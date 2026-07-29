"""Utility helpers for the EdgeOS providers.

Interface helpers
-----------------
EdgeOS/Vyatta groups interfaces under a *type* keyword in its
``set interfaces <type> <name> ...`` configuration commands (for example
``set interfaces ethernet eth0 address 192.168.1.1/24``).  When we generate
``set``/``delete`` statements we only have the interface *name* (e.g. ``eth0``)
to work from, so we infer the type from the well-known EdgeOS name prefixes.

BGP helpers
-----------
EdgeOS exposes its running configuration as a flat list of ``set ...`` commands
via ``show configuration commands`` and applies changes with ``set``/``delete``
statements under configure mode. The BGP helpers below hold the pure
(device-free) translation logic: ``parse_bgp_commands`` turns the
``protocols bgp`` output into a vendor-neutral BGP state dict, and the
``*_commands`` builders emit the ``set``/``delete protocols bgp <asn> ...``
command tree for a single change. The vendor-neutral schema lives in
``runcible.modules.bgp`` (BGPResources / BGPNeighborResources).
"""
from runcible.modules.bgp import BGPResources, BGPNeighborResources

# Ordered longest-prefix-first so that, e.g., ``switch`` is matched before a
# hypothetical shorter prefix could shadow it.
_INTERFACE_TYPE_PREFIXES = (
    ("ethernet", "ethernet"),
    ("switch", "switch"),
    ("bond", "bonding"),
    ("loopback", "loopback"),
    ("tunnel", "tunnel"),
    ("bridge", "bridge"),
    ("vtun", "openvpn"),
    ("pppoe", "pppoe"),
    ("wlan", "wireless"),
    ("lo", "loopback"),
    ("eth", "ethernet"),
    ("br", "bridge"),
    ("tun", "tunnel"),
)


def interface_type(name):
    """Return the EdgeOS interface *type* keyword for an interface ``name``.

    Falls back to ``ethernet`` (the overwhelmingly common addressed interface
    type on EdgeOS) when the name matches no known prefix.
    """
    lowered = name.lower()
    for prefix, if_type in _INTERFACE_TYPE_PREFIXES:
        if lowered.startswith(prefix):
            return if_type
    return "ethernet"


# Mapping between the vendor-neutral address-family keys and EdgeOS CLI tokens.
AF_NEUTRAL_TO_CLI = {
    'ipv4_unicast': 'ipv4-unicast',
    'ipv6_unicast': 'ipv6-unicast',
}
AF_CLI_TO_NEUTRAL = {cli: neutral for neutral, cli in AF_NEUTRAL_TO_CLI.items()}


def _bgp_prefix(asn):
    return f"set protocols bgp {asn}"


def _bgp_del_prefix(asn):
    return f"delete protocols bgp {asn}"


def router_id_set_commands(asn, router_id):
    """``set`` the BGP router-id."""
    return [f"{_bgp_prefix(asn)} parameters router-id {router_id}"]


def router_id_delete_commands(asn):
    """``delete`` the BGP router-id."""
    return [f"{_bgp_del_prefix(asn)} parameters router-id"]


def neighbor_set_commands(asn, neighbor):
    """Emit the full ``set`` command tree for a single neighbor dict.

    ``neighbor`` is a vendor-neutral neighbor dict (see BGPNeighborResources):
    remote_asn + peer_ip are required; description and address_families optional.
    """
    peer_ip = neighbor[BGPNeighborResources.PEER_IP]
    remote_asn = neighbor[BGPNeighborResources.REMOTE_ASN]
    base = f"{_bgp_prefix(asn)} neighbor {peer_ip}"
    commands = [f"{base} remote-as {remote_asn}"]

    description = neighbor.get(BGPNeighborResources.DESCRIPTION)
    if description is not None:
        commands.append(f"{base} description \"{description}\"")

    address_families = neighbor.get(BGPNeighborResources.ADDRESS_FAMILIES) or {}
    # Deterministic ordering so the emitted tree is stable/testable.
    for neutral_key in sorted(address_families.keys()):
        if address_families[neutral_key]:
            cli = AF_NEUTRAL_TO_CLI[neutral_key]
            commands.append(f"{base} address-family {cli}")
    return commands


def neighbor_delete_commands(asn, neighbor):
    """Remove a neighbor entirely by its peer IP."""
    peer_ip = neighbor[BGPNeighborResources.PEER_IP]
    return [f"{_bgp_del_prefix(asn)} neighbor {peer_ip}"]


def network_set_commands(asn, prefix):
    """Advertise a network prefix."""
    return [f"{_bgp_prefix(asn)} network {prefix}"]


def network_delete_commands(asn, prefix):
    """Withdraw a network prefix advertisement."""
    return [f"{_bgp_del_prefix(asn)} network {prefix}"]


def _tokens_after(tokens, marker):
    """Return the tokens following ``marker`` in ``tokens`` or None."""
    if marker in tokens:
        return tokens[tokens.index(marker) + 1:]
    return None


def parse_bgp_commands(commands):
    """Parse ``show configuration commands`` output into a BGP state dict.

    :param commands:
        An iterable of command strings (each a ``set protocols ...`` line, as
        produced by EdgeOS ``show configuration commands`` and stored by the
        driver's ``pre_plan_tasks`` under ``parsed_commands``).
    :return:
        A vendor-neutral dict suitable for constructing a
        :class:`runcible.modules.bgp.BGP` instance, or ``{}`` if no
        ``protocols bgp`` configuration is present. ``local_asn`` is populated
        from the ASN embedded in the command lines.
    """
    asn = None
    router_id = None
    networks = []
    # peer_ip -> neighbor dict (preserving discovery order)
    neighbors = {}

    for raw in commands:
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        # Only interested in "... protocols bgp <asn> ..." lines.
        if 'protocols' not in tokens or 'bgp' not in tokens:
            continue
        bgp_idx = tokens.index('bgp')
        rest = tokens[bgp_idx + 1:]
        if not rest:
            continue
        # rest[0] is the local ASN.
        try:
            asn = int(rest[0])
        except ValueError:
            continue
        body = rest[1:]
        if not body:
            continue

        if body[0] == 'parameters' and len(body) >= 3 and body[1] == 'router-id':
            router_id = body[2]
        elif body[0] == 'network' and len(body) >= 2:
            prefix = body[1]
            if prefix not in networks:
                networks.append(prefix)
        elif body[0] == 'neighbor' and len(body) >= 2:
            peer_ip = body[1]
            neighbor = neighbors.setdefault(peer_ip, {BGPNeighborResources.PEER_IP: peer_ip})
            attrs = body[2:]
            if not attrs:
                continue
            if attrs[0] == 'remote-as' and len(attrs) >= 2:
                try:
                    neighbor[BGPNeighborResources.REMOTE_ASN] = int(attrs[1])
                except ValueError:
                    pass
            elif attrs[0] == 'description' and len(attrs) >= 2:
                # Reconstruct a possibly-quoted, space-containing description.
                desc = ' '.join(attrs[1:])
                if desc.startswith('"') and desc.endswith('"') and len(desc) >= 2:
                    desc = desc[1:-1]
                neighbor[BGPNeighborResources.DESCRIPTION] = desc
            elif attrs[0] == 'address-family' and len(attrs) >= 2:
                cli = attrs[1]
                neutral = AF_CLI_TO_NEUTRAL.get(cli)
                if neutral is not None:
                    afs = neighbor.setdefault(BGPNeighborResources.ADDRESS_FAMILIES, {})
                    afs[neutral] = True

    if asn is None:
        return {}

    state = {BGPResources.LOCAL_ASN: asn}
    if router_id is not None:
        state[BGPResources.ROUTER_ID] = router_id
    if networks:
        state[BGPResources.NETWORKS] = networks
    if neighbors:
        state[BGPResources.NEIGHBORS] = list(neighbors.values())
    return state
