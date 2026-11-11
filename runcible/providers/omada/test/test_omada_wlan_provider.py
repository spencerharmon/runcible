"""Controller 6.1 fixture regression tests; mutations are synthetic cases."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from runcible.core.errors import RuncibleValidationError
from runcible.drivers.omada import OmadaDriver
from runcible.providers.omada.wlan import OmadaWLANProvider


BASE = '/sites/site-abc/setting/wlans/wlangroup-1/ssids'


@pytest.fixture
def recorded():
    return json.loads(Path(__file__).with_name('controller_6_1_ssid.json').read_text())


def make_provider(current, desired, secrets=None):
    device = Mock()
    device.retrieve.return_value = 'site-abc'
    device.meta_device = {'wlan_group': 'wlangroup-1', 'wifi_passphrases': secrets or {}}
    device.send_command.return_value = {'data': current}
    return OmadaWLANProvider(device, {'ssids': desired})


def desired(**changes):
    state = {'name': 'fixture-ssid', 'enabled': True, 'broadcast': True,
             'security': {'auth_mode': 'wpa2_wpa3_psk'}}
    state.update(changes)
    return state


def test_recorded_matching_state_is_no_op(recorded):
    provider = make_provider([recorded], [desired()])
    assert provider.generate_operations() == []
    provider.determine_needs()
    provider.fix_needs()
    assert provider.needed_actions == []
    provider.device.send_command.assert_called_once_with({'method': 'GET', 'path': BASE})


@pytest.mark.parametrize('version,band,auth', [
    (2, 3, 'wpa2_psk'), (4, 6, 'wpa2_wpa3_psk'), (4, 4, 'wpa3_psk'),
])
def test_psk_mode_round_trip(recorded, version, band, auth):
    recorded['pskSetting']['versionPsk'] = version
    recorded['band'] = band
    provider = make_provider([recorded], [desired(security={'auth_mode': auth})])
    assert provider.generate_operations() == []


def test_patch_preserves_all_unowned_fields_and_psk(recorded):
    recorded['pskSetting']['securityKey'] = 'synthetic-existing-test-key'
    original = deepcopy(recorded)
    provider = make_provider([recorded], [desired(broadcast=False)])
    ops = provider.generate_operations()
    expected = deepcopy(recorded)
    expected['broadcast'] = False
    assert ops == [{'method': 'PATCH', 'path': f"{BASE}/{recorded['id']}", 'data': expected}]
    assert recorded == original
    assert provider.generate_operations() == ops
    assert 'enable' not in ops[0]['data']


@pytest.mark.parametrize('custom', [
    {'customMode': 1, 'vlanId': 20},
    {'customMode': 1, 'vlanPoolIds': '20'},
    {'customMode': 0, 'lanNetworkId': 'lan-1', 'lanNetworkVlanIds': {'lan-1': [20]},
     'bridgeVlan': 20},
])
def test_vlan_read_no_op_and_preservation(recorded, custom):
    recorded['vlanEnable'] = True
    recorded['vlanSetting'] = {'mode': 1, 'customConfig': custom}
    provider = make_provider([recorded], [desired(vlan_id=20)])
    assert provider.generate_operations() == []
    provider = make_provider([recorded], [desired(vlan_id=20, broadcast=False)])
    assert provider.generate_operations()[0]['data']['vlanSetting'] == recorded['vlanSetting']


def test_vlan_update_and_removal_round_trip(recorded):
    provider = make_provider([recorded], [desired(vlan_id=30)])
    payload = provider.generate_operations()[0]['data']
    assert payload['vlanSetting'] == {
        'mode': 1, 'customConfig': {'customMode': 1, 'vlanId': 30}}
    assert payload['vlanEnable'] is True
    assert 'vlanId' not in payload
    assert make_provider([payload], [desired(vlan_id=30)]).generate_operations() == []
    cleared = make_provider([payload], [desired()]).generate_operations()[0]['data']
    assert cleared['vlanSetting'] == {'mode': 0, 'customConfig': {}}
    assert cleared['vlanEnable'] is False
    assert make_provider([cleared], [desired()]).generate_operations() == []


@pytest.mark.parametrize('ref,secrets', [
    ('${TEST_WIFI_KEY}', None), ('corp-key', {'corp-key': '${TEST_WIFI_KEY}'}),
])
def test_runtime_secret_resolution_on_create(monkeypatch, ref, secrets):
    monkeypatch.setenv('TEST_WIFI_KEY', 'synthetic-runtime-key')
    provider = make_provider([], [desired(security={
        'auth_mode': 'wpa2_psk', 'passphrase_ref': ref})], secrets)
    ops = provider.generate_operations()
    assert len(ops) == 1
    assert ops[0]['method'] == 'POST'
    assert ops[0]['path'] == BASE
    payload = ops[0]['data']
    assert payload['security'] == 3
    assert payload['pskSetting'] == {
        'versionPsk': 2, 'encryptionPsk': 3, 'securityKey': 'synthetic-runtime-key'}
    assert not {'enable', 'wpaMode', 'encryption', 'pskString', 'vlanId'} & payload.keys()
    payload['id'] = 'new-id'
    assert make_provider([payload], [desired(security={'auth_mode': 'wpa2_psk'})]).generate_operations() == []


def test_secret_update_merges_nested_settings(recorded, monkeypatch):
    monkeypatch.setenv('TEST_WIFI_KEY', 'synthetic-new-key')
    provider = make_provider([recorded], [desired(broadcast=False, security={
        'auth_mode': 'wpa2_wpa3_psk', 'passphrase_ref': '${TEST_WIFI_KEY}'})])
    payload = provider.generate_operations()[0]['data']
    assert payload['pskSetting'] == dict(recorded['pskSetting'], securityKey='synthetic-new-key')
    assert 'securityKey' not in recorded['pskSetting']


@pytest.mark.parametrize('ref,secrets', [
    ('${UNSET_WIFI_KEY}', None), ('missing', None),
    ('literal', {'literal': 'do-not-leak-this-value'}),
])
def test_invalid_secret_reference_fails_without_leaking(monkeypatch, ref, secrets):
    monkeypatch.delenv('UNSET_WIFI_KEY', raising=False)
    provider = make_provider([], [desired(security={
        'auth_mode': 'wpa2_psk', 'passphrase_ref': ref})], secrets)
    with pytest.raises(RuncibleValidationError) as error:
        provider.generate_operations()
    assert 'do-not-leak-this-value' not in str(error.value)
    assert all(c.args[0]['method'] == 'GET' for c in provider.device.send_command.call_args_list)


def test_no_op_does_not_require_secret_in_environment(recorded):
    provider = make_provider([recorded], [desired(security={
        'auth_mode': 'wpa2_wpa3_psk', 'passphrase_ref': '${UNSET_WIFI_KEY}'})])
    assert provider.generate_operations() == []


@pytest.mark.parametrize('changes', [
    {'security': 2}, {'security': 99},
    {'pskSetting': {'versionPsk': 99, 'encryptionPsk': 3}},
    {'vlanSetting': {'mode': 1, 'customConfig': {'customMode': 1, 'vlanPoolIds': '20,30'}}},
])
def test_unrepresentable_current_state_fails_closed(recorded, changes):
    recorded.update(changes)
    with pytest.raises(RuncibleValidationError):
        make_provider([recorded], [desired()]).generate_operations()


def test_disable_is_not_silently_encoded_as_enable_or_hidden(recorded):
    with pytest.raises(RuncibleValidationError):
        make_provider([recorded], [desired(enabled=False)]).generate_operations()


def test_returned_ssid_enable_field_round_trip(recorded):
    recorded['ssidEnable'] = False
    assert make_provider([recorded], [desired(enabled=False)]).generate_operations() == []
    payload = make_provider([recorded], [desired()]).generate_operations()[0]['data']
    assert payload['ssidEnable'] is True
    assert payload['broadcast'] is True
    assert 'enable' not in payload


def test_non_owned_cipher_is_preserved_on_update(recorded):
    recorded['pskSetting']['encryptionPsk'] = 1
    payload = make_provider([recorded], [desired(broadcast=False)]).generate_operations()[0]['data']
    assert payload['pskSetting'] == recorded['pskSetting']


def test_cannot_create_psk_without_secret():
    with pytest.raises(RuncibleValidationError):
        make_provider([], [desired()]).generate_operations()


def test_cannot_encode_wpa3_only_on_non_6ghz_band(recorded):
    with pytest.raises(RuncibleValidationError):
        make_provider([recorded], [desired(security={'auth_mode': 'wpa3_psk'})]).generate_operations()


def test_create_update_delete_order_and_fix_needs(recorded):
    old = dict(recorded, id='old-id', name='old')
    states = [desired(broadcast=False), {'name': 'new', 'security': {'auth_mode': 'open'}}]
    provider = make_provider([recorded, old], states)
    provider.determine_needs()
    assert len(provider.needed_actions) == 1
    assert [op['method'] for op in provider.generate_operations()] == ['POST', 'PATCH', 'DELETE']
    provider.fix_needs()
    assert provider.needed_actions == []
    assert len(provider.completed_actions) == 1
    writes = [c.args[0] for c in provider.device.send_command.call_args_list[1:]]
    assert writes[-1] == {'method': 'DELETE', 'path': f'{BASE}/old-id'}
    assert writes[0]['data']['security'] == 0


def test_empty_controller_and_driver_wiring():
    assert make_provider([], []).generate_operations() == []
    assert OmadaDriver.module_provider_map['wlan'] is OmadaWLANProvider
