"""EdgeOS driver.

EdgeOS is Vyatta-derived, so configuration state is read via
``show configuration commands`` and changes are applied by entering
configure mode, issuing ``set``/``delete`` statements, then ``commit``
and ``save`` over SSH.

This module is the driver skeleton. The per-module providers
(system, interfaces, static_route, bgp) are wired into
``module_provider_map`` by their respective tasks; it starts empty here.
"""
from runcible.protocols.ssh_protocol import SSHProtocol
from runcible.drivers.driver import DriverBase
from runcible.providers.edgeos.system import EdgeOSSystemProvider
from runcible.providers.edgeos.interfaces import EdgeOSInterfacesProvider
from runcible.providers.edgeos.bgp import EdgeOSBGPProvider


class EdgeOSDriver(DriverBase):
    driver_name = "edgeos"

    # Filled in by the per-module provider tasks
    # (edgeos-system-provider, edgeos-interfaces-provider,
    #  edgeos-static-route-provider, edgeos-bgp-provider).
    module_provider_map = {
        "system": EdgeOSSystemProvider,
        "interfaces": EdgeOSInterfacesProvider,
        "bgp": EdgeOSBGPProvider,
    }

    protocol_map = {
        "ssh": SSHProtocol
    }

    @staticmethod
    def pre_plan_tasks(device):
        """Read the running configuration as a list of set-style commands.

        EdgeOS/Vyatta exposes the active configuration as the commands that
        would recreate it via ``show configuration commands``.
        """
        commands = device.send_command(
            "show configuration commands", memoize=True
        )
        device.store('parsed_commands', commands.split("\n"))

    @staticmethod
    def pre_exec_tasks(device):
        """Enter configuration mode before applying any changes."""
        device.send_command('configure')

    @staticmethod
    def post_exec_tasks(device):
        """Commit and persist the applied configuration."""
        device.send_command('commit')
        device.send_command('save')
