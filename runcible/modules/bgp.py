from runcible.modules.module import Module
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.errors import RuncibleValidationError


class BGPResources(object):
    LOCAL_ASN = 'local_asn'
    ROUTER_ID = 'router_id'
    NEIGHBORS = 'neighbors'
    NETWORKS = 'networks'


class BGPNeighborResources(object):
    """
    Vendor-neutral keys accepted inside each entry of BGP.neighbors. These are intentionally shaped so
    any provider (EdgeOS, Cumulus, FRR, ...) can map them to its own CLI/config syntax.
    """
    REMOTE_ASN = 'remote_asn'
    PEER_IP = 'peer_ip'
    DESCRIPTION = 'description'
    ADDRESS_FAMILIES = 'address_families'

    REQUIRED = {
        REMOTE_ASN: int,
        PEER_IP: str,
    }

    OPTIONAL = {
        DESCRIPTION: str,
        ADDRESS_FAMILIES: dict,
    }

    # The set of address-family knobs allowed inside a neighbor's address_families dict. Each value is a
    # bool indicating whether that address-family is activated for the neighbor.
    ALLOWED_ADDRESS_FAMILIES = {
        'ipv4_unicast': bool,
        'ipv6_unicast': bool,
    }


class BGP(Module):
    module_name = 'bgp'
    identifier_attribute = BGPResources.LOCAL_ASN

    configuration_attributes = {
        BGPResources.LOCAL_ASN: {
            'type': int,
            'allowed_operations': [Op.SET],
            'examples': [65000, 4200000001],
            'description': 'The local Autonomous System Number for this device',
            'required': True
        },
        BGPResources.ROUTER_ID: {
            'type': str,
            'allowed_operations': [Op.SET, Op.DELETE],
            'examples': ['10.0.0.1', '192.168.1.1'],
            'description': 'The BGP router-id, typically a loopback or management IPV4 address'
        },
        BGPResources.NEIGHBORS: {
            'type': list,
            'sub_type': dict,
            'allowed_operations': [Op.SET, Op.ADD, Op.DELETE, Op.CLEAR],
            'examples': [[{'remote_asn': 65001, 'peer_ip': '10.0.0.2'}]],
            'description': 'A list of BGP neighbor definitions. Each entry is a vendor-neutral dict; see '
                           'BGPNeighborResources for the accepted keys.'
        },
        BGPResources.NETWORKS: {
            'type': list,
            'sub_type': str,
            'allowed_operations': [Op.SET, Op.ADD, Op.DELETE, Op.CLEAR],
            'examples': [['10.1.0.0/16', '192.168.1.0/24']],
            'description': 'A list of networks in CIDR notation advertised via BGP'
        }
    }

    def validate(self, dictionary: dict):
        validated_config = super().validate(dictionary)
        neighbors = validated_config.get(BGPResources.NEIGHBORS)
        if neighbors:
            for neighbor in neighbors:
                self.validate_neighbor(neighbor)
        return validated_config

    @staticmethod
    def validate_neighbor(neighbor: dict):
        """
        Validates a single entry of the neighbors list against the vendor-neutral neighbor schema.

        :param neighbor:
            A dict representing a single BGP neighbor
        :raises RuncibleValidationError:
            If the neighbor dict is malformed
        """
        if not isinstance(neighbor, dict):
            raise RuncibleValidationError(f"Each entry of {BGPResources.NEIGHBORS} must be a dict, got {neighbor}")

        allowed_keys = set(BGPNeighborResources.REQUIRED.keys()) | set(BGPNeighborResources.OPTIONAL.keys())
        for key in neighbor.keys():
            if key not in allowed_keys:
                raise RuncibleValidationError(f"Key {key} not defined in BGP neighbor schema")

        for key, expected_type in BGPNeighborResources.REQUIRED.items():
            if key not in neighbor:
                raise RuncibleValidationError(f"BGP neighbor is missing required attribute {key}")
            if not isinstance(neighbor[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {neighbor[key]} of key {key} in BGP neighbor must be a {expected_type}"
                )

        for key, expected_type in BGPNeighborResources.OPTIONAL.items():
            if key in neighbor and not isinstance(neighbor[key], expected_type):
                raise RuncibleValidationError(
                    f"Value {neighbor[key]} of key {key} in BGP neighbor must be a {expected_type}"
                )

        address_families = neighbor.get(BGPNeighborResources.ADDRESS_FAMILIES)
        if address_families:
            for af_key, af_value in address_families.items():
                if af_key not in BGPNeighborResources.ALLOWED_ADDRESS_FAMILIES:
                    raise RuncibleValidationError(f"Key {af_key} not defined in BGP neighbor address_families")
                expected_type = BGPNeighborResources.ALLOWED_ADDRESS_FAMILIES[af_key]
                if not isinstance(af_value, expected_type):
                    raise RuncibleValidationError(
                        f"Value {af_value} of key {af_key} in BGP neighbor address_families must be a {expected_type}"
                    )

    def determine_needs(self, other):
        needs_list = super().determine_needs(other)
        return needs_list

    def __repr__(self):
        return f"<Runcible Module: bgp {getattr(self, BGPResources.LOCAL_ASN, None)}>"
