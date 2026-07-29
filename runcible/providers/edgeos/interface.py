"""EdgeOS single-interface sub-provider.

Mirrors :class:`CumulusInterfaceProvider` but emits EdgeOS/Vyatta
``set``/``delete`` configuration statements instead of Cumulus ``net`` commands.

EdgeOS exposes its running configuration as ``set ...`` commands via
``show configuration commands`` (see :class:`EdgeOSDriver`).  For interface
addressing the relevant lines look like::

    set interfaces ethernet eth0 address 192.168.1.1/24
    set interfaces ethernet eth0 address 10.0.0.1/24

Changes are applied inside configure mode with matching ``set``/``delete``
statements.
"""
from runcible.modules.interface import Interface, InterfaceResources
from runcible.providers.sub_provider import SubProviderBase
from runcible.core.need import NeedOperation as Op
from runcible.providers.edgeos.utils import interface_type


class EdgeOSInterfaceProvider(SubProviderBase):
    provides_for = Interface
    supported_attributes = [
        InterfaceResources.NAME,
        InterfaceResources.IPV4_ADDRESSES,
    ]

    @staticmethod
    def get_cstate(name, interface_commands):
        """Build an :class:`Interface` module from parsed EdgeOS commands.

        Called by :class:`EdgeOSInterfacesProvider` with the interface ``name``
        and ``interface_commands`` - the list of token-lists that followed the
        ``set interfaces <type> <name>`` prefix for this interface.
        """
        interface_config = {}
        for command in interface_commands:
            if not command:
                continue
            if command[0] == 'address' and len(command) > 1:
                # EdgeOS supports 'address dhcp'/'address dhcpv6' which are not
                # static IPv4 addresses; only track CIDR addresses here.
                value = command[1]
                if value in ('dhcp', 'dhcpv6'):
                    continue
                if '.' not in value:
                    # Skip IPv6 addresses (no IPv6 module attribute yet).
                    continue
                if not interface_config.get(InterfaceResources.IPV4_ADDRESSES, None):
                    interface_config.update({InterfaceResources.IPV4_ADDRESSES: []})
                interface_config[InterfaceResources.IPV4_ADDRESSES].append(value)
        interface_config.update({'name': name})
        return Interface(interface_config)

    def _add_interface_ipv4_address(self, interface, address):
        if_type = interface_type(interface)
        return self.device.send_command(
            f"set interfaces {if_type} {interface} address {address}")

    def _del_interface_ipv4_address(self, interface, address):
        if_type = interface_type(interface)
        return self.device.send_command(
            f"delete interfaces {if_type} {interface} address {address}")

    def _clear_interface_ipv4_address(self, interface):
        if_type = interface_type(interface)
        return self.device.send_command(
            f"delete interfaces {if_type} {interface} address")

    def _set_ipv4_addresses(self, interface, addresses):
        self._clear_interface_ipv4_address(interface)
        for address in addresses:
            self._add_interface_ipv4_address(interface, address)

    def fix_need(self, need):
        if need.attribute == InterfaceResources.IPV4_ADDRESSES:
            if need.operation == Op.ADD:
                self._add_interface_ipv4_address(need.module, need.value)
                self.complete(need)
            elif need.operation == Op.DELETE:
                self._del_interface_ipv4_address(need.module, need.value)
                self.complete(need)
            elif need.operation == Op.CLEAR:
                self._clear_interface_ipv4_address(need.module)
                self.complete(need)
            elif need.operation == Op.SET:
                self._set_ipv4_addresses(need.module, need.value)
                self.complete(need)
