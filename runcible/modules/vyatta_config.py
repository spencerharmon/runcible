"""Declarative raw configuration for Vyatta-derived devices (EdgeOS, VyOS).

The vendor-neutral modules (system, users, interfaces, bgp, ...) cover the
concerns runcible models generically. Everything else on a Vyatta box --
firewall rule-sets, NAT, DHCP server, DNS forwarding, service listeners,
hardware offload -- is expressed here as the configuration *statements* the
device itself prints in ``show configuration commands`` (with or without the
leading ``set``).

Semantics:

* ``statements`` -- every listed statement must be present on the device.
  A statement is satisfied when the device has it, or has it as the prefix of
  a deeper configured path.
* ``managed_paths`` -- configuration subtrees this module owns exclusively.
  Any statement on the device under one of these paths that is NOT in
  ``statements`` is deleted. Paths not listed here are additive only, so
  factory defaults and config owned by other modules are left alone.
"""
import shlex

from runcible.core.errors import RuncibleValidationError
from runcible.core.need import Need, NeedOperation as Op
from runcible.modules.module import Module


class VyattaConfigResources(object):
    STATEMENTS = 'statements'
    MANAGED_PATHS = 'managed_paths'


def tokenize(statement):
    """Parse a config statement into a tuple of unquoted tokens.

    A leading ``set`` is dropped, so device output and hand-written desired
    state compare equal regardless of quoting style.
    """
    try:
        tokens = shlex.split(statement, posix=True)
    except ValueError as e:
        raise RuncibleValidationError(msg=f"Unparseable configuration statement {statement!r}: {e}")
    if tokens and tokens[0] == 'set':
        tokens = tokens[1:]
    return tuple(tokens)


def quote_token(token):
    """Quote a token for the Vyatta CLI when it is not a plain word."""
    if token and all(ch.isalnum() or ch in '-_./:@,+=' for ch in token):
        return token
    return "'" + token.replace("'", "'\\''") + "'"


def render(tokens):
    return ' '.join(quote_token(t) for t in tokens)


def _is_prefix(prefix, tokens):
    return len(prefix) <= len(tokens) and tuple(tokens[:len(prefix)]) == tuple(prefix)


class VyattaConfig(Module):
    module_name = 'vyatta_config'
    configuration_attributes = {
        VyattaConfigResources.STATEMENTS: {
            'type': list,
            'sub_type': str,
            'allowed_operations': [Op.ADD, Op.DELETE],
            'examples': [["service nat rule 5010 type masquerade", "service ssh port 22"]],
            'description': "Configuration statements (as printed by 'show configuration commands', the leading "
                           "'set' is optional) that must be present on the device."
        },
        VyattaConfigResources.MANAGED_PATHS: {
            'type': list,
            'sub_type': str,
            'allowed_operations': [],
            'examples': [["firewall name WAN_IN", "service nat"]],
            'description': "Configuration subtrees owned exclusively by this module: device statements under these "
                           "paths that are not listed in 'statements' are deleted."
        },
    }

    def __init__(self, config_dictionary: dict):
        super().__init__(config_dictionary)
        # Canonicalise once so comparisons are quoting-insensitive.
        self.statements = [render(tokenize(s)) for s in (getattr(self, 'statements', None) or [])]
        self.managed_paths = [render(tokenize(p)) for p in (getattr(self, 'managed_paths', None) or [])]

    def determine_needs(self, other):
        desired = [tokenize(s) for s in self.statements]
        current = [tokenize(s) for s in (getattr(other, 'statements', None) or [])]
        managed = [tokenize(p) for p in self.managed_paths]
        needs = []
        doomed = []
        for cur in current:
            if not any(_is_prefix(path, cur) for path in managed):
                continue
            if any(_is_prefix(cur, want) for want in desired):
                continue
            doomed.append(cur)
        # Deletions first so a replaced single-value leaf is cleared before it is re-set.
        for node in _collapse(doomed, current, desired, managed):
            needs.append(Need(None, VyattaConfigResources.STATEMENTS, Op.DELETE, value=render(node)))
        for want in desired:
            if any(_is_prefix(want, cur) for cur in current):
                continue
            needs.append(Need(None, VyattaConfigResources.STATEMENTS, Op.ADD, value=render(want)))
        return needs


def _collapse(doomed, current, desired, managed):
    """Turn per-leaf deletions into whole-node deletions where possible.

    Deleting every leaf of a tag node one by one leaves the empty node behind
    (e.g. ``static-mapping NAME`` with neither ip-address nor mac-address),
    which Vyatta refuses to commit. So for each doomed statement, delete the
    SHORTEST ancestor (strictly below its managed path) whose entire current
    subtree is doomed and that no desired statement lives under.
    """
    doomed_set = set(doomed)
    result = []
    for stmt in doomed:
        path = max((p for p in managed if _is_prefix(p, stmt)), key=len, default=())
        # Nothing desired under the managed path at all: remove the path node
        # itself (e.g. a whole service), not its leaves one by one — Vyatta can
        # refuse to commit a service left with no mandatory children.
        if path and not any(_is_prefix(path, want) for want in desired) and \
                all(c in doomed_set for c in current if _is_prefix(path, c)):
            if path not in result and not any(_is_prefix(r, path) for r in result):
                result = [r for r in result if not _is_prefix(path, r)]
                result.append(path)
            continue
        floor = len(path)
        chosen = stmt
        for length in range(floor + 1, len(stmt)):
            node = stmt[:length]
            subtree = [c for c in current if _is_prefix(node, c)]
            if all(c in doomed_set for c in subtree) and \
                    not any(_is_prefix(node, want) for want in desired):
                chosen = node
                break
        if chosen not in result and not any(_is_prefix(r, chosen) for r in result):
            result = [r for r in result if not _is_prefix(chosen, r)]
            result.append(chosen)
    return result
