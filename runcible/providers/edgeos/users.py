"""EdgeOS local user accounts (``system login user``).

EdgeOS lines handled::

    set system login user <name> authentication encrypted-password <hash>
    set system login user <name> authentication public-keys <id> key <key>
    set system login user <name> authentication public-keys <id> type <type>
    set system login user <name> full-name <text>
    set system login user <name> level <level>
"""
import shlex

from runcible.modules.users import Users
from runcible.modules.user import User, UserResources, ssh_key_parts
from runcible.modules.vyatta_config import render
from runcible.providers.provider_array import ProviderArrayBase
from runcible.providers.sub_provider import SubProviderBase
from runcible.core.need import NeedOperation as Op

_PREFIX = ('system', 'login', 'user')


def _base(name):
    return ['system', 'login', 'user', name]


class EdgeOSUserProvider(SubProviderBase):
    provides_for = User
    supported_attributes = [
        UserResources.NAME,
        UserResources.FULL_NAME,
        UserResources.LEVEL,
        UserResources.ENCRYPTED_PASSWORD,
        UserResources.SSH_KEYS,
    ]

    @staticmethod
    def get_cstate(name, user_tokens):
        """Build a :class:`User` from the token lists following ``system login user <name>``."""
        state = {UserResources.NAME: name}
        keys = {}
        for tokens in user_tokens:
            if len(tokens) >= 2 and tokens[0] == 'full-name':
                state[UserResources.FULL_NAME] = tokens[1]
            elif len(tokens) >= 2 and tokens[0] == 'level':
                state[UserResources.LEVEL] = tokens[1]
            elif len(tokens) >= 3 and tokens[:2] == ['authentication', 'encrypted-password']:
                state[UserResources.ENCRYPTED_PASSWORD] = tokens[2]
            elif len(tokens) >= 5 and tokens[:2] == ['authentication', 'public-keys']:
                key_id, attr, value = tokens[2], tokens[3], tokens[4]
                keys.setdefault(key_id, {})[attr] = value
        ssh_keys = []
        for key_id, attrs in keys.items():
            if 'type' in attrs and 'key' in attrs:
                ssh_keys.append(f"{attrs['type']} {attrs['key']} {key_id}")
        if ssh_keys:
            state[UserResources.SSH_KEYS] = ssh_keys
        return User(state)

    def _send(self, verb, tokens):
        return self.device.send_command(f"{verb} {render(tokens)}")

    def fix_need(self, need):
        name = need.module
        attr = need.attribute
        op = need.operation
        if attr == UserResources.FULL_NAME:
            if op == Op.SET:
                self._send('set', _base(name) + ['full-name', need.value])
            elif op == Op.DELETE:
                self._send('delete', _base(name) + ['full-name'])
            else:
                return
        elif attr == UserResources.LEVEL:
            if op != Op.SET:
                return
            self._send('set', _base(name) + ['level', need.value])
        elif attr == UserResources.ENCRYPTED_PASSWORD:
            if op == Op.SET:
                self._send('set', _base(name) + ['authentication', 'encrypted-password', need.value])
            elif op == Op.DELETE:
                self._send('delete', _base(name) + ['authentication', 'encrypted-password'])
            else:
                return
        elif attr == UserResources.SSH_KEYS:
            if op == Op.ADD:
                key_type, key, key_id = ssh_key_parts(need.value)
                prefix = _base(name) + ['authentication', 'public-keys', key_id]
                self._send('set', prefix + ['type', key_type])
                self._send('set', prefix + ['key', key])
            elif op == Op.DELETE:
                _, _, key_id = ssh_key_parts(need.value)
                self._send('delete', _base(name) + ['authentication', 'public-keys', key_id])
            elif op == Op.CLEAR:
                self._send('delete', _base(name) + ['authentication', 'public-keys'])
            else:
                return
        else:
            return
        self.complete(need)


class EdgeOSUsersProvider(ProviderArrayBase):
    provides_for = Users
    sub_module_provider = EdgeOSUserProvider

    def _create_module(self, name):
        return self.device.send_command(f"set {render(_base(name))}")

    def _remove_module(self, name):
        return self.device.send_command(f"delete {render(_base(name))}")

    def get_cstate(self):
        commands = self.device.retrieve('parsed_commands')
        per_user = {}
        for line in commands:
            line = line.strip()
            if not line.startswith('set system login user '):
                continue
            try:
                tokens = shlex.split(line)[1:]
            except ValueError:
                continue
            if len(tokens) < 4 or tuple(tokens[:3]) != _PREFIX:
                continue
            per_user.setdefault(tokens[3], []).append(tokens[4:])
        users = Users([])
        users.users = [EdgeOSUserProvider.get_cstate(n, t) for n, t in per_user.items()]
        return users
