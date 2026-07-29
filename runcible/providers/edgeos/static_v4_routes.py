"""EdgeOS static IPv4 routes array provider.

Mirrors :class:`EdgeOSInterfacesProvider`: it reads current static-route state
out of the ``parsed_commands`` the :class:`EdgeOSDriver` stored from ``show
configuration commands`` (:meth:`get_cstate`) and delegates per-route
attribute fixes to :class:`EdgeOSStaticV4RouteProvider`.

EdgeOS/Vyatta static route lines have the shape::

    set protocols static route <prefix> next-hop <ip> [distance <n>]
    set protocols static route <prefix> description '<text>'

and changes are applied with matching ``set``/``delete protocols static route``
statements. The pure (device-free) translation lives in
:mod:`runcible.providers.edgeos.utils`.
"""
from runcible.providers.provider_array import ProviderArrayBase
from runcible.providers.edgeos.static_v4_route import EdgeOSStaticV4RouteProvider
from runcible.providers.edgeos import utils
from runcible.modules.static_v4_routes import StaticV4Routes


class EdgeOSStaticV4RoutesProvider(ProviderArrayBase):
    provides_for = StaticV4Routes
    sub_module_provider = EdgeOSStaticV4RouteProvider

    def _create_module(self, prefix):
        for command in utils.static_route_create_commands(prefix):
            self.device.send_command(command)

    def _remove_module(self, prefix):
        for command in utils.static_route_remove_commands(prefix):
            self.device.send_command(command)

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        routes = utils.parse_static_route_commands(commands or [])
        routes_inst = StaticV4Routes([])
        routes_inst.static_v4_routes = [
            EdgeOSStaticV4RouteProvider.provides_for(route)
            for route in routes.values()
        ]
        return routes_inst
