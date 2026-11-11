"""Omada provider for the vendor-neutral ``system`` module.

Device naming on an Omada-managed device is exposed by the Northbound API as
the device's ``name`` field, scoped to the site the driver selected in
``pre_plan_tasks``/``pre_exec_tasks`` (see ``runcible.drivers.omada``). This
provider reads that field to build the current state, diffs it against the
desired state via the normal :class:`ProviderBase` need machinery, and emits
ordered Northbound API operations (never shell commands) to reconcile it.

Device identity within a site is the device's ``mac`` address, delivered
through the device's per-device meta config (the same ``meta_device`` plumbing
that supplies ``site`` to the driver). The selected site is read back from
where the driver stored it (``device.retrieve('omada_site')``) rather than
re-resolved here, so this provider stays a thin consumer of the driver's
lifecycle hooks.
"""
from runcible.modules.system import System, SystemResources
from runcible.providers.provider import ProviderBase
from runcible.core.need import NeedOperation as Op
from runcible.core.errors import RuncibleValidationError


class OmadaSystemProvider(ProviderBase):
    provides_for = System
    supported_attributes = [
        'hostname',
    ]

    def __init__(self, device_instance, dstate):
        self._resolved_identity = None
        self._resolved_path = None
        super().__init__(device_instance, dstate)

    def _device_path(self):
        site = self.device.retrieve('omada_site')
        mac = self.device.meta_device.get('mac')
        if not isinstance(site, str) or not site.strip():
            raise RuncibleValidationError(
                msg="Omada system provider requires a selected site (omada_site).")
        if not isinstance(mac, str) or not mac.strip():
            raise RuncibleValidationError(
                msg="Omada system provider requires the 'mac' meta config.")
        mac = mac.upper().replace(':', '-')
        identity = (site, mac)
        if self._resolved_identity == identity:
            return self._resolved_path

        inventory = self.device.send_command({
            'method': 'GET',
            'path': f'/sites/{site}/devices',
        })
        if isinstance(inventory, dict):
            inventory = inventory.get('data')
        if not isinstance(inventory, list):
            raise RuncibleValidationError(
                msg="Omada device inventory must contain a list of devices.")
        for device in inventory:
            if not isinstance(device, dict):
                continue
            device_mac = device.get('mac')
            if not isinstance(device_mac, str) or device_mac.upper().replace(':', '-') != mac:
                continue
            device_type = device.get('type')
            collection = {'ap': 'eaps', 'switch': 'switches', 'gateway': 'gateways'}.get(
                device_type if isinstance(device_type, str) else None)
            if collection is None:
                raise RuncibleValidationError(
                    msg=f"Unsupported Omada device type {device_type!r} for MAC {mac}.")
            self._resolved_path = f'/sites/{site}/{collection}/{device_mac}'
            self._resolved_identity = identity
            return self._resolved_path
        raise RuncibleValidationError(
            msg=f"Omada device MAC {mac} was not found in site {site!r}.")

    def get_cstate(self):
        result = self.device.send_command({
            'method': 'GET',
            'path': self._device_path(),
        })
        state = {}
        if isinstance(result, dict) and result.get('name') is not None:
            state['hostname'] = result['name']
        return System(state)

    def _set_hostname(self, hostname):
        return self.device.send_command({
            'method': 'PATCH',
            'path': self._device_path(),
            'data': {'name': hostname},
        })

    def fix_needs(self):
        for need in self.needed_actions:
            if need.attribute is SystemResources.HOSTNAME:
                if need.operation is Op.SET:
                    self._set_hostname(need.value)
                    self.complete(need)
