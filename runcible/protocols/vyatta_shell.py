"""Interactive-shell protocols for Vyatta-derived devices (EdgeOS, VyOS).

Both protocols drive ONE persistent ``vbash`` session through
:class:`runcible.protocols.shell_session.ShellSession`, so configure-mode state
(``configure`` -> ``set``/``delete`` -> ``commit`` -> ``save``) survives
between commands and a device document behaves identically whichever
transport is selected:

* ``serial`` -- :class:`VyattaSerialProtocol`, an RS-232 console (pyserial).
  Required keys: ``device`` (e.g. ``/dev/ttyUSB0``), ``username``.
  Optional: ``speed`` (default 115200), ``password``, ``timeout``.
* ``ssh``    -- :class:`VyattaSSHProtocol`, a paramiko interactive shell.
  Required keys: ``hostname``, ``username``.
  Optional: ``port`` (22), ``password``, ``key_filename``, ``timeout``.

Secrets are never required to live in a device document: any string config
value of the form ``${NAME}`` is resolved from the environment variable
``NAME`` at connect time (an unset variable is a validation error).
"""
import re

from runcible.core.errors import (
    RuncibleClientExecutionError,
    RuncibleConnectionError,
    RuncibleNotConnectedError,
    RuncibleValidationError,
)
from runcible.protocols.config import resolve_env
from runcible.protocols.protocol import TerminalProtocolBase
from runcible.protocols.shell_session import ShellSession, CONFIG_PROMPT_RE, PROMPT_RE

# Run once after reaching an op-mode prompt: no echo (so output is exactly the
# command's), no line wrapping, and no pager on show commands.
SESSION_SETUP = [
    # (EdgeOS' stty rejects 'rows 0'.)
    'stty -echo cols 4096',
    # readline caches the window size; make it re-read the new width so long
    # command lines are not redrawn/wrapped into the output.
    'kill -WINCH $$',
    'export VYATTA_PAGER=cat',
]

# Configure-mode output that indicates failure even when vbash returns 0.
_ERROR_MARKERS = (
    'set failed',
    'delete failed',
    'commit failed',
    'is not valid',
    'invalid command',
    'error:',
    'nothing to delete',
    'not valid',
)
_CONFIGURE_VERBS = ('set', 'delete', 'commit', 'commit-confirm', 'save', 'configure')


class VyattaShellProtocolBase(TerminalProtocolBase):
    required_keys = ()
    default_timeout = 120

    def __init__(self, config: dict):
        self.session = None
        self.in_configure = False
        self._saved_tty = None
        super().__init__(config=config)

    def validate(self, config):
        for key in self.required_keys:
            if key not in config:
                raise RuncibleValidationError(msg=f"Key {key} missing from protocol {self.__repr__()}")

    def _cfg(self, key, default=None):
        return resolve_env(getattr(self, key, default), key)

    # Subclasses implement these two.
    def open_transport(self):
        raise NotImplementedError

    def close_transport(self):
        raise NotImplementedError

    def authenticate(self):
        """Bring the fresh session to an op-mode prompt."""
        raise NotImplementedError

    def connect(self):
        transport = self.open_transport()
        self.session = ShellSession(transport, quiet=float(self._cfg('quiet', 1.0)))
        self.in_configure = False
        self.authenticate()
        # The console's tty settings (echo, window size) outlive this login: the
        # next interactive user inherits them. Save them to restore on logout.
        timeout = float(self._cfg('timeout', self.default_timeout))
        output, _ = self.session.run('stty -g', timeout=timeout)
        lines = [line.strip() for line in output.splitlines() if ':' in line]
        saved = lines[-1] if lines else 'sane'
        # `stty -g` omits the window size; save it too (EdgeOS rejects 0 rows/cols).
        output, _ = self.session.run('stty size', timeout=timeout)
        size = re.findall(r'^\s*(\d+)\s+(\d+)\s*$', output, re.M)
        rows, cols = size[-1] if size else ('24', '80')
        if rows == '0' or cols == '0':
            rows, cols = '24', '80'
        self._saved_tty = f"{saved} rows {rows} cols {cols}"
        self._setup_shell()

    def _setup_shell(self):
        # Best effort: on EdgeOS the first command after login can report a
        # stale non-zero status even though it took effect, and none of these
        # are required for correctness (the sentinel framing tolerates echo).
        for command in SESSION_SETUP:
            self.session.run(command, timeout=float(self._cfg('timeout', self.default_timeout)),
                             status=not self.in_configure)

    def disconnect(self):
        if self.session is not None:
            try:
                self.session.logout(restore_tty=getattr(self, '_saved_tty', None))
            finally:
                self.close_transport()
                self.session = None

    def _run_checked(self, command, timeout=None):
        if self.session is None:
            raise RuncibleNotConnectedError(msg="Activate with self.connect() before executing")
        verb = command.split(' ', 1)[0]
        # configure/exit replace the running vbash: send them bare, wait for the
        # new mode's prompt, then restore terminal settings in the new shell.
        if command.strip() == 'configure':
            self.session.transition(command, CONFIG_PROMPT_RE, timeout or 60)
            self.in_configure = True
            self._setup_shell()
            return ''
        if verb == 'exit':
            text = self.session.transition(command, PROMPT_RE, timeout or 60)
            if 'cannot exit' in text.lower() or CONFIG_PROMPT_RE.search(text.rstrip('\n')):
                raise RuncibleClientExecutionError(msg=text, command=command, system=self.system_name())
            self.in_configure = False
            self._setup_shell()
            return ''
        if timeout is None:
            timeout = float(self._cfg('timeout', self.default_timeout))
            if verb in ('commit', 'commit-confirm', 'save'):
                # Commits on small MIPS boxes can take minutes for a full config.
                timeout = max(timeout, 900)
        output, status = self.session.run(command, timeout=timeout, status=not self.in_configure)
        lowered = output.lower()
        configure_verb = verb in _CONFIGURE_VERBS
        failed = status is not None and status != 0
        if failed or (configure_verb and any(marker in lowered for marker in _ERROR_MARKERS)):
            raise RuncibleClientExecutionError(msg=f"exit status {status}: {output}", command=command,
                                               system=self.system_name())
        return output

    def send_implement(self, command):
        return self._run_checked(command)

    def system_name(self):
        return str(self)


class VyattaSerialProtocol(VyattaShellProtocolBase):
    required_keys = ('device', 'username')

    def __init__(self, config: dict):
        self.serial = None
        super().__init__(config)

    def open_transport(self):
        from serial import Serial  # imported lazily: optional at import time
        try:
            self.serial = Serial(self._cfg('device'), int(self._cfg('speed', 115200)),
                                 bytesize=8, parity='N', stopbits=1,
                                 xonxoff=False, rtscts=False, dsrdtr=False,
                                 timeout=0, exclusive=True)
        except Exception as e:
            raise RuncibleConnectionError(msg=f"Unable to open serial device {self._cfg('device')}: {e}")
        return _SerialTransport(self.serial)

    def close_transport(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def authenticate(self):
        self.session.login(self._cfg('username'), self._cfg('password'))

    def system_name(self):
        return getattr(self, 'device', 'serial')


class VyattaSSHProtocol(VyattaShellProtocolBase):
    required_keys = ('hostname', 'username')

    def __init__(self, config: dict):
        self.client = None
        super().__init__(config)

    def open_transport(self):
        from paramiko import SSHClient, RejectPolicy
        self.client = SSHClient()
        self.client.load_system_host_keys()
        self.client.set_missing_host_key_policy(RejectPolicy)
        try:
            self.client.connect(hostname=self._cfg('hostname'),
                                port=int(self._cfg('port', 22)),
                                username=self._cfg('username'),
                                password=self._cfg('password'),
                                key_filename=self._cfg('key_filename'))
        except Exception as e:
            raise RuncibleConnectionError(msg=f"SSH connection to {self._cfg('hostname')} failed: {e}")
        channel = self.client.invoke_shell(term='dumb', width=4096, height=0)
        return _ChannelTransport(channel)

    def close_transport(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def authenticate(self):
        # SSH already authenticated; just wait for the first prompt.
        self.session.write('\r')
        self.session.read_quiet(quiet=1.0, timeout=30)

    def system_name(self):
        return getattr(self, 'hostname', 'ssh')


class _SerialTransport(object):
    def __init__(self, port):
        self.port = port

    def write(self, data):
        self.port.write(data)
        self.port.flush()

    def read(self, timeout):
        import select
        ready, _, _ = select.select([self.port.fileno()], [], [], timeout)
        if not ready:
            return b''
        return self.port.read(self.port.in_waiting or 1)


class _ChannelTransport(object):
    def __init__(self, channel):
        self.channel = channel

    def write(self, data):
        self.channel.sendall(data)

    def read(self, timeout):
        self.channel.settimeout(timeout)
        try:
            return self.channel.recv(65535)
        except Exception:
            return b''
