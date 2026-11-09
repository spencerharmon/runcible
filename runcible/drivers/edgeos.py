"""EdgeOS driver.

EdgeOS is Vyatta-derived, so configuration state is read via
``show configuration commands`` and changes are applied by entering
configure mode, issuing ``set``/``delete`` statements, then ``commit``
and ``save``.

Configure mode is per-session state, so both transports drive one persistent
interactive ``vbash`` session (see :mod:`runcible.protocols.vyatta_shell`):

* ``ssh``    -- interactive SSH shell (:class:`VyattaSSHProtocol`)
* ``serial`` -- RS-232 console (:class:`VyattaSerialProtocol`), e.g. for
  bootstrapping a factory-default router before it has a management address.

A device document may carry both blocks; ``default_management_protocol``
(overridable per run with ``runcible --protocol``) selects which one is used,
and the module blocks are identical either way.
"""
from runcible.protocols.vyatta_shell import VyattaSSHProtocol, VyattaSerialProtocol
from runcible.drivers.driver import DriverBase
from runcible.providers.edgeos.system import EdgeOSSystemProvider
from runcible.providers.edgeos.interfaces import EdgeOSInterfacesProvider
from runcible.providers.edgeos.static_v4_routes import EdgeOSStaticV4RoutesProvider
from runcible.providers.edgeos.bgp import EdgeOSBGPProvider
from runcible.providers.edgeos.users import EdgeOSUsersProvider
from runcible.providers.edgeos.config import EdgeOSConfigProvider


class EdgeOSDriver(DriverBase):
    driver_name = "edgeos"

    module_provider_map = {
        "system": EdgeOSSystemProvider,
        "users": EdgeOSUsersProvider,
        "interfaces": EdgeOSInterfacesProvider,
        "static_v4_routes": EdgeOSStaticV4RoutesProvider,
        "bgp": EdgeOSBGPProvider,
        "vyatta_config": EdgeOSConfigProvider,
    }

    protocol_map = {
        "ssh": VyattaSSHProtocol,
        "serial": VyattaSerialProtocol,
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
        device.store('parsed_commands', [line.strip() for line in commands.split("\n") if line.strip()])

    @staticmethod
    def pre_exec_tasks(device):
        """Enter configuration mode before applying any changes."""
        device.send_command('configure')

    @staticmethod
    def post_exec_tasks(device):
        """Commit and persist the applied configuration, then leave configure mode."""
        device.send_command('commit')
        device.send_command('save')
        device.send_command('exit')
