from runcible.modules.system import System, SystemResources
from runcible.providers.provider import ProviderBase
from runcible.core.need import NeedOperation as Op


class EdgeOSSystemProvider(ProviderBase):
    provides_for = System
    supported_attributes = [
        'hostname',
    ]

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        hostname = None
        for line in commands:
            line = line.strip()
            if line.startswith('set system host-name '):
                hostname = line[len('set system host-name '):].strip().strip("'\"")
        state = {}
        if hostname is not None:
            state.update({'hostname': hostname})
        return System(state)

    def _set_hostname(self, hostname):
        return self.device.send_command(f"set system host-name {hostname}")

    def _delete_hostname(self):
        return self.device.send_command("delete system host-name")

    def fix_needs(self):
        for need in self.needed_actions:
            if need.attribute is SystemResources.HOSTNAME:
                if need.operation is Op.SET:
                    self._set_hostname(need.value)
                    self.complete(need)
                elif need.operation is Op.DELETE:
                    self._delete_hostname()
                    self.complete(need)
