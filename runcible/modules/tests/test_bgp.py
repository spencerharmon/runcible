from unittest import TestCase

from runcible.modules.bgp import BGP, BGPResources, BGPNeighborResources
from runcible.core.errors import RuncibleValidationError


VALID_DSTATE = {
    BGPResources.LOCAL_ASN: 65000,
    BGPResources.ROUTER_ID: '10.0.0.1',
    BGPResources.NETWORKS: ['10.1.0.0/16', '192.168.1.0/24'],
    BGPResources.NEIGHBORS: [
        {
            BGPNeighborResources.REMOTE_ASN: 65001,
            BGPNeighborResources.PEER_IP: '10.0.0.2',
            BGPNeighborResources.DESCRIPTION: 'upstream peer',
            BGPNeighborResources.ADDRESS_FAMILIES: {
                'ipv4_unicast': True,
                'ipv6_unicast': False,
            }
        },
        {
            BGPNeighborResources.REMOTE_ASN: 65002,
            BGPNeighborResources.PEER_IP: '10.0.0.3',
        }
    ]
}


class TestBGPModuleValidation(TestCase):

    def test_valid_dstate_parses(self):
        bgp = BGP(VALID_DSTATE)
        self.assertEqual(bgp.local_asn, 65000)
        self.assertEqual(bgp.router_id, '10.0.0.1')
        self.assertEqual(len(bgp.neighbors), 2)
        self.assertEqual(bgp.neighbors[0][BGPNeighborResources.REMOTE_ASN], 65001)
        self.assertEqual(bgp.networks, ['10.1.0.0/16', '192.168.1.0/24'])

    def test_missing_required_local_asn(self):
        dstate = {k: v for k, v in VALID_DSTATE.items() if k != BGPResources.LOCAL_ASN}
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_local_asn_wrong_type(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.LOCAL_ASN] = 'not-an-int'
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_unknown_top_level_key_rejected(self):
        dstate = dict(VALID_DSTATE)
        dstate['not_a_real_attribute'] = True
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_missing_remote_asn(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{BGPNeighborResources.PEER_IP: '10.0.0.2'}]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_missing_peer_ip(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{BGPNeighborResources.REMOTE_ASN: 65001}]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_remote_asn_wrong_type(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{
            BGPNeighborResources.REMOTE_ASN: 'not-an-int',
            BGPNeighborResources.PEER_IP: '10.0.0.2',
        }]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_unknown_key_rejected(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{
            BGPNeighborResources.REMOTE_ASN: 65001,
            BGPNeighborResources.PEER_IP: '10.0.0.2',
            'bogus_key': 'nope',
        }]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_unknown_address_family_rejected(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{
            BGPNeighborResources.REMOTE_ASN: 65001,
            BGPNeighborResources.PEER_IP: '10.0.0.2',
            BGPNeighborResources.ADDRESS_FAMILIES: {'bogus_af': True},
        }]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_neighbor_address_family_wrong_type(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NEIGHBORS] = [{
            BGPNeighborResources.REMOTE_ASN: 65001,
            BGPNeighborResources.PEER_IP: '10.0.0.2',
            BGPNeighborResources.ADDRESS_FAMILIES: {'ipv4_unicast': 'yes'},
        }]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)

    def test_network_wrong_sub_type_rejected(self):
        dstate = dict(VALID_DSTATE)
        dstate[BGPResources.NETWORKS] = [123]
        with self.assertRaises(RuncibleValidationError):
            BGP(dstate)
