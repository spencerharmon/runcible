"""EdgeOS provider for the raw ``vyatta_config`` module.

Current state is every ``set`` line from ``show configuration commands``;
needs are applied verbatim as ``set``/``delete`` statements inside the
driver's configure session.
"""
from runcible.modules.vyatta_config import VyattaConfig, VyattaConfigResources
from runcible.providers.provider import ProviderBase
from runcible.core.need import NeedOperation as Op


class EdgeOSConfigProvider(ProviderBase):
    provides_for = VyattaConfig
    supported_attributes = [
        VyattaConfigResources.STATEMENTS,
    ]

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        statements = [line.strip() for line in commands if line.strip().startswith('set ')]
        return VyattaConfig({VyattaConfigResources.STATEMENTS: statements})

    def fix_needs(self):
        for need in self.get_needs():
            if need.attribute != VyattaConfigResources.STATEMENTS:
                continue
            if need.operation == Op.ADD:
                self.device.send_command(f"set {need.value}")
                self.complete(need)
            elif need.operation == Op.DELETE:
                self.device.send_command(f"delete {need.value}")
                self.complete(need)
