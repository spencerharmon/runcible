import unittest
from unittest.mock import Mock

from runcible.drivers.edgeos import EdgeOSDriver
from runcible.drivers.driver import DriverBase
from runcible.protocols.ssh_protocol import SSHProtocol
from runcible.core.plugin_registry import PluginRegistry
from runcible.providers.edgeos.system import EdgeOSSystemProvider


class TestEdgeOSDriver(unittest.TestCase):
    longMessage = True

    def test_is_driver_subclass(self):
        self.assertTrue(issubclass(EdgeOSDriver, DriverBase))

    def test_driver_name(self):
        self.assertEqual(EdgeOSDriver.driver_name, "edgeos")

    def test_protocol_map_binds_ssh(self):
        self.assertIn("ssh", EdgeOSDriver.protocol_map)
        self.assertIs(EdgeOSDriver.protocol_map["ssh"], SSHProtocol)

    def test_module_provider_map_registers_system_provider(self):
        # Filled in incrementally by the per-module provider tasks
        # (edgeos-system-provider, edgeos-interfaces-provider,
        #  edgeos-static-route-provider, edgeos-bgp-provider).
        self.assertIn("system", EdgeOSDriver.module_provider_map)
        self.assertIs(
            EdgeOSDriver.module_provider_map["system"],
            EdgeOSSystemProvider,
        )

    def test_module_provider_map_binds_interfaces(self):
        from runcible.providers.edgeos.interfaces import EdgeOSInterfacesProvider
        self.assertIn("interfaces", EdgeOSDriver.module_provider_map)
        self.assertIs(
            EdgeOSDriver.module_provider_map["interfaces"],
            EdgeOSInterfacesProvider,
        )

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
