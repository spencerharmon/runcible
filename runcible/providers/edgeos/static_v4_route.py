"""EdgeOS single static-route sub-provider.

Mirrors the interface/BGP EdgeOS providers: it emits EdgeOS/Vyatta
``set``/``delete protocols static route <prefix> ...`` statements for a single
route.  The parent :class:`EdgeOSStaticV4RoutesProvider` builds current state
and delegates per-attribute fixes here via :meth:`fix_need`.

The vendor-neutral schema (``prefix`` / ``gateway_ip`` / ``distance`` /
``description``) lives in :mod:`runcible.modules.static_v4_route`.  In the
EdgeOS tree ``distance`` hangs off the route's ``next-hop <ip>`` node, so a
distance change needs the route's gateway; it is looked up from the parent
provider's desired state (each route carries exactly one ``gateway_ip``).
"""
from runcible.modules.static_v4_route import StaticV4Route, StaticV4RouteResources
from runcible.providers.sub_provider import SubProviderBase
from runcible.core.need import NeedOperation as Op
from runcible.providers.edgeos import utils


class EdgeOSStaticV4RouteProvider(SubProviderBase):
    provides_for = StaticV4Route
    supported_attributes = [
        StaticV4RouteResources.GATEWAY_IP,
        StaticV4RouteResources.DISTANCE,
        StaticV4RouteResources.DESCRIPTION,
    ]

    def _send(self, commands):
        for command in commands:
            self.device.send_command(command)

    def _gateway_for(self, prefix):
        """Return the desired ``gateway_ip`` for ``prefix`` (or None).

        ``distance`` sits under the route's ``next-hop`` in the EdgeOS tree, so
        the gateway is needed to address the right node. It is read from the
        parent provider's desired-state module, which carries the full set of
        desired routes.
        """
        dstate = getattr(self.provider, 'dstate', None)
        routes = getattr(dstate, StaticV4Route.parent_module, None) or []
        for route in routes:
            if getattr(route, StaticV4RouteResources.PREFIX, None) == prefix:
                return getattr(route, StaticV4RouteResources.GATEWAY_IP, None)
        return None

    def fix_need(self, need):
        prefix = need.module
        if need.attribute == StaticV4RouteResources.GATEWAY_IP:
            if need.operation == Op.SET:
                self._send(utils.next_hop_set_commands(prefix, need.value))
                self.complete(need)
            elif need.operation == Op.DELETE:
                self._send(utils.next_hop_delete_commands(prefix, need.value))
                self.complete(need)
        elif need.attribute == StaticV4RouteResources.DISTANCE:
            if need.operation == Op.SET:
                gateway = self._gateway_for(prefix)
                self._send(
                    utils.distance_set_commands(prefix, gateway, need.value))
                self.complete(need)
        elif need.attribute == StaticV4RouteResources.DESCRIPTION:
            if need.operation == Op.SET:
                self._send(
                    utils.description_set_commands(prefix, need.value))
                self.complete(need)
            elif need.operation == Op.DELETE:
                self._send(utils.description_delete_commands(prefix))
                self.complete(need)
