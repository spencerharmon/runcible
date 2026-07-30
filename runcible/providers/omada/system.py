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


class OmadaSystemProvider(ProviderBase):
    provides_for = System
    supported_attributes = [
        'hostname',
    ]

    def _site(self):
        return self.device.retrieve('omada_site')

    def _mac(self):
        return self.device.meta_device.get('mac')

    def _device_path(self):
        return f"/sites/{self._site()}/devices/{self._mac()}"

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
