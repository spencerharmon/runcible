"""A tiny in-memory Vyatta/EdgeOS console simulator for protocol/driver tests.

It speaks the byte-level dialogue a real console does -- login prompt,
op/configure prompts, terminal echo (until ``stty -echo``) -- and keeps a
working + committed configuration so ``show configuration commands`` reflects
committed ``set``/``delete`` statements.
"""
import shlex
import time


class FakeVyatta(object):

    def __init__(self, username='admin', password='secret', hostname='router',
                 config=None, logged_in=False, configure=False):
        self.username = username
        self.password = password
        self.hostname = hostname
        self.committed = list(config or [])
        self.working = list(self.committed)
        self.state = 'shell' if logged_in else 'login'
        self.configure = configure
        self.echo = True
        self.out = b''
        self.inbuf = ''
        self.commands = []          # every shell command line received
        self.pending_user = None
        self.stty_history = []

    # -- transport interface -------------------------------------------------
    def write(self, data):
        self.inbuf += data.decode()
        while '\r' in self.inbuf:
            line, self.inbuf = self.inbuf.split('\r', 1)
            self._line(line)

    def read(self, timeout):
        data, self.out = self.out, b''
        if not data:
            time.sleep(min(timeout, 0.005))
        return data

    # -- simulation ------------------------------------------------------------
    def _emit(self, text):
        self.out += text.replace('\n', '\r\n').encode()

    def prompt(self):
        if self.state == 'login':
            return f"{self.hostname} login: "
        if self.state == 'password':
            return "Password: "
        if self.configure:
            return f"[edit]\n{self.username}@{self.hostname}# "
        return f"{self.username}@{self.hostname}:~$ "

    def _line(self, line):
        if self.state == 'login':
            self._emit(line + '\n')
            if line:
                self.pending_user = line
                self.state = 'password'
            self._emit(self.prompt())
            return
        if self.state == 'password':
            self._emit('\n')
            if self.pending_user == self.username and line == self.password:
                self.state = 'shell'
                self._emit("Welcome to EdgeOS\n")
            else:
                self.state = 'login'
                self._emit("\nLogin incorrect\n")
            self._emit(self.prompt())
            return
        if self.echo:
            self._emit(line + '\n')
        self.commands.append(line)
        status = 0
        if self.configure and line.split()[:1] and line.split()[0] in ('set', 'delete', 'commit', 'save'):
            # vbash configure mode hands the whole line to the config command.
            if ';' in line or '&&' in line:
                self._emit("The specified configuration node is not valid\nSet failed\n")
            else:
                self._command(line)
            self._emit(self.prompt())
            return
        for part in [p.strip() for p in line.split(';')]:
            if not part:
                continue
            if part.startswith('echo '):
                if '?' in part:
                    # vbash binds '?' to inline help; a real console would mangle this.
                    raise AssertionError(f"'?' sent to a Vyatta console: {part!r}")
                self._emit(part[5:].replace('${PIPESTATUS[0]}', str(status)).replace('$((6*7))', '42') + '\n')
                continue
            status = self._command(part)
            if self.state == 'login':
                self._emit(self.prompt())
                return
            if part.split()[0] in ('configure', 'exit') and status == 0:
                # Like vbash: entering/leaving configure replaces the shell, so the
                # rest of the line is lost and terminal settings are reset.
                self.echo = True
                break
        self._emit(self.prompt())

    def _command(self, cmd):
        tokens = shlex.split(cmd)
        verb = tokens[0]
        if verb == 'stty':
            if tokens[1:] == ['size']:
                self._emit("24 80\n")
                return 0
            if tokens[1:] == ['-g']:
                self._emit("500:5:bf:8a3b:3:1c:7f:15:4:0:1:0:11:13:1a:0:12:f:17:16:0:0:0\n")
                return 0
            self.stty_history.append(tokens[1:])
            if '-echo' in tokens:
                self.echo = False
            elif len(tokens) >= 2 and ':' in tokens[1]:
                self.echo = True   # restored saved settings
            return 0
        if verb in ('export', 'kill'):
            return 0
        if verb == 'exit':
            if self.configure:
                if self.working != self.committed and 'discard' not in tokens:
                    self._emit("Cannot exit: configuration modified.\n")
                    return 1
                self.working = list(self.committed)
                self.configure = False
                return 0
            self.state = 'login'
            self.echo = True
            self._emit('logout\n')
            return 0
        if verb == 'configure':
            self.configure = True
            return 0
        if verb == 'show' and tokens[1:] == ['configuration', 'commands']:
            for line in self.committed:
                self._emit(line + '\n')
            return 0
        if self.configure and verb == 'set':
            path = tokens[1:]
            if path and path[0] == 'bogus':
                self._emit(f"  Configuration path: [{' '.join(path)}] is not valid\n  Set failed\n")
                return 1
            stmt = 'set ' + ' '.join(self._q(t) for t in path)
            if stmt not in self.working:
                # single-value leaves replace their previous value
                self.working = [w for w in self.working if not self._replaces(w, path)]
                self.working.append(stmt)
            return 0
        if self.configure and verb == 'delete':
            path = tokens[1:]
            before = len(self.working)
            self.working = [w for w in self.working if shlex.split(w)[1:len(path) + 1] != path]
            if len(self.working) == before:
                self._emit("Nothing to delete\n")
                return 1
            return 0
        if self.configure and verb in ('commit', 'save'):
            if verb == 'commit':
                self.committed = list(self.working)
            return 0
        self._emit(f"Invalid command: {cmd}\n")
        return 1

    SINGLE_VALUE_LEAVES = ('host-name', 'domain-name', 'time-zone', 'level', 'full-name',
                           'encrypted-password', 'type', 'key')

    def _replaces(self, existing, path):
        old = shlex.split(existing)[1:]
        return (len(old) == len(path) and old[:-1] == path[:-1]
                and path[-2] in self.SINGLE_VALUE_LEAVES)

    @staticmethod
    def _q(token):
        if any(ch.isspace() for ch in token) or '$' in token:
            return f"'{token}'"
        return token
