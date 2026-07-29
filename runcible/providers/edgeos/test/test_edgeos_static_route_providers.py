import unittest
from unittest.mock import Mock

from runcible.providers.edgeos.static_v4_routes import EdgeOSStaticV4RoutesProvider
from runcible.providers.edgeos.static_v4_route import EdgeOSStaticV4RouteProvider
from runcible.modules.static_v4_route import StaticV4RouteResources
from runcible.core.need import Need, NeedOperation as Op
from runcible.core.test_utilities import append_operation_test_cases


system_dict = {}
device = Mock()
prov = EdgeOSStaticV4RoutesProvider(device, {})


class TestStaticRouteNeedCompletion(unittest.TestCase):
    longMessage = True


# Auto-generated per-operation smoke tests (mirrors the interfaces suite): each
# supported sub-module attribute/operation must drive fix_needs to completion.
append_operation_test_cases(prov, system_dict, TestStaticRouteNeedCompletion)


class TestEdgeOSStaticRouteGetCstate(unittest.TestCase):
    longMessage = True

    def _provider_with_commands(self, commands):
        dev = Mock()
        dev.retrieve.return_value = commands
        return EdgeOSStaticV4RoutesProvider(dev, {})

    def test_parses_single_route_next_hop(self):
        commands = [
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        routes = {r.prefix: r for r in cstate.static_v4_routes}
        self.assertIn("10.1.0.0/16", routes)
        self.assertEqual(routes["10.1.0.0/16"].gateway_ip, "10.1.2.3")

    def test_parses_next_hop_with_distance(self):
        commands = [
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3 distance 5",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        routes = {r.prefix: r for r in cstate.static_v4_routes}
        self.assertEqual(routes["10.1.0.0/16"].gateway_ip, "10.1.2.3")
        self.assertEqual(routes["10.1.0.0/16"].distance, 5)

    def test_parses_description(self):
        commands = [
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3",
            "set protocols static route 10.1.0.0/16 description 'uplink route'",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        routes = {r.prefix: r for r in cstate.static_v4_routes}
        self.assertEqual(routes["10.1.0.0/16"].description, "uplink route")

    def test_parses_multiple_routes(self):
        commands = [
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3",
            "set protocols static route 192.168.0.0/24 next-hop 192.168.1.1",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        routes = {r.prefix: r for r in cstate.static_v4_routes}
        self.assertEqual(sorted(routes.keys()),
                         ["10.1.0.0/16", "192.168.0.0/24"])

    def test_ignores_non_route_lines(self):
        commands = [
            "set system host-name router",
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3",
            "set protocols bgp 65000 router-id 1.1.1.1",
            "set protocols static route6 2001:db8::/32 next-hop fe80::1",
        ]
        cstate = self._provider_with_commands(commands).get_cstate()
        routes = {r.prefix: r for r in cstate.static_v4_routes}
        self.assertEqual(list(routes.keys()), ["10.1.0.0/16"])


class TestEdgeOSStaticRouteCommandGeneration(unittest.TestCase):
    """Assert the REAL set/delete command lists against known states."""

    longMessage = True

    def _fix(self, cstate_commands, dstate):
        dev = Mock()
        dev.retrieve.return_value = cstate_commands
        sent = []
        dev.send_command.side_effect = lambda cmd, *a, **k: sent.append(cmd)
        provider = EdgeOSStaticV4RoutesProvider(dev, dstate)
        provider.load_module_cstate()
        provider.determine_needs()
        provider.fix_needs()
        return sent

    def test_add_new_route(self):
        sent = self._fix(
            [],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3"}],
        )
        self.assertIn("set protocols static route 10.1.0.0/16", sent)
        self.assertIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3", sent)

    def test_add_route_with_distance(self):
        sent = self._fix(
            [],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3",
              "distance": 5}],
        )
        self.assertIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3 "
            "distance 5", sent)

    def test_add_route_with_description(self):
        sent = self._fix(
            [],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3",
              "description": "uplink route"}],
        )
        self.assertIn(
            "set protocols static route 10.1.0.0/16 description 'uplink route'",
            sent)

    def test_change_gateway(self):
        sent = self._fix(
            ["set protocols static route 10.1.0.0/16 next-hop 10.1.2.3"],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.9.9.9"}],
        )
        self.assertIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.9.9.9", sent)

    def test_change_distance(self):
        sent = self._fix(
            ["set protocols static route 10.1.0.0/16 next-hop 10.1.2.3 "
             "distance 1"],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3",
              "distance": 10}],
        )
        self.assertIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3 "
            "distance 10", sent)
        # The gateway is unchanged, so it must not be re-set.
        self.assertNotIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3", sent)

    def test_remove_description(self):
        sent = self._fix(
            ["set protocols static route 10.1.0.0/16 next-hop 10.1.2.3",
             "set protocols static route 10.1.0.0/16 description 'old'"],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3",
              "description": False}],
        )
        self.assertIn(
            "delete protocols static route 10.1.0.0/16 description", sent)

    def test_noop_when_state_matches(self):
        sent = self._fix(
            ["set protocols static route 10.1.0.0/16 next-hop 10.1.2.3"],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3"}],
        )
        self.assertEqual(sent, [])

    def test_add_second_route_keeps_existing(self):
        sent = self._fix(
            ["set protocols static route 10.1.0.0/16 next-hop 10.1.2.3"],
            [{"prefix": "10.1.0.0/16", "gateway_ip": "10.1.2.3"},
             {"prefix": "192.168.0.0/24", "gateway_ip": "192.168.1.1"}],
        )
        self.assertIn(
            "set protocols static route 192.168.0.0/24 next-hop 192.168.1.1",
            sent)
        # The already-correct route must not be touched.
        self.assertNotIn(
            "set protocols static route 10.1.0.0/16 next-hop 10.1.2.3", sent)


class TestEdgeOSStaticRouteProviderDirect(unittest.TestCase):
    longMessage = True

    def _parent(self):
        dev = Mock()
        sent = []
        dev.send_command.side_effect = lambda cmd, *a, **k: sent.append(cmd)
        parent = EdgeOSStaticV4RoutesProvider(dev, {})
        return parent, sent

    def test_remove_route_module(self):
        parent, sent = self._parent()
        need = Need("static_v4_routes", "10.1.0.0/16", Op.REMOVE)
        parent.needed_actions.append(need)
        parent.fix_needs()
        self.assertEqual(
            sent, ["delete protocols static route 10.1.0.0/16"])
        self.assertEqual(parent.needed_actions, [])

    def test_delete_gateway_no_value(self):
        parent, sent = self._parent()
        need = Need("10.1.0.0/16", StaticV4RouteResources.GATEWAY_IP,
                    Op.DELETE, parent_module="static_v4_routes")
        parent.needed_actions.append(need)
        parent.sub_provider.fix_need(need)
        self.assertEqual(
            sent, ["delete protocols static route 10.1.0.0/16 next-hop"])


if __name__ == "__main__":
    unittest.main()
