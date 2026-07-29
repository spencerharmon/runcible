import unittest
from unittest.mock import Mock

from runcible.drivers.edgeos import EdgeOSDriver
from runcible.drivers.driver import DriverBase
from runcible.protocols.ssh_protocol import SSHProtocol
from runcible.core.plugin_registry import PluginRegistry


class TestEdgeOSDriver(unittest.TestCase):
    longMessage = True

    def test_is_driver_subclass(self):
        self.assertTrue(issubclass(EdgeOSDriver, DriverBase))

    def test_driver_name(self):
        self.assertEqual(EdgeOSDriver.driver_name, "edgeos")

    def test_protocol_map_binds_ssh(self):
        self.assertIn("ssh", EdgeOSDriver.protocol_map)
        self.assertIs(EdgeOSDriver.protocol_map["ssh"], SSHProtocol)

    def test_module_provider_map_starts_empty(self):
        self.assertEqual(EdgeOSDriver.module_provider_map, {})

    def test_driver_registers_and_loads(self):
        PluginRegistry.drivers = {}
        driver = PluginRegistry.get_driver("edgeos")
        self.assertIs(driver, EdgeOSDriver)

    def test_lifecycle_hooks(self):
        device = Mock()
        EdgeOSDriver.pre_exec_tasks(device)
        device.send_command.assert_called_with('configure')

        device.reset_mock()
        EdgeOSDriver.post_exec_tasks(device)
        device.send_command.assert_any_call('commit')
        device.send_command.assert_any_call('save')

        device.reset_mock()
        device.send_command.return_value = "set system host-name foo"
        EdgeOSDriver.pre_plan_tasks(device)
        device.send_command.assert_called_with(
            "show configuration commands", memoize=True
        )
        device.store.assert_called_with(
            'parsed_commands', ["set system host-name foo"]
        )


if __name__ == "__main__":
    unittest.main()
