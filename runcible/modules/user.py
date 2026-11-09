from runcible.modules.module import Module
from runcible.core.need import NeedOperation as Op


class UserResources(object):
    NAME = 'name'
    FULL_NAME = 'full_name'
    LEVEL = 'level'
    ENCRYPTED_PASSWORD = 'encrypted_password'
    SSH_KEYS = 'ssh_keys'


class User(Module):
    parent_module = 'users'
    module_name = 'user'
    identifier_attribute = UserResources.NAME

    configuration_attributes = {
        UserResources.NAME: {
            'type': str,
            'allowed_operations': [Op.CREATE, Op.REMOVE],
            'examples': ['admin', 'netops'],
            'description': "The login name of the local user account"
        },
        UserResources.FULL_NAME: {
            'type': str,
            'allowed_operations': [Op.SET, Op.DELETE],
            'examples': ['Network Operator'],
            'description': "The user's full name (GECOS field)"
        },
        UserResources.LEVEL: {
            'type': str,
            'allowed_operations': [Op.SET],
            'examples': ['admin', 'operator'],
            'description': "The privilege level of the account"
        },
        UserResources.ENCRYPTED_PASSWORD: {
            'type': str,
            'allowed_operations': [Op.SET, Op.DELETE],
            'examples': ['$6$saltsalt$hashedpasswordexample'],
            'description': "A crypt(3) password hash (e.g. from `openssl passwd -6`). Plaintext passwords are never "
                           "accepted so the desired state can be stored safely."
        },
        UserResources.SSH_KEYS: {
            'type': list,
            'sub_type': str,
            'allowed_operations': [Op.ADD, Op.DELETE, Op.CLEAR],
            'examples': [['ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterial admin@example.com']],
            'description': "Authorized SSH public keys, each in authorized_keys format: '<type> <key> <comment>'. "
                           "The comment identifies the key on the device."
        },
    }

    def __repr__(self):
        return f"<Runcible Module: user {getattr(self, 'name', None)}>"


def ssh_key_parts(key_line):
    """Split an authorized_keys-style line into ``(type, key, identifier)``.

    The identifier is the comment when present, otherwise a stable name derived
    from the key material so the same key always maps to the same device entry.
    """
    parts = key_line.split()
    if len(parts) < 2:
        raise ValueError(f"SSH key '{key_line}' must be '<type> <key> [comment]'")
    key_type, key = parts[0], parts[1]
    identifier = ' '.join(parts[2:]) if len(parts) > 2 else f"{key_type}-{key[-12:]}"
    return key_type, key, identifier
