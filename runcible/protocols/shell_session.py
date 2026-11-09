"""Prompt-driven interactive shell session over a byte stream.

Vyatta-derived systems (EdgeOS, VyOS) only expose their configuration CLI
(``configure`` / ``set`` / ``delete`` / ``commit`` / ``save``) inside ONE
long-lived interactive ``vbash`` session: configure mode is per-session state,
so each command cannot be run in a fresh ``exec`` channel. This module holds
the transport-agnostic engine that drives such a session: it writes a command,
then reads until a unique end-of-command sentinel carrying the command's exit
status, and returns the output that preceded it.

The same engine is used over a serial console (pyserial) and over an SSH
interactive shell (paramiko ``invoke_shell``); only the byte transport differs.

A transport is any object with:

* ``write(data: bytes) -> None``
* ``read(timeout: float) -> bytes`` -- return whatever bytes are available,
  waiting at most ``timeout`` seconds; ``b''`` when nothing arrived.
"""
import re
import time
import uuid

from runcible.core.errors import RuncibleConnectionError

# CSI / OSC escape sequences emitted by readline / the kernel console.
_ANSI_RE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>]')
# A shell prompt at the very end of the buffer: ``user@host:~$ `` (op mode) or
# ``user@host# `` (configure mode).
PROMPT_RE = re.compile(r'(?:^|[\r\n])[^\r\n]*[$#] ?$')
CONFIG_PROMPT_RE = re.compile(r'(?:^|[\r\n])[^\r\n]*# ?$')
OP_PROMPT_RE = re.compile(r'(?:^|[\r\n])[^\r\n]*\$ ?$')
LOGIN_RE = re.compile(r'login: ?$', re.IGNORECASE)
PASSWORD_RE = re.compile(r'password: ?$', re.IGNORECASE)


def clean(text):
    """Strip ANSI escapes and normalise line endings to ``\\n``."""
    text = _ANSI_RE.sub('', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text


class ShellTimeout(RuncibleConnectionError):
    pass


class ShellSession(object):

    def __init__(self, transport, encoding='utf-8', quiet=1.0):
        """
        :param quiet:
            Seconds of silence that mark the end of unsolicited output (banners,
            login prompts). Command output is delimited by a sentinel instead.
        """
        self.transport = transport
        self.encoding = encoding
        self.quiet = quiet
        self.buffer = ''

    # -- low level -----------------------------------------------------------

    def write(self, text):
        self.transport.write(text.encode(self.encoding))

    def _pump(self, timeout):
        data = self.transport.read(timeout)
        if data:
            self.buffer += data.decode(self.encoding, errors='replace')
        return bool(data)

    def read_until(self, pattern, timeout):
        """Read until ``pattern`` (a compiled regex) matches the cleaned buffer.

        Returns the cleaned buffer (and empties it). Raises ShellTimeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            text = clean(self.buffer)
            match = pattern.search(text)
            if match:
                self.buffer = ''
                return text, match
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ShellTimeout(
                    msg=f"Timed out after {timeout}s waiting for {pattern.pattern!r}; "
                        f"last output: {text[-300:]!r}")
            self._pump(min(remaining, 0.5))

    def read_quiet(self, quiet=1.0, timeout=10.0):
        """Read until no bytes arrive for ``quiet`` seconds; return cleaned text."""
        deadline = time.monotonic() + timeout
        last = time.monotonic()
        while time.monotonic() < deadline:
            if self._pump(0.2):
                last = time.monotonic()
            elif time.monotonic() - last >= quiet:
                break
        text = clean(self.buffer)
        self.buffer = ''
        return text

    # -- command execution ---------------------------------------------------

    def run(self, command, timeout=60.0, status=True):
        """Run ``command`` at the current prompt.

        :param status:
            When True the command's exit status is captured by appending a
            sentinel to the same line. Vyatta's configure mode hands the WHOLE
            line (``;``/``&&`` included) to ``set``/``delete``, so there the
            caller passes False: the sentinel is sent as a separate line and the
            returned status is None (failures must be detected from output).
        :return: ``(output, exit_status)``. Output excludes any echo of the
            command line, the sentinel, ``[edit]`` markers and prompts.
        """
        token = uuid.uuid4().hex[:12]
        if status:
            # The status is embedded in the sentinel; the literal variable
            # reference in any echoed copy of the line can never match the digit
            # pattern. ${PIPESTATUS[0]} is used instead of $? because Vyatta's
            # vbash binds '?' to inline help, swallowing it at the prompt.
            sentinel = re.compile(rf'__RC_{token}=(\d+)__')
            self.write(f"{command}; echo __RC_{token}=${{PIPESTATUS[0]}}__\r")
        else:
            # Arithmetic expansion: only the shell's output can contain "42".
            sentinel = re.compile(rf'__RC_{token}=(42)__')
            self.write(f"{command}\r")
            self.write(f"echo __RC_{token}=$((6*7))__\r")
        text, match = self.read_until(sentinel, timeout)
        exit_status = int(match.group(1)) if status else None
        output = text[:match.start()]
        # Consume the prompt that follows the sentinel.
        tail = text[match.end():]
        if not PROMPT_RE.search(tail):
            self.read_until(PROMPT_RE, timeout)
        return self._strip_echo(output, command, token, separate_sentinel=not status), exit_status

    def transition(self, command, prompt, timeout=60.0):
        """Send a mode-changing command (``configure`` / ``exit``) on its own.

        On Vyatta these replace the running shell, so nothing may follow them
        on the same line (no sentinel) and terminal settings are reset: the
        caller must re-apply its session setup. Waits for ``prompt``.
        """
        self.write(f"{command}\r")
        text, _ = self.read_until(prompt, timeout)
        return text

    @staticmethod
    def _strip_echo(output, command, token, separate_sentinel=False):
        lines = output.split('\n')
        kept = []
        for line in lines:
            if f'__RC_{token}' in line:
                # echoed command line (terminal echo still on)
                continue
            if line.strip() == '[edit]':
                continue
            if PROMPT_RE.fullmatch(line) and line.rstrip().endswith(command):
                # prompt + echoed command
                continue
            kept.append(line)
        # Echoed command line (terminal echo on, e.g. before session setup).
        if separate_sentinel and kept and command.strip() and kept[0].rstrip().endswith(command.strip()):
            kept.pop(0)
        # A prompt printed between a command and a separately-sent sentinel.
        if kept and PROMPT_RE.search(kept[-1]) and kept[-1].rstrip()[-1:] in '$#':
            kept.pop()
        # Drop leading/trailing blank lines but keep inner structure.
        while kept and not kept[0].strip():
            kept.pop(0)
        while kept and not kept[-1].strip():
            kept.pop()
        return '\n'.join(kept)

    # -- session lifecycle ----------------------------------------------------

    def login(self, username, password, timeout=30.0):
        """Bring a console to an operational-mode shell prompt.

        Handles the four states a serial console can be left in: a login
        prompt, a dangling password prompt, an op-mode shell, or a configure
        mode shell (whose uncommitted changes are discarded).
        """
        self.write('\r')
        for _ in range(6):
            text = self.read_quiet(quiet=self.quiet, timeout=timeout)
            tail = text.rstrip('\n')
            if LOGIN_RE.search(tail):
                if username is None:
                    raise RuncibleConnectionError(msg="Console is at a login prompt but no username is configured")
                self.write(f"{username}\r")
                self.read_until(PASSWORD_RE, timeout)
                if password is None:
                    raise RuncibleConnectionError(msg="Console requested a password but none is configured")
                self.write(f"{password}\r")
                text = self.read_quiet(quiet=self.quiet * 2, timeout=timeout)
                if 'incorrect' in text.lower():
                    raise RuncibleConnectionError(msg=f"Console login failed for user {username}")
                if PROMPT_RE.search(text.rstrip('\n')) and not LOGIN_RE.search(text.rstrip('\n')):
                    return
                self.write('\r')
                continue
            if PASSWORD_RE.search(tail):
                # Abandon a half-finished login.
                self.write('\r')
                continue
            if CONFIG_PROMPT_RE.search(tail):
                self.write('exit discard\r')
                continue
            if PROMPT_RE.search(tail):
                return
            # Unknown / boot noise: poke it again.
            self.write('\r')
        raise RuncibleConnectionError(msg="Could not reach a shell prompt on the console")

    def logout(self, timeout=10.0, restore_tty=None):
        """Leave configure mode (discarding), restore tty settings, log out.

        :param restore_tty:
            ``stty -g`` output captured at login. The console tty outlives the
            session, so settings changed for automation (no echo, a 4096-column
            window) would otherwise break the next interactive login.
        """
        self.write('\r')
        text = self.read_quiet(quiet=self.quiet / 2, timeout=timeout).rstrip('\n')
        if CONFIG_PROMPT_RE.search(text):
            self.write('exit discard\r')
            self.read_quiet(quiet=self.quiet / 2, timeout=timeout)
        if restore_tty:
            self.write(f"stty {restore_tty}\r")
        else:
            self.write("stty sane cols 80 rows 24\r")
        self.read_quiet(quiet=self.quiet / 2, timeout=timeout)
        self.write('exit\r')
        self.read_quiet(quiet=self.quiet / 2, timeout=timeout)
