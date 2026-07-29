import unittest
from unittest.mock import Mock
from runcible.providers.edgeos.system import EdgeOSSystemProvider
from runcible.modules.system import System, SystemResources
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.test_utilities import append_operation_test_cases

system_dict = {
    "hostname": "test"
}

device = Mock()
prov = EdgeOSSystemProvider(device, {})


class TestNeedCompletion(unittest.TestCase):
    longMessage = True


append_operation_test_cases(prov, system_dict, TestNeedCompletion)


class TestEdgeOSSystemGetCState(unittest.TestCase):

    def test_parses_hostname_from_show_configuration_commands(self):
        device = Mock()
        device.retrieve.return_value = [
            "set system name-server '8.8.8.8'",
            "set system host-name 'edge-router-01'",
            "set system time-zone 'UTC'",
        ]
        provider = EdgeOSSystemProvider(device, {})
        cstate = provider.get_cstate()
        self.assertEqual(cstate.hostname, 'edge-router-01')

    def test_parses_hostname_without_quotes(self):
        device = Mock()
        device.retrieve.return_value = [
            "set system host-name edge-router-02",
        ]
        provider = EdgeOSSystemProvider(device, {})
        cstate = provider.get_cstate()
        self.assertEqual(cstate.hostname, 'edge-router-02')

    def test_no_hostname_present(self):
        device = Mock()
        device.retrieve.return_value = [
            "set system time-zone 'UTC'",
        ]
        provider = EdgeOSSystemProvider(device, {})
        cstate = provider.get_cstate()
        self.assertIsNone(getattr(cstate, 'hostname', None))


class TestEdgeOSSystemFixNeeds(unittest.TestCase):

    def test_set_hostname_emits_set_command(self):
        device = Mock()
        provider = EdgeOSSystemProvider(device, {'hostname': 'new-router'})
        provider.needed_actions = [
            Need('system', SystemResources.HOSTNAME, Op.SET, value='new-router')
        ]
        provider.fix_needs()
        device.send_command.assert_called_once_with('set system host-name new-router')
        self.assertEqual(provider.needed_actions, [])

    def test_delete_hostname_emits_delete_command(self):
        device = Mock()
        provider = EdgeOSSystemProvider(device, {})
        provider.needed_actions = [
            Need('system', SystemResources.HOSTNAME, Op.DELETE)
        ]
        provider.fix_needs()
        device.send_command.assert_called_once_with('delete system host-name')
        self.assertEqual(provider.needed_actions, [])

    def test_determine_needs_no_op_when_converged(self):
        device = Mock()
        device.retrieve.return_value = [
            "set system host-name 'converged-router'",
        ]
        provider = EdgeOSSystemProvider(device, {'hostname': 'converged-router'})
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(provider.needed_actions, [])

    def test_determine_needs_emits_set_when_diverged(self):
        device = Mock()
        device.retrieve.return_value = [
            "set system host-name 'old-router'",
        ]
        provider = EdgeOSSystemProvider(device, {'hostname': 'new-router'})
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(len(provider.needed_actions), 1)
        need = provider.needed_actions[0]
        self.assertEqual(need.attribute, SystemResources.HOSTNAME)
        self.assertEqual(need.operation, Op.SET)
        self.assertEqual(need.value, 'new-router')
        provider.fix_needs()
        device.send_command.assert_called_once_with('set system host-name new-router')
        self.assertEqual(provider.needed_actions, [])
