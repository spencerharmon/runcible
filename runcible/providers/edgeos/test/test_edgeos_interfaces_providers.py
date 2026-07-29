import unittest
from unittest.mock import Mock

from runcible.providers.edgeos.interfaces import EdgeOSInterfacesProvider
from runcible.providers.edgeos.interface import EdgeOSInterfaceProvider
from runcible.modules.interface import InterfaceResources
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.test_utilities import append_operation_test_cases


system_dict = {}
device = Mock()
prov = EdgeOSInterfacesProvider(device, {})


class TestInterfaceNeedCompletion(unittest.TestCase):
    longMessage = True


# Auto-generated per-operation smoke tests (mirrors the cumulus suite): each
# supported attribute/operation must drive fix_needs to completion.
append_operation_test_cases(prov, system_dict, TestInterfaceNeedCompletion)


class TestEdgeOSInterfacesGetCstate(unittest.TestCase):
    longMessage = True

    def _provider_with_commands(self, commands):
        dev = Mock()
        dev.retrieve.return_value = commands
        return EdgeOSInterfacesProvider(dev, {})

    def test_parses_single_address(self):
        commands = [
            "set interfaces ethernet eth0 address 192.168.1.1/24",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        interfaces = {i.name: i for i in cstate.interfaces}
        self.assertIn("eth0", interfaces)
        self.assertEqual(
            interfaces["eth0"].ipv4_addresses, ["192.168.1.1/24"])

    def test_parses_multiple_addresses(self):
        commands = [
            "set interfaces ethernet eth1 address 10.0.0.1/24",
            "set interfaces ethernet eth1 address 10.0.1.1/24",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        interfaces = {i.name: i for i in cstate.interfaces}
        self.assertEqual(
            interfaces["eth1"].ipv4_addresses,
            ["10.0.0.1/24", "10.0.1.1/24"],
        )

    def test_ignores_non_interface_lines(self):
        commands = [
            "set system host-name router",
            "set interfaces ethernet eth0 address 192.168.1.1/24",
            "set service ssh port 22",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        interfaces = {i.name: i for i in cstate.interfaces}
        self.assertEqual(list(interfaces.keys()), ["eth0"])

    def test_ignores_dhcp_and_ipv6_addresses(self):
        commands = [
            "set interfaces ethernet eth0 address dhcp",
            "set interfaces ethernet eth0 address 2001:db8::1/64",
            "set interfaces ethernet eth0 address 192.168.1.1/24",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        interfaces = {i.name: i for i in cstate.interfaces}
        self.assertEqual(
            interfaces["eth0"].ipv4_addresses, ["192.168.1.1/24"])

    def test_bare_interface_declaration_has_no_addresses(self):
        commands = [
            "set interfaces ethernet eth2",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        interfaces = {i.name: i for i in cstate.interfaces}
        self.assertIn("eth2", interfaces)
        self.assertIsNone(
            getattr(interfaces["eth2"], InterfaceResources.IPV4_ADDRESSES, None))


class TestEdgeOSInterfaceCommandGeneration(unittest.TestCase):
    """Assert the REAL set/delete command lists against known states."""

    longMessage = True

    def _fix(self, cstate_commands, dstate):
        """Run a full determine_needs/fix_needs cycle and return the list of
        commands sent to the device."""
        dev = Mock()
        dev.retrieve.return_value = cstate_commands
        sent = []
        dev.send_command.side_effect = lambda cmd, *a, **k: sent.append(cmd)
        provider = EdgeOSInterfacesProvider(dev, dstate)
        provider.load_module_cstate()
        provider.determine_needs()
        provider.fix_needs()
        return sent

    def test_add_address_to_empty_interface(self):
        sent = self._fix(
            ["set interfaces ethernet eth0"],
            [{"name": "eth0", "ipv4_addresses": ["192.168.1.1/24"]}],
        )
        self.assertIn(
            "set interfaces ethernet eth0 address 192.168.1.1/24", sent)

    def test_remove_address(self):
        sent = self._fix(
            ["set interfaces ethernet eth0 address 192.168.1.1/24"],
            [{"name": "eth0", "ipv4_addresses": []}],
        )
        self.assertIn(
            "delete interfaces ethernet eth0 address 192.168.1.1/24", sent)

    def test_change_address_reip(self):
        # The re-IP case: swap one address for another.
        sent = self._fix(
            ["set interfaces ethernet eth0 address 192.168.1.1/24"],
            [{"name": "eth0", "ipv4_addresses": ["10.10.0.1/24"]}],
        )
        self.assertIn(
            "delete interfaces ethernet eth0 address 192.168.1.1/24", sent)
        self.assertIn(
            "set interfaces ethernet eth0 address 10.10.0.1/24", sent)

    def test_add_additional_address_keeps_existing(self):
        sent = self._fix(
            ["set interfaces ethernet eth0 address 192.168.1.1/24"],
            [{"name": "eth0",
              "ipv4_addresses": ["192.168.1.1/24", "192.168.2.1/24"]}],
        )
        self.assertIn(
            "set interfaces ethernet eth0 address 192.168.2.1/24", sent)
        # The already-present address must not be re-deleted or re-added.
        self.assertNotIn(
            "delete interfaces ethernet eth0 address 192.168.1.1/24", sent)

    def test_noop_when_state_matches(self):
        sent = self._fix(
            ["set interfaces ethernet eth0 address 192.168.1.1/24"],
            [{"name": "eth0", "ipv4_addresses": ["192.168.1.1/24"]}],
        )
        self.assertEqual(sent, [])

    def test_interface_type_inference_for_switch(self):
        sent = self._fix(
            ["set interfaces switch switch0"],
            [{"name": "switch0", "ipv4_addresses": ["172.16.0.1/24"]}],
        )
        self.assertIn(
            "set interfaces switch switch0 address 172.16.0.1/24", sent)


class TestEdgeOSInterfaceProviderDirect(unittest.TestCase):
    longMessage = True

    def _sub_provider(self):
        dev = Mock()
        sent = []
        dev.send_command.side_effect = lambda cmd, *a, **k: sent.append(cmd)
        parent = EdgeOSInterfacesProvider(dev, {})
        return parent, sent

    def test_set_replaces_all_addresses(self):
        parent, sent = self._sub_provider()
        need = Need("eth0", InterfaceResources.IPV4_ADDRESSES, Op.SET,
                    parent_module="interfaces",
                    value=["10.0.0.1/24", "10.0.0.2/24"])
        parent.needed_actions.append(need)
        parent.sub_provider.fix_need(need)
        self.assertEqual(
            sent,
            [
                "delete interfaces ethernet eth0 address",
                "set interfaces ethernet eth0 address 10.0.0.1/24",
                "set interfaces ethernet eth0 address 10.0.0.2/24",
            ],
        )


if __name__ == "__main__":
    unittest.main()
