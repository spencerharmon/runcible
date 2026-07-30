import unittest
from unittest.mock import Mock
from runcible.providers.omada.system import OmadaSystemProvider
from runcible.modules.system import System, SystemResources
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.test_utilities import append_operation_test_cases

system_dict = {
    "hostname": "test"
}


def make_device(site="Default", mac="AA-BB-CC-DD-EE-FF"):
    device = Mock()
    device.retrieve.return_value = site
    device.meta_device = {"mac": mac}
    return device


device = make_device()
prov = OmadaSystemProvider(device, {})


class TestNeedCompletion(unittest.TestCase):
    longMessage = True


append_operation_test_cases(prov, system_dict, TestNeedCompletion)


class TestOmadaSystemGetCState(unittest.TestCase):

    def test_parses_hostname_from_device_info(self):
        device = make_device()
        device.send_command.return_value = {
            "name": "omada-switch-01",
            "mac": "AA-BB-CC-DD-EE-FF",
        }
        provider = OmadaSystemProvider(device, {})
        cstate = provider.get_cstate()
        self.assertEqual(cstate.hostname, 'omada-switch-01')
        device.send_command.assert_called_once_with({
            'method': 'GET',
            'path': '/sites/Default/devices/AA-BB-CC-DD-EE-FF',
        })

    def test_no_name_present(self):
        device = make_device()
        device.send_command.return_value = {"mac": "AA-BB-CC-DD-EE-FF"}
        provider = OmadaSystemProvider(device, {})
        cstate = provider.get_cstate()
        self.assertIsNone(getattr(cstate, 'hostname', None))

    def test_uses_selected_site_and_mac(self):
        device = make_device(site="Branch-Office", mac="11-22-33-44-55-66")
        device.send_command.return_value = {"name": "branch-ap-01"}
        provider = OmadaSystemProvider(device, {})
        provider.get_cstate()
        device.send_command.assert_called_once_with({
            'method': 'GET',
            'path': '/sites/Branch-Office/devices/11-22-33-44-55-66',
        })


class TestOmadaSystemFixNeeds(unittest.TestCase):

    def test_set_hostname_emits_patch_operation(self):
        device = make_device()
        provider = OmadaSystemProvider(device, {'hostname': 'new-device'})
        provider.needed_actions = [
            Need('system', SystemResources.HOSTNAME, Op.SET, value='new-device')
        ]
        provider.fix_needs()
        device.send_command.assert_called_once_with({
            'method': 'PATCH',
            'path': '/sites/Default/devices/AA-BB-CC-DD-EE-FF',
            'data': {'name': 'new-device'},
        })
        self.assertEqual(provider.needed_actions, [])

    def test_determine_needs_no_op_when_converged(self):
        device = make_device()
        device.send_command.return_value = {"name": "converged-device"}
        provider = OmadaSystemProvider(device, {'hostname': 'converged-device'})
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(provider.needed_actions, [])

    def test_determine_needs_emits_set_when_diverged(self):
        device = make_device()
        device.send_command.return_value = {"name": "old-device"}
        provider = OmadaSystemProvider(device, {'hostname': 'new-device'})
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(len(provider.needed_actions), 1)
        need = provider.needed_actions[0]
        self.assertEqual(need.attribute, SystemResources.HOSTNAME)
        self.assertEqual(need.operation, Op.SET)
        self.assertEqual(need.value, 'new-device')
        device.send_command.reset_mock()
        provider.fix_needs()
        device.send_command.assert_called_once_with({
            'method': 'PATCH',
            'path': '/sites/Default/devices/AA-BB-CC-DD-EE-FF',
            'data': {'name': 'new-device'},
        })
        self.assertEqual(provider.needed_actions, [])


if __name__ == "__main__":
    unittest.main()
