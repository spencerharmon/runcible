import unittest
from unittest import mock

from runcible.core.device import Device
from runcible.core.need import Need, NeedOperation as Op
from runcible.modules.vyatta_config import VyattaConfig, tokenize, render
from runcible.modules.user import UserResources
from runcible.protocols.vyatta_shell import VyattaSerialProtocol, VyattaSSHProtocol
from runcible.protocols.test.fake_vyatta import FakeVyatta
from runcible.providers.edgeos.config import EdgeOSConfigProvider
from runcible.providers.edgeos.users import EdgeOSUsersProvider
from runcible.providers.edgeos.system import EdgeOSSystemProvider

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterialOnly admin@example.com"

FACTORY = [
    "set interfaces ethernet eth0 address 192.0.2.1/24",
    "set interfaces ethernet eth1 duplex auto",
    "set service gui https-port 443",
    "set service ssh port 22",
    "set system host-name ubnt",
    "set system login user ubnt authentication encrypted-password '$6$examplesalt$examplehashexamplehashexample'",
    "set system login user ubnt level admin",
    "set system ntp server 0.ubnt.pool.ntp.org",
]


def device_doc(protocol='serial'):
    return {
        'meta': {'device': {
            'driver': 'edgeos',
            'default_management_protocol': protocol,
            'serial': {'device': '/dev/ttyUSB0', 'username': 'ubnt', 'password': 'ubnt', 'quiet': 0.05,
                       'timeout': 5},
            'ssh': {'hostname': '192.0.2.1', 'username': 'admin'},
        }},
        'system': {'hostname': 'router.example.com', 'timezone': 'UTC', 'dns': ['192.0.2.53']},
        'users': [{'name': 'admin', 'level': 'admin', 'full_name': 'Net Admin', 'ssh_keys': [KEY]}],
        'interfaces': [
            {'name': 'eth0', 'ipv4_addresses': []},
            {'name': 'eth1', 'ipv4_addresses': ['198.51.100.1/24']},
        ],
        'vyatta_config': {
            'statements': [
                "interfaces ethernet eth0 address dhcp",
                "service nat rule 5010 outbound-interface eth0",
                "service nat rule 5010 type masquerade",
                "set firewall name WAN_IN description 'WAN to internal'",
                "firewall name WAN_IN default-action drop",
                "service ssh listen-address 198.51.100.1",
            ],
            'managed_paths': ["service nat", "firewall name WAN_IN", "service ssh listen-address"],
        },
    }


class TestVyattaConfigModule(unittest.TestCase):

    def test_tokenize_is_quote_insensitive(self):
        self.assertEqual(tokenize("set firewall name X description 'a b'"),
                         tokenize('firewall name X description "a b"'))
        self.assertEqual(render(tokenize("system login user u authentication encrypted-password '$6$x$y'")),
                         "system login user u authentication encrypted-password '$6$x$y'")

    def test_needs_add_missing_and_delete_unmanaged_extras(self):
        desired = VyattaConfig({'statements': ['service nat rule 1 type masquerade', 'service ssh port 22'],
                                'managed_paths': ['service nat']})
        current = VyattaConfig({'statements': ['set service nat rule 9 type masquerade',
                                               'set service ssh port 22',
                                               'set service gui https-port 443']})
        needs = desired.determine_needs(current)
        self.assertEqual(needs, [
            Need(None, 'statements', Op.DELETE, value='service nat rule 9'),
            Need(None, 'statements', Op.ADD, value='service nat rule 1 type masquerade'),
        ])

    def test_removing_a_whole_tag_node_deletes_the_node(self):
        # Regression (real EdgeOS): deleting both leaves of a static-mapping left
        # an empty `static-mapping NAME` node and the commit was refused.
        base = 'service dhcp-server shared-network-name LAN subnet 192.0.2.0/24'
        desired = VyattaConfig({'statements': [f'{base} default-router 192.0.2.1'],
                                'managed_paths': ['service dhcp-server shared-network-name']})
        current = VyattaConfig({'statements': [f'set {base} default-router 192.0.2.1',
                                               f'set {base} static-mapping h1 ip-address 192.0.2.10',
                                               f'set {base} static-mapping h1 mac-address 00:00:5e:00:53:01',
                                               f'set {base} static-mapping h2 ip-address 192.0.2.11']})
        needs = desired.determine_needs(current)
        # every mapping is going: the whole subtree is removed in one statement
        self.assertEqual([n.value for n in needs], [f'{base} static-mapping'])

    def test_removing_one_of_several_tag_nodes(self):
        base = 'service dhcp-server shared-network-name LAN subnet 192.0.2.0/24'
        desired = VyattaConfig({'statements': [f'{base} static-mapping h2 ip-address 192.0.2.11'],
                                'managed_paths': ['service dhcp-server shared-network-name']})
        current = VyattaConfig({'statements': [f'set {base} static-mapping h1 ip-address 192.0.2.10',
                                               f'set {base} static-mapping h1 mac-address 00:00:5e:00:53:01',
                                               f'set {base} static-mapping h2 ip-address 192.0.2.11']})
        self.assertEqual([n.value for n in desired.determine_needs(current)], [f'{base} static-mapping h1'])

    def test_emptied_managed_path_is_deleted_whole(self):
        # Regression (real EdgeOS): deleting every leaf of `service dns forwarding`
        # left the service node with no listen-on and the commit was refused.
        desired = VyattaConfig({'statements': ['service ssh port 22'],
                                'managed_paths': ['service dns forwarding', 'service ssh']})
        current = VyattaConfig({'statements': ['set service dns forwarding cache-size 0',
                                               'set service dns forwarding listen-on eth1',
                                               'set service dns forwarding name-server 192.0.2.53',
                                               'set service ssh port 22']})
        self.assertEqual([n.value for n in desired.determine_needs(current)], ['service dns forwarding'])

    def test_partial_subtree_removal_stays_leaf_level(self):
        base = 'service nat rule 10'
        desired = VyattaConfig({'statements': [f'{base} type masquerade'], 'managed_paths': ['service nat']})
        current = VyattaConfig({'statements': [f'set {base} type masquerade', f'set {base} protocol all']})
        self.assertEqual([n.value for n in desired.determine_needs(current)], [f'{base} protocol'])

    def test_prefix_statement_satisfied_by_deeper_config(self):
        desired = VyattaConfig({'statements': ['interfaces ethernet eth2']})
        current = VyattaConfig({'statements': ['set interfaces ethernet eth2 disable']})
        self.assertEqual(desired.determine_needs(current), [])


class TestEdgeOSUsersProvider(unittest.TestCase):

    def test_cstate_parses_users(self):
        device = mock.Mock()
        device.retrieve.return_value = [
            "set system login user admin authentication encrypted-password '$6$abc$def'",
            "set system login user admin authentication public-keys admin@example.com key AAAAKEY",
            "set system login user admin authentication public-keys admin@example.com type ssh-ed25519",
            "set system login user admin full-name 'Net Admin'",
            "set system login user admin level admin",
        ]
        users = EdgeOSUsersProvider(device, []).get_cstate().users
        self.assertEqual(len(users), 1)
        user = users[0]
        self.assertEqual(user.name, 'admin')
        self.assertEqual(user.full_name, 'Net Admin')
        self.assertEqual(user.level, 'admin')
        self.assertEqual(user.encrypted_password, '$6$abc$def')
        self.assertEqual(user.ssh_keys, ['ssh-ed25519 AAAAKEY admin@example.com'])

    def test_add_key_emits_type_and_key(self):
        device = mock.Mock()
        provider = EdgeOSUsersProvider(device, [])
        provider.needed_actions = [Need('admin', UserResources.SSH_KEYS, Op.ADD, value=KEY, parent_module='users')]
        provider.fix_needs()
        calls = [c.args[0] for c in device.send_command.call_args_list]
        self.assertEqual(calls, [
            "set system login user admin authentication public-keys admin@example.com type ssh-ed25519",
            "set system login user admin authentication public-keys admin@example.com key "
            "AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterialOnly",
        ])
        self.assertEqual(provider.needed_actions, [])


class TestEdgeOSSystemProviderExtras(unittest.TestCase):

    def test_fqdn_roundtrip(self):
        device = mock.Mock()
        device.retrieve.return_value = ["set system host-name router", "set system domain-name example.com",
                                        "set system time-zone UTC", "set system name-server 192.0.2.53"]
        provider = EdgeOSSystemProvider(device, {'hostname': 'router.example.com', 'timezone': 'UTC',
                                                 'dns': ['192.0.2.53']})
        provider.load_module_cstate()
        provider.determine_needs()
        self.assertEqual(provider.needed_actions, [])

    def test_fqdn_set_splits_domain(self):
        device = mock.Mock()
        provider = EdgeOSSystemProvider(device, {})
        provider.needed_actions = [Need(None, 'hostname', Op.SET, value='router.example.com')]
        provider.fix_needs()
        self.assertEqual([c.args[0] for c in device.send_command.call_args_list],
                         ["set system host-name router", "set system domain-name example.com"])


class TestEdgeOSEndToEnd(unittest.TestCase):
    """plan -> execute -> plan over a simulated console converges with no further needs."""

    def _device(self, fake, protocol='serial'):
        doc = device_doc(protocol)
        with mock.patch.object(VyattaSerialProtocol, 'open_transport', lambda self: fake), \
                mock.patch.object(VyattaSerialProtocol, 'close_transport', lambda self: None):
            device = Device('router', doc)
            device.plan()
            self.assertTrue(device.needs_changes)
            device.execute()
            device.needs_changes = False
            device.plan()
            remaining = {p.provides_for.module_name: p.needed_actions for p in device.providers
                         if p.needed_actions}
            device.disconnect()
        return remaining

    def test_serial_provisioning_converges(self):
        fake = FakeVyatta(username='ubnt', password='ubnt', hostname='ubnt', config=FACTORY)
        remaining = self._device(fake)
        self.assertEqual(remaining, {})
        cfg = fake.committed
        self.assertIn("set system host-name router", cfg)
        self.assertIn("set system domain-name example.com", cfg)
        self.assertIn("set system login user admin level admin", cfg)
        self.assertIn("set interfaces ethernet eth1 address 198.51.100.1/24", cfg)
        self.assertIn("set interfaces ethernet eth0 address dhcp", cfg)
        self.assertNotIn("set interfaces ethernet eth0 address 192.0.2.1/24", cfg)
        self.assertIn("set firewall name WAN_IN description 'WAN to internal'", cfg)
        # unmanaged factory config is untouched
        self.assertIn("set system login user ubnt level admin", cfg)
        self.assertIn("set service gui https-port 443", cfg)
        # the console is logged back out
        self.assertEqual(fake.state, 'login')

    def test_same_document_selects_ssh(self):
        device = Device('router', device_doc('ssh'))
        self.assertIsInstance(device.protocol, VyattaSSHProtocol)
        device = Device('router', device_doc('ssh'), protocol='serial')
        self.assertIsInstance(device.protocol, VyattaSerialProtocol)


if __name__ == '__main__':
    unittest.main()
