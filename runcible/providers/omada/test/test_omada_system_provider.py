import unittest
from unittest.mock import Mock, call

import pytest

from runcible.providers.omada.system import OmadaSystemProvider
from runcible.modules.system import SystemResources
from runcible.core.errors import RuncibleValidationError
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.test_utilities import append_operation_test_cases


# Recorded, sanitized five-field inventory projection from controller 6.1.0.19.
RECORDED_AP = {
    'mac': '02-00-00-00-00-01',
    'name': 'fixture-ap-01',
    'type': 'ap',
    'model': 'EAP670',
    'status': 14,
}
ROUTES = [('ap', 'eaps'), ('switch', 'switches'), ('gateway', 'gateways')]


def make_device(site='Default', mac=RECORDED_AP['mac']):
    device = Mock()
    device.retrieve.return_value = site
    device.meta_device = {'mac': mac}
    # Inventory is sufficient for the generated direct-SET completion test.
    device.send_command.return_value = {'data': [dict(RECORDED_AP)]}
    return device


class TestNeedCompletion(unittest.TestCase):
    longMessage = True


append_operation_test_cases(
    OmadaSystemProvider(make_device(), {}), {'hostname': 'test'}, TestNeedCompletion)


@pytest.mark.parametrize('device_type,collection', ROUTES)
@pytest.mark.parametrize('wrapped', [False, True])
def test_read_and_rename_use_type_route_and_cache(device_type, collection, wrapped):
    device = make_device(site='Branch-Office')
    # Switch/gateway inventory and all detail/write responses are simulated.
    inventory = [
        {'mac': '02-00-00-00-00-02', 'type': 'unknown'},
        dict(RECORDED_AP, type=device_type),
    ]
    device.send_command.side_effect = [
        {'data': inventory} if wrapped else inventory,
        {'name': RECORDED_AP['name']},
        {},
    ]
    provider = OmadaSystemProvider(device, {'hostname': 'new-device'})
    provider.load_module_cstate()
    assert provider.cstate.hostname == RECORDED_AP['name']
    provider.determine_needs()
    assert len(provider.needed_actions) == 1
    need = provider.needed_actions[0]
    assert need.attribute == SystemResources.HOSTNAME
    assert need.operation == Op.SET
    assert need.value == 'new-device'
    provider.fix_needs()
    path = f'/sites/Branch-Office/{collection}/{RECORDED_AP["mac"]}'
    assert device.send_command.call_args_list == [
        call({'method': 'GET', 'path': '/sites/Branch-Office/devices'}),
        call({'method': 'GET', 'path': path}),
        call({'method': 'PATCH', 'path': path, 'data': {'name': 'new-device'}}),
    ]
    assert provider.needed_actions == []


@pytest.mark.parametrize('device_type,collection', ROUTES)
def test_matching_hostname_is_no_op(device_type, collection):
    device = make_device()
    # Only the AP inventory projection is recorded; detail responses are simulated.
    device.send_command.side_effect = [
        {'data': [dict(RECORDED_AP, type=device_type)]},
        {'name': RECORDED_AP['name']},
    ]
    provider = OmadaSystemProvider(device, {'hostname': RECORDED_AP['name']})
    provider.load_module_cstate()
    provider.determine_needs()
    provider.fix_needs()
    assert provider.needed_actions == []
    assert device.send_command.call_args_list == [
        call({'method': 'GET', 'path': '/sites/Default/devices'}),
        call({'method': 'GET', 'path': f'/sites/Default/{collection}/{RECORDED_AP["mac"]}'}),
    ]


@pytest.mark.parametrize('device_type,collection', ROUTES)
def test_direct_set_discovers_route(device_type, collection):
    device = make_device()
    device.send_command.return_value = [dict(RECORDED_AP, type=device_type)]
    provider = OmadaSystemProvider(device, {'hostname': 'new-device'})
    provider.needed_actions = [
        Need('system', SystemResources.HOSTNAME, Op.SET, value='new-device')
    ]
    provider.fix_needs()
    assert device.send_command.call_args_list == [
        call({'method': 'GET', 'path': '/sites/Default/devices'}),
        call({'method': 'PATCH',
              'path': f'/sites/Default/{collection}/{RECORDED_AP["mac"]}',
              'data': {'name': 'new-device'}}),
    ]
    assert provider.needed_actions == []


@pytest.mark.parametrize('mac', ['aa-bb-cc-dd-ee-ff', 'aa:bb:cc:dd:ee:ff', 'AA-BB-CC-DD-EE-FF'])
def test_mac_matching_preserves_inventory_address(mac):
    device = make_device(mac=mac)
    device.send_command.side_effect = [
        [{'mac': 'AA-BB-CC-DD-EE-FF', 'type': 'ap'}],
        {'name': 'simulated-ap'},
    ]
    provider = OmadaSystemProvider(device, {})
    assert provider.get_cstate().hostname == 'simulated-ap'
    device.send_command.assert_called_with({
        'method': 'GET', 'path': '/sites/Default/eaps/AA-BB-CC-DD-EE-FF'})


def test_missing_detail_name_does_not_invent_hostname():
    device = make_device()
    device.send_command.side_effect = [[dict(RECORDED_AP)], {'mac': RECORDED_AP['mac']}]
    provider = OmadaSystemProvider(device, {})
    assert getattr(provider.get_cstate(), 'hostname', None) is None


def test_absent_mac_key_fails_without_requests():
    device = make_device()
    device.meta_device = {}
    provider = OmadaSystemProvider(device, {})
    with pytest.raises(RuncibleValidationError, match='mac'):
        provider._set_hostname('new-device')
    device.send_command.assert_not_called()


@pytest.mark.parametrize('field', ['site', 'mac'])
@pytest.mark.parametrize('value', [None, '', '   '])
@pytest.mark.parametrize('operation', ['read', 'write'])
def test_missing_identity_fails_without_requests(field, value, operation):
    device = make_device(**{field: value})
    provider = OmadaSystemProvider(device, {})
    with pytest.raises(RuncibleValidationError, match='site|mac'):
        if operation == 'read':
            provider.get_cstate()
        else:
            provider._set_hostname('new-device')
    device.send_command.assert_not_called()


@pytest.mark.parametrize('inventory,message', [
    ([], 'not found'),
    ({'data': []}, 'not found'),
    ([{'mac': '02-00-00-00-00-02', 'type': 'ap'}], 'not found'),
    ([dict(RECORDED_AP, type='unknown')], 'Unsupported'),
    ([dict(RECORDED_AP, type=None)], 'Unsupported'),
    ([{'mac': RECORDED_AP['mac']}], 'Unsupported'),
    ({}, 'inventory'),
    ({'data': None}, 'inventory'),
    (None, 'inventory'),
])
@pytest.mark.parametrize('operation', ['read', 'write'])
def test_missing_or_unsupported_device_never_reads_or_writes_detail(inventory, message, operation):
    device = make_device()
    device.send_command.return_value = inventory
    provider = OmadaSystemProvider(device, {})
    need = Need('system', SystemResources.HOSTNAME, Op.SET, value='new-device')
    provider.needed_actions = [need]
    with pytest.raises(RuncibleValidationError, match=message):
        if operation == 'read':
            provider.get_cstate()
        else:
            provider.fix_needs()
    device.send_command.assert_called_once_with({
        'method': 'GET', 'path': '/sites/Default/devices'})
    assert provider.needed_actions == [need]
    assert provider.completed_actions == []


@pytest.mark.parametrize('changed_field', ['site', 'mac'])
def test_cached_route_is_not_reused_for_another_identity(changed_field):
    device = make_device()
    device.send_command.side_effect = [[dict(RECORDED_AP)], {'name': 'simulated-ap'}, []]
    provider = OmadaSystemProvider(device, {})
    provider.get_cstate()
    if changed_field == 'site':
        device.retrieve.return_value = 'Other-Site'
    else:
        device.meta_device['mac'] = '02-00-00-00-00-02'
    with pytest.raises(RuncibleValidationError, match='not found'):
        provider._set_hostname('new-device')
    device.send_command.assert_called_with({
        'method': 'GET', 'path': f'/sites/{device.retrieve.return_value}/devices'})
    assert all(c.args[0]['method'] == 'GET' for c in device.send_command.call_args_list)
