"""Unit tests for the Omada WLAN/SSID provider.

These MOCK the Northbound API (``device.send_command``) and assert the exact
ordered list of API operations the provider generates for known desired/current
states, including the no-op case, plus current-state parsing and the driver
wiring.
"""
import unittest
from unittest.mock import Mock

from runcible.providers.omada.wlan import OmadaWLANProvider
from runcible.drivers.omada import OmadaDriver


SITE = 'site-abc'
GROUP = 'wlangroup-1'
BASE = f"/sites/{SITE}/setting/wlans/{GROUP}/ssids"


def make_device(current_ssids=None, passphrases=None):
    """A Mock device whose GET on the SSID collection returns current_ssids."""
    device = Mock()
    device.retrieve.return_value = SITE
    device.meta_device = {'wlan_group': GROUP}
    if passphrases is not None:
        device.meta_device['wifi_passphrases'] = passphrases
    current = current_ssids if current_ssids is not None else []

    def send_command(command):
        if command.get('method', 'GET') == 'GET':
            return {'data': list(current)}
        return {}

    device.send_command.side_effect = send_command
    return device


def desired(ssids):
    return {'ssids': ssids}


class TestGetCState(unittest.TestCase):
    def test_parses_current_ssids_into_neutral_state(self):
        device = make_device(current_ssids=[
            {'id': 'id1', 'name': 'corp', 'enable': True, 'broadcast': True,
             'vlanEnable': True, 'vlanId': 20, 'security': 'wpa-personal', 'wpaMode': 'wpa2'},
            {'id': 'id2', 'name': 'guest', 'enable': False, 'broadcast': False,
             'vlanEnable': False, 'security': 'open'},
        ])
        provider = OmadaWLANProvider(device, {})
        cstate = provider.get_cstate()
        names = sorted(s['name'] for s in cstate.ssids)
        self.assertEqual(names, ['corp', 'guest'])
        corp = next(s for s in cstate.ssids if s['name'] == 'corp')
        self.assertEqual(corp['vlan_id'], 20)
        self.assertEqual(corp['security']['auth_mode'], 'wpa2_psk')
        guest = next(s for s in cstate.ssids if s['name'] == 'guest')
        self.assertFalse(guest['enabled'])
        self.assertNotIn('vlan_id', guest)
        self.assertEqual(guest['security']['auth_mode'], 'open')
        self.assertEqual(provider._current_ids, {'corp': 'id1', 'guest': 'id2'})

    def test_empty_controller_yields_no_ssids(self):
        device = make_device(current_ssids=[])
        provider = OmadaWLANProvider(device, {})
        cstate = provider.get_cstate()
        self.assertEqual(getattr(cstate, 'ssids', None) or [], [])


class TestGenerateOperations(unittest.TestCase):
    def test_no_op_when_already_converged(self):
        current = [
            {'id': 'id1', 'name': 'corp', 'enable': True, 'broadcast': True,
             'vlanEnable': True, 'vlanId': 20, 'security': 'wpa-personal', 'wpaMode': 'wpa2'},
        ]
        device = make_device(current_ssids=current, passphrases={'ref': 'secret'})
        provider = OmadaWLANProvider(device, desired([
            {'name': 'corp', 'enabled': True, 'broadcast': True, 'vlan_id': 20,
             'security': {'auth_mode': 'wpa2_psk', 'passphrase_ref': 'ref'}},
        ]))
        provider.load_module_cstate()
        self.assertEqual(provider.generate_operations(), [])
        provider.determine_needs()
        self.assertEqual(provider.needed_actions, [])

    def test_create_new_ssid(self):
        device = make_device(current_ssids=[], passphrases={'ref': 'secret'})
        provider = OmadaWLANProvider(device, desired([
            {'name': 'corp', 'enabled': True, 'broadcast': True, 'vlan_id': 20,
             'security': {'auth_mode': 'wpa2_psk', 'passphrase_ref': 'ref'}},
        ]))
        provider.load_module_cstate()
        ops = provider.generate_operations()
        self.assertEqual(ops, [{
            'method': 'POST',
            'path': BASE,
            'data': {
                'name': 'corp', 'enable': True, 'broadcast': True,
                'vlanEnable': True, 'vlanId': 20,
                'security': 'wpa-personal', 'wpaMode': 'wpa2', 'encryption': 'aes',
                'pskString': 'secret',
            },
        }])

    def test_update_changed_ssid_vlan_binding(self):
        current = [
            {'id': 'id1', 'name': 'corp', 'enable': True, 'broadcast': True,
             'vlanEnable': True, 'vlanId': 20, 'security': 'wpa-personal', 'wpaMode': 'wpa2'},
        ]
        device = make_device(current_ssids=current, passphrases={'ref': 'secret'})
        provider = OmadaWLANProvider(device, desired([
            {'name': 'corp', 'enabled': True, 'broadcast': True, 'vlan_id': 30,
             'security': {'auth_mode': 'wpa2_psk', 'passphrase_ref': 'ref'}},
        ]))
        provider.load_module_cstate()
        ops = provider.generate_operations()
        self.assertEqual(ops, [{
            'method': 'PATCH',
            'path': f"{BASE}/id1",
            'data': {
                'name': 'corp', 'enable': True, 'broadcast': True,
                'vlanEnable': True, 'vlanId': 30,
                'security': 'wpa-personal', 'wpaMode': 'wpa2', 'encryption': 'aes',
                'pskString': 'secret',
            },
        }])

    def test_delete_removed_ssid(self):
        current = [
            {'id': 'id2', 'name': 'guest', 'enable': True, 'broadcast': True,
             'vlanEnable': False, 'security': 'open'},
        ]
        device = make_device(current_ssids=current)
        provider = OmadaWLANProvider(device, desired([]))
        provider.load_module_cstate()
        ops = provider.generate_operations()
        self.assertEqual(ops, [{'method': 'DELETE', 'path': f"{BASE}/id2"}])

    def test_ordered_create_update_delete(self):
        current = [
            {'id': 'idc', 'name': 'corp', 'enable': True, 'broadcast': True,
             'vlanEnable': True, 'vlanId': 20, 'security': 'open'},
            {'id': 'idg', 'name': 'guest', 'enable': True, 'broadcast': True,
             'vlanEnable': False, 'security': 'open'},
        ]
        device = make_device(current_ssids=current)
        provider = OmadaWLANProvider(device, desired([
            # unchanged corp -> no op; changed guest -> update; new iot -> create
            {'name': 'corp', 'enabled': True, 'broadcast': True, 'vlan_id': 20,
             'security': {'auth_mode': 'open'}},
            {'name': 'guest', 'enabled': False, 'broadcast': True,
             'security': {'auth_mode': 'open'}},
            {'name': 'iot', 'enabled': True, 'broadcast': False, 'vlan_id': 40,
             'security': {'auth_mode': 'open'}},
        ]))
        # also delete an SSID present on controller only:
        current.append({'id': 'idold', 'name': 'legacy', 'enable': True,
                        'broadcast': True, 'vlanEnable': False, 'security': 'open'})
        provider.load_module_cstate()
        ops = provider.generate_operations()
        methods = [(o['method'], o['path']) for o in ops]
        self.assertEqual(methods, [
            ('POST', BASE),
            ('PATCH', f"{BASE}/idg"),
            ('DELETE', f"{BASE}/idold"),
        ])


class TestFixNeeds(unittest.TestCase):
    def test_fix_needs_sends_each_operation_and_completes(self):
        device = make_device(current_ssids=[], passphrases={'ref': 'secret'})
        provider = OmadaWLANProvider(device, desired([
            {'name': 'corp', 'security': {'auth_mode': 'wpa2_psk', 'passphrase_ref': 'ref'}},
        ]))
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(len(provider.needed_actions), 1)
        provider.fix_needs()
        # one GET (cstate) + one POST (create) issued
        post_calls = [c.args[0] for c in device.send_command.call_args_list
                      if c.args[0].get('method') == 'POST']
        self.assertEqual(len(post_calls), 1)
        self.assertEqual(post_calls[0]['path'], BASE)
        self.assertEqual(provider.needed_actions, [])
        self.assertEqual(len(provider.completed_actions), 1)


class TestDriverWiring(unittest.TestCase):
    def test_wlan_module_wired_into_provider_map(self):
        self.assertIs(OmadaDriver.module_provider_map.get('wlan'), OmadaWLANProvider)


if __name__ == '__main__':
    unittest.main()
