"""EdgeOS interfaces array provider.

Mirrors :class:`CumulusInterfacesProvider`: it reads the current interface
state out of the ``parsed_commands`` the :class:`EdgeOSDriver` stored from
``show configuration commands`` and delegates per-interface fixes to
:class:`EdgeOSInterfaceProvider`.

EdgeOS interface configuration lines have the shape::

    set interfaces <type> <name> [<attribute> <value> ...]

for example ``set interfaces ethernet eth0 address 192.168.1.1/24``.
"""
from runcible.providers.provider_array import ProviderArrayBase
from runcible.providers.edgeos.interface import EdgeOSInterfaceProvider
from runcible.providers.edgeos.utils import interface_type
from runcible.modules.interfaces import Interfaces


class EdgeOSInterfacesProvider(ProviderArrayBase):
    provides_for = Interfaces
    sub_module_provider = EdgeOSInterfaceProvider

    def _create_module(self, interface):
        if_type = interface_type(interface)
        return self.device.send_command(
            f"set interfaces {if_type} {interface}")

    def _remove_module(self, interface):
        if_type = interface_type(interface)
        return self.device.send_command(
            f"delete interfaces {if_type} {interface}")

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        interface_commands = {}
        interface_instances = []
        for line in commands:
            split_line = line.split(' ')
            # Only interested in 'set interfaces <type> <name> ...' lines.
            if len(split_line) < 4:
                continue
            if split_line[0] != 'set' or split_line[1] != 'interfaces':
                continue
            if_name = split_line[3]
            if if_name not in interface_commands:
                interface_commands.update({if_name: []})
            # Anything beyond the name is an attribute of the interface. A
            # 4-token line simply declares the interface with no attributes.
            if len(split_line) > 4:
                interface_commands[if_name].append(split_line[4:])
        for k, v in interface_commands.items():
            interface_instances.append(EdgeOSInterfaceProvider.get_cstate(k, v))
        interfaces_inst = Interfaces({})
        interfaces_inst.interfaces = interface_instances
        return interfaces_inst
