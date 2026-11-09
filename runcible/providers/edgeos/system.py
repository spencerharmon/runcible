"""EdgeOS system provider: host name, domain name, time zone and resolvers.

``hostname`` may be fully qualified; EdgeOS stores the parts separately::

    set system host-name <short>
    set system domain-name <domain>

so a FQDN is split on its first dot and the cstate is reassembled the same way.

    set system time-zone <tz>
    set system name-server <ip>
"""
import shlex

from runcible.modules.system import System, SystemResources
from runcible.providers.provider import ProviderBase
from runcible.core.need import NeedOperation as Op


def _value(line, prefix):
    rest = line[len(prefix):].strip()
    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = [rest.strip("'\"")]
    return parts[0] if parts else ''


class EdgeOSSystemProvider(ProviderBase):
    provides_for = System
    supported_attributes = [
        SystemResources.HOSTNAME,
        SystemResources.TIMEZONE,
        SystemResources.DNS,
    ]

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        hostname = None
        domain = None
        timezone = None
        dns = []
        for line in commands:
            line = line.strip()
            if line.startswith('set system host-name '):
                hostname = _value(line, 'set system host-name ')
            elif line.startswith('set system domain-name '):
                domain = _value(line, 'set system domain-name ')
            elif line.startswith('set system time-zone '):
                timezone = _value(line, 'set system time-zone ')
            elif line.startswith('set system name-server '):
                dns.append(_value(line, 'set system name-server '))
        state = {}
        if hostname is not None:
            state[SystemResources.HOSTNAME] = f"{hostname}.{domain}" if domain else hostname
        if timezone is not None:
            state[SystemResources.TIMEZONE] = timezone
        if dns:
            state[SystemResources.DNS] = dns
        # Remember whether a domain is configured so a short hostname can clear it.
        self._current_domain = domain
        return System(state)

    def _set_hostname(self, hostname):
        short, _, domain = hostname.partition('.')
        result = self.device.send_command(f"set system host-name {short}")
        if domain:
            self.device.send_command(f"set system domain-name {domain}")
        elif getattr(self, '_current_domain', None):
            self.device.send_command("delete system domain-name")
        return result

    def _delete_hostname(self):
        return self.device.send_command("delete system host-name")

    def fix_needs(self):
        for need in self.get_needs():
            if need.attribute == SystemResources.HOSTNAME:
                if need.operation is Op.SET:
                    self._set_hostname(need.value)
                    self.complete(need)
                elif need.operation is Op.DELETE:
                    self._delete_hostname()
                    self.complete(need)
            elif need.attribute == SystemResources.TIMEZONE:
                if need.operation is Op.SET:
                    self.device.send_command(f"set system time-zone {need.value}")
                    self.complete(need)
                elif need.operation is Op.DELETE:
                    self.device.send_command("delete system time-zone")
                    self.complete(need)
            elif need.attribute == SystemResources.DNS:
                if need.operation is Op.ADD:
                    self.device.send_command(f"set system name-server {need.value}")
                    self.complete(need)
                elif need.operation is Op.DELETE:
                    self.device.send_command(f"delete system name-server {need.value}")
                    self.complete(need)
                elif need.operation is Op.CLEAR:
                    self.device.send_command("delete system name-server")
                    self.complete(need)
                elif need.operation is Op.SET:
                    self.device.send_command("delete system name-server")
                    for server in need.value:
                        self.device.send_command(f"set system name-server {server}")
                    self.complete(need)
