"""Unit tests for the EdgeOS BGP provider.

These assert the generated EdgeOS ``set``/``delete protocols bgp <asn> ...``
command tree against known desired/current states, including the idempotent
no-op case, plus round-trip parsing of ``show configuration commands`` output.
"""
import unittest
from unittest.mock import Mock

from runcible.modules.bgp import BGP, BGPResources, BGPNeighborResources
from runcible.providers.edgeos.bgp import EdgeOSBGPProvider
from runcible.providers.edgeos import utils


ASN = 65000

DESIRED = {
    BGPResources.LOCAL_ASN: ASN,
    BGPResources.ROUTER_ID: '10.0.0.1',
    BGPResources.NETWORKS: ['10.1.0.0/16', '192.168.1.0/24'],
    BGPResources.NEIGHBORS: [
        {
            BGPNeighborResources.REMOTE_ASN: 65001,
            BGPNeighborResources.PEER_IP: '10.0.0.2',
            BGPNeighborResources.DESCRIPTION: 'k3s node',
            BGPNeighborResources.ADDRESS_FAMILIES: {'ipv4_unicast': True},
        },
        {
            BGPNeighborResources.REMOTE_ASN: 65002,
            BGPNeighborResources.PEER_IP: '10.0.0.3',
        },
    ],
}

# The exact ``show configuration commands`` lines that a device already fully
# configured to DESIRED would report.
DESIRED_AS_COMMANDS = [
    f"set protocols bgp {ASN} parameters router-id 10.0.0.1",
    f"set protocols bgp {ASN} network 10.1.0.0/16",
    f"set protocols bgp {ASN} network 192.168.1.0/24",
    f"set protocols bgp {ASN} neighbor 10.0.0.2 remote-as 65001",
    f"set protocols bgp {ASN} neighbor 10.0.0.2 description \"k3s node\"",
    f"set protocols bgp {ASN} neighbor 10.0.0.2 address-family ipv4-unicast",
    f"set protocols bgp {ASN} neighbor 10.0.0.3 remote-as 65002",
]


def make_provider(current_commands, dstate=DESIRED):
    """Build a provider whose device returns ``current_commands`` as the stored
    parsed configuration, and load its cstate from them."""
    device = Mock()
    device.retrieve.return_value = list(current_commands)
    sent = []
    device.send_command.side_effect = lambda cmd: sent.append(cmd)
    provider = EdgeOSBGPProvider(device, dstate)
    provider.load_module_cstate()
    provider.sent = sent
    return provider


def run_plan(current_commands, dstate=DESIRED):
    """Diff dstate against current state and apply, returning sent commands."""
    provider = make_provider(current_commands, dstate)
    provider.determine_needs()
    provider.fix_needs()
    return provider


class TestParseBGPCommands(unittest.TestCase):
    def test_round_trip_parse(self):
        state = utils.parse_bgp_commands(DESIRED_AS_COMMANDS)
        # Constructing a BGP module from the parsed state must equal one built
        # from the original desired dict.
        self.assertEqual(BGP(state), BGP(DESIRED))

    def test_no_bgp_config_returns_empty(self):
        self.assertEqual(utils.parse_bgp_commands([
            "set system host-name router",
            "set interfaces ethernet eth0 address 10.0.0.1/24",
        ]), {})

    def test_ignores_non_bgp_lines(self):
        state = utils.parse_bgp_commands([
            "set system host-name router",
            f"set protocols bgp {ASN} parameters router-id 10.0.0.1",
        ])
        self.assertEqual(state[BGPResources.LOCAL_ASN], ASN)
        self.assertEqual(state[BGPResources.ROUTER_ID], '10.0.0.1')


class TestFromScratch(unittest.TestCase):
    def test_full_config_emitted_when_nothing_present(self):
        provider = run_plan([])
        # Attribute ordering of the emitted tree is not significant; the full
        # set of commands must match.
        self.assertCountEqual(provider.sent, DESIRED_AS_COMMANDS)
        self.assertEqual(provider.needed_actions, [])


class TestNoOp(unittest.TestCase):
    def test_no_commands_when_already_converged(self):
        provider = run_plan(DESIRED_AS_COMMANDS)
        self.assertEqual(provider.sent, [])
        self.assertEqual(provider.needed_actions, [])


class TestChange(unittest.TestCase):
    def test_router_id_change_reissues_set(self):
        current = [
            f"set protocols bgp {ASN} parameters router-id 10.9.9.9",
            f"set protocols bgp {ASN} network 10.1.0.0/16",
            f"set protocols bgp {ASN} network 192.168.1.0/24",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 remote-as 65001",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 description \"k3s node\"",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 address-family ipv4-unicast",
            f"set protocols bgp {ASN} neighbor 10.0.0.3 remote-as 65002",
        ]
        provider = run_plan(current)
        self.assertEqual(
            provider.sent,
            [f"set protocols bgp {ASN} parameters router-id 10.0.0.1"],
        )

    def test_neighbor_attribute_change_deletes_then_readds(self):
        # Current neighbor 10.0.0.2 has the wrong remote-as -> whole neighbor is
        # deleted and re-added with the desired attributes.
        current = [
            f"set protocols bgp {ASN} parameters router-id 10.0.0.1",
            f"set protocols bgp {ASN} network 10.1.0.0/16",
            f"set protocols bgp {ASN} network 192.168.1.0/24",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 remote-as 65999",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 description \"k3s node\"",
            f"set protocols bgp {ASN} neighbor 10.0.0.2 address-family ipv4-unicast",
            f"set protocols bgp {ASN} neighbor 10.0.0.3 remote-as 65002",
        ]
        provider = run_plan(current)
        self.assertIn(f"delete protocols bgp {ASN} neighbor 10.0.0.2", provider.sent)
        self.assertIn(f"set protocols bgp {ASN} neighbor 10.0.0.2 remote-as 65001", provider.sent)
        self.assertIn(
            f"set protocols bgp {ASN} neighbor 10.0.0.2 address-family ipv4-unicast",
            provider.sent,
        )


class TestRemove(unittest.TestCase):
    def test_removed_network_and_neighbor_are_deleted(self):
        # Current has an extra network and an extra neighbor not in desired.
        current = DESIRED_AS_COMMANDS + [
            f"set protocols bgp {ASN} network 172.16.0.0/12",
            f"set protocols bgp {ASN} neighbor 10.0.0.9 remote-as 65099",
        ]
        provider = run_plan(current)
        self.assertIn(f"delete protocols bgp {ASN} network 172.16.0.0/12", provider.sent)
        self.assertIn(f"delete protocols bgp {ASN} neighbor 10.0.0.9", provider.sent)
        # Nothing that belongs in the desired state is touched.
        self.assertNotIn(f"delete protocols bgp {ASN} neighbor 10.0.0.2", provider.sent)

    def test_router_id_removed_when_absent_from_desired(self):
        dstate = {
            BGPResources.LOCAL_ASN: ASN,
            BGPResources.ROUTER_ID: False,
        }
        provider = run_plan([f"set protocols bgp {ASN} parameters router-id 10.0.0.1"], dstate)
        self.assertEqual(provider.sent, [f"delete protocols bgp {ASN} parameters router-id"])


if __name__ == '__main__':
    unittest.main()
