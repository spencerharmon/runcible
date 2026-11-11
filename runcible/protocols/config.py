"""Protocol-neutral configuration resolution without persisting secrets."""
import os
import re

from runcible.core.errors import RuncibleValidationError


_ENV_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def resolve_env(value, key='value'):
    """Expand environment references; errors identify the key, never its value."""
    if not isinstance(value, str):
        return value

    def repl(match):
        name = match.group(1)
        if name not in os.environ:
            raise RuncibleValidationError(
                msg=f"Environment variable referenced by protocol key '{key}' is not set")
        return os.environ[name]
    return _ENV_RE.sub(repl, value)
