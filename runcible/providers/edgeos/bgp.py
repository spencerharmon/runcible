"""EdgeOS provider for the vendor-neutral ``bgp`` module.

EdgeOS/Vyatta reads its running config as a flat list of ``set ...`` commands
(``show configuration commands``, stored by the driver under
``parsed_commands``) and applies changes with ``set``/``delete protocols bgp
<asn> ...`` statements. This provider:

* builds the current BGP state by parsing those stored commands
  (``get_cstate``), and
* translates the needs produced by diffing desired vs current state into the
  EdgeOS ``set``/``delete`` command tree (``fix_needs``): local-as/router-id,
  per-neighbor remote-as/description/address-family, and network
  advertisements, plus the matching deletes for removed elements.

It mirrors the Cumulus providers (``CumulusSystemProvider``) in shape; the pure
CLI translation lives in ``runcible.providers.edgeos.utils``.
"""
from runcible.modules.bgp import BGP, BGPResources
from runcible.providers.provider import ProviderBase
from runcible.core.need import NeedOperation as Op
from runcible.providers.edgeos import utils


class EdgeOSBGPProvider(ProviderBase):
    provides_for = BGP
    supported_attributes = [
        BGPResources.ROUTER_ID,
        BGPResources.NEIGHBORS,
        BGPResources.NETWORKS,
    ]

    def __init__(self, device_instance, dstate):
        # BGP requires ``local_asn`` at construction, so the ProviderBase default
        # of ``self.provides_for({})`` for the initial cstate would raise. Build
        # the cstate placeholder carrying just the ASN from the desired state.
        self.device = device_instance
        self.dstate = None
        self.needed_actions = []
        self.completed_actions = []
        self.failed_actions = []
        self.load_module_dstate(dstate)
        self.cstate = self.provides_for(
            {BGPResources.LOCAL_ASN: getattr(self.dstate, BGPResources.LOCAL_ASN)}
        )

    @property
    def _asn(self):
        return getattr(self.dstate, BGPResources.LOCAL_ASN)

    def get_cstate(self):
        """Parse the stored EdgeOS config commands into a BGP module."""
        commands = self.device.retrieve('parsed_commands')
        state = utils.parse_bgp_commands(commands or [])
        if not state:
            # No BGP configured yet; represent an empty state keyed by our ASN so
            # the diff yields ADD/SET needs for everything in the desired state.
            state = {BGPResources.LOCAL_ASN: self._asn}
        return BGP(state)

    def _send(self, commands):
        for command in commands:
            self.device.send_command(command)

    def fix_needs(self):
        asn = self._asn
        for need in self.get_needs():
            if need.attribute == BGPResources.ROUTER_ID:
                if need.operation == Op.SET:
                    self._send(utils.router_id_set_commands(asn, need.value))
                    self.complete(need)
                elif need.operation == Op.DELETE:
                    self._send(utils.router_id_delete_commands(asn))
                    self.complete(need)
            elif need.attribute == BGPResources.NEIGHBORS:
                if need.operation == Op.ADD:
                    self._send(utils.neighbor_set_commands(asn, need.value))
                    self.complete(need)
                elif need.operation == Op.DELETE:
                    self._send(utils.neighbor_delete_commands(asn, need.value))
                    self.complete(need)
                elif need.operation == Op.CLEAR:
                    self._send([f"delete protocols bgp {asn} neighbor"])
                    self.complete(need)
            elif need.attribute == BGPResources.NETWORKS:
                if need.operation == Op.ADD:
                    self._send(utils.network_set_commands(asn, need.value))
                    self.complete(need)
                elif need.operation == Op.DELETE:
                    self._send(utils.network_delete_commands(asn, need.value))
                    self.complete(need)
                elif need.operation == Op.CLEAR:
                    self._send([f"delete protocols bgp {asn} network"])
                    self.complete(need)
