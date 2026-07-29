"""Utility helpers for the EdgeOS providers.

EdgeOS/Vyatta groups interfaces under a *type* keyword in its
``set interfaces <type> <name> ...`` configuration commands (for example
``set interfaces ethernet eth0 address 192.168.1.1/24``).  When we generate
``set``/``delete`` statements we only have the interface *name* (e.g. ``eth0``)
to work from, so we infer the type from the well-known EdgeOS name prefixes.
"""

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
