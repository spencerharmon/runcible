import unittest
from unittest.mock import Mock

from runcible.drivers.omada import OmadaDriver
from runcible.drivers.driver import DriverBase
from runcible.protocols.rest_protocol import RestProtocol
from runcible.core.plugin_registry import PluginRegistry


class TestOmadaDriver(unittest.TestCase):
    longMessage = True

    def test_is_driver_subclass(self):
        self.assertTrue(issubclass(OmadaDriver, DriverBase))

    def test_driver_name(self):
        self.assertEqual(OmadaDriver.driver_name, "omada")

    def test_protocol_map_binds_rest(self):
        self.assertIn("rest", OmadaDriver.protocol_map)
        self.assertIs(OmadaDriver.protocol_map["rest"], RestProtocol)

    def test_module_provider_map_starts_empty(self):
        # Filled in incrementally by the per-module Omada provider tasks.
        self.assertEqual(OmadaDriver.module_provider_map, {})

    def test_driver_registers_and_loads(self):
        PluginRegistry.drivers = {}
        driver = PluginRegistry.get_driver("omada")
        self.assertIs(driver, OmadaDriver)

    def test_lifecycle_selects_site(self):
        device = Mock()
        device.meta_device = {"site": "Default"}
        OmadaDriver.pre_plan_tasks(device)
        device.store.assert_called_with('omada_site', "Default")

        device.reset_mock()
        device.meta_device = {"site": "Default"}
        OmadaDriver.pre_exec_tasks(device)
        device.store.assert_called_with('omada_site', "Default")


if __name__ == "__main__":
    unittest.main()
