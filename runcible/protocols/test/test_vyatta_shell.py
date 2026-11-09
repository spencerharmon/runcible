import os
import unittest
from unittest import mock

from runcible.core.errors import RuncibleClientExecutionError, RuncibleConnectionError, RuncibleNotConnectedError
from runcible.protocols.shell_session import ShellSession
from runcible.protocols.vyatta_shell import VyattaSerialProtocol, VyattaSSHProtocol, resolve_env
from runcible.protocols.test.fake_vyatta import FakeVyatta


class FakeSerialProtocol(VyattaSerialProtocol):
    """VyattaSerialProtocol wired to an in-memory console instead of a tty."""

    def __init__(self, config, fake):
        self.fake = fake
        super().__init__(config)

    def open_transport(self):
        return self.fake

    def close_transport(self):
        self.closed = True


def serial(fake, **extra):
    config = {'device': '/dev/ttyUSB0', 'username': 'admin', 'password': 'secret', 'quiet': 0.05, 'timeout': 5}
    config.update(extra)
    return FakeSerialProtocol(config, fake)


class TestShellSession(unittest.TestCase):

    def test_run_strips_echo_and_returns_status(self):
        fake = FakeVyatta(logged_in=True, config=["set system host-name router"])
        session = ShellSession(fake, quiet=0.05)
        output, status = session.run("show configuration commands", timeout=5)
        self.assertEqual(status, 0)
        self.assertEqual(output, "set system host-name router")

    def test_run_reports_failure_status(self):
        fake = FakeVyatta(logged_in=True)
        session = ShellSession(fake, quiet=0.05)
        output, status = session.run("frobnicate", timeout=5)
        self.assertEqual(status, 1)
        self.assertIn("Invalid command", output)

    def test_configure_mode_edit_marker_and_prompt_are_stripped(self):
        fake = FakeVyatta(logged_in=True, configure=True)
        session = ShellSession(fake, quiet=0.05)
        output, status = session.run("set system host-name x", timeout=5, status=False)
        self.assertEqual((output, status), ('', None))
        self.assertIn("set system host-name x", fake.working)

    def test_configure_mode_rejects_chained_sentinel(self):
        # Regression (real EdgeOS v2.0): vbash configure mode passes the whole
        # line to `set`, so `set ...; echo` fails; status=False must be used.
        fake = FakeVyatta(logged_in=True, configure=True)
        session = ShellSession(fake, quiet=0.05)
        output, _ = session.run("set system host-name x", timeout=5, status=False)
        self.assertNotIn("not valid", output)
        output, _ = session.run("set bogus", timeout=5, status=False)
        self.assertIn("Set failed", output)


class TestVyattaSerialProtocol(unittest.TestCase):

    def test_validation_requires_device_and_username(self):
        from runcible.core.errors import RuncibleValidationError
        with self.assertRaises(RuncibleValidationError):
            VyattaSerialProtocol({'username': 'admin'})
        with self.assertRaises(RuncibleValidationError):
            VyattaSerialProtocol({'device': '/dev/ttyUSB0'})

    def test_send_before_connect_raises_not_connected(self):
        proto = serial(FakeVyatta())
        with self.assertRaises(RuncibleNotConnectedError):
            proto.run_command("show version")

    def test_login_from_login_prompt_and_session_setup(self):
        fake = FakeVyatta()
        proto = serial(fake)
        proto.connect()
        self.assertEqual(fake.state, 'shell')
        self.assertFalse(fake.echo, "session setup must disable terminal echo")
        self.assertTrue(any(c.startswith('export VYATTA_PAGER=cat') for c in fake.commands))

    def test_bad_password_raises(self):
        proto = serial(FakeVyatta(), password='wrong')
        with self.assertRaises(RuncibleConnectionError):
            proto.connect()

    def test_password_from_environment(self):
        fake = FakeVyatta()
        proto = serial(fake, password='${TEST_RUNCIBLE_PW}')
        with mock.patch.dict(os.environ, {'TEST_RUNCIBLE_PW': 'secret'}):
            proto.connect()
        self.assertEqual(fake.state, 'shell')

    def test_unset_environment_variable_is_an_error(self):
        os.environ.pop('TEST_RUNCIBLE_UNSET', None)
        with self.assertRaises(RuncibleConnectionError):
            resolve_env('${TEST_RUNCIBLE_UNSET}', 'password')

    def test_already_logged_in_console_is_reused(self):
        fake = FakeVyatta(logged_in=True)
        proto = serial(fake, password=None)
        proto.connect()
        self.assertEqual(fake.state, 'shell')

    def test_dangling_configure_session_is_discarded(self):
        fake = FakeVyatta(logged_in=True, configure=True, config=["set system host-name a"])
        fake.working.append("set system host-name b")
        proto = serial(fake)
        proto.connect()
        self.assertFalse(fake.configure)
        self.assertEqual(fake.working, fake.committed)

    def test_configure_session_persists_across_commands(self):
        fake = FakeVyatta(config=["set system host-name old"])
        proto = serial(fake)
        proto.connect()
        proto.run_command("configure")
        proto.run_command("set system host-name new")
        proto.run_command("commit")
        proto.run_command("save")
        proto.run_command("exit")
        self.assertEqual(proto.run_command("show configuration commands"), "set system host-name new")

    def test_set_failure_raises(self):
        proto = serial(FakeVyatta())
        proto.connect()
        proto.run_command("configure")
        with self.assertRaises(RuncibleClientExecutionError):
            proto.run_command("set bogus path")

    def test_disconnect_restores_tty_settings(self):
        # Regression: a 4096-column, no-echo console tty outlived the session
        # and broke the operator's next interactive login on the console.
        fake = FakeVyatta()
        proto = serial(fake)
        proto.connect()
        self.assertFalse(fake.echo)
        proto.disconnect()
        self.assertEqual(fake.stty_history[-1], ["500:5:bf:8a3b:3:1c:7f:15:4:0:1:0:11:13:1a:0:12:f:17:16:0:0:0",
                                                 "rows", "24", "cols", "80"])
        self.assertTrue(fake.echo)

    def test_disconnect_logs_out(self):
        fake = FakeVyatta()
        proto = serial(fake)
        proto.connect()
        proto.run_command("configure")
        proto.run_command("set system host-name pending")
        proto.disconnect()
        self.assertEqual(fake.state, 'login')
        self.assertFalse(fake.configure)
        self.assertIsNone(proto.session)


class TestVyattaSSHProtocol(unittest.TestCase):

    def test_validation(self):
        from runcible.core.errors import RuncibleValidationError
        with self.assertRaises(RuncibleValidationError):
            VyattaSSHProtocol({'hostname': 'router.example.com'})
        VyattaSSHProtocol({'hostname': 'router.example.com', 'username': 'admin'})

    def test_uses_interactive_shell(self):
        fake = FakeVyatta(logged_in=True, config=["set system host-name r"])
        channel = mock.Mock()
        channel.sendall.side_effect = fake.write
        channel.recv.side_effect = lambda n: fake.read(0.01)
        with mock.patch('paramiko.SSHClient') as client_cls:
            client_cls.return_value.invoke_shell.return_value = channel
            proto = VyattaSSHProtocol({'hostname': 'router.example.com', 'username': 'admin', 'quiet': 0.05,
                                       'timeout': 5})
            proto.connect()
            client_cls.return_value.invoke_shell.assert_called_once()
            self.assertEqual(proto.run_command("show configuration commands"), "set system host-name r")


if __name__ == '__main__':
    unittest.main()
