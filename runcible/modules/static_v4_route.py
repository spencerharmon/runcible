from runcible.modules.module import Module
from runcible.core.need import Need, NeedOperation as Op


class StaticV4RouteResources(object):
    PREFIX = 'prefix'
    GATEWAY_IP = 'gateway_ip'
    DISTANCE = 'distance'
    DESCRIPTION = 'description'


class StaticV4Route(Module):
    parent_module = 'static_v4_routes'
    module_name = 'static_v4_route'
    identifier_attribute = StaticV4RouteResources.PREFIX

    configuration_attributes = {
        StaticV4RouteResources.PREFIX: {
            'type': str,
            'allowed_operations': [Op.CREATE, Op.REMOVE],
            'examples': ['10.1.0.0/16', '192.168.1.0/24'],
            'description': 'The prefix used for routing in CIDR notation'
        },
        StaticV4RouteResources.GATEWAY_IP: {
            'type': str,
            'allowed_operations': [Op.SET, Op.DELETE],
            'examples': ['10.1.2.3', '192.168.1.1'],
            # NOTE: not 'required'. StaticV4Route is an array sub_module
            # (parent_module='static_v4_routes'); ModuleArray.determine_needs
            # builds an empty ``StaticV4Route({})`` to diff a brand-new route
            # against, so the sub_module MUST be constructible from ``{}``. A
            # required attribute makes that empty-instance construction raise a
            # ValidationError and breaks adding any new route. The gateway is
            # still emitted whenever the desired state carries it.
        },
        StaticV4RouteResources.DISTANCE: {
            'type': int,
            'allowed_operations': [Op.SET],
            'examples': [255, 1],
            'description': 'Administrative distance to the gateway specified'
        },
        StaticV4RouteResources.DESCRIPTION: {
            'type': str,
            'allowed_operations': [Op.SET, Op.DELETE],
            'examples': "This is a description",
            'description': 'Describe the route'
        }
    }