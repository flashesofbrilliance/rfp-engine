"""Where settings come from: the environment first, then the .env file at the repo root.

Surrounding quotes are stripped, and a key that appears twice is an error, never a silent pick.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ConfigError(Exception):
    pass


def env(name, root=None):
    """The value of `name`, or None. Raises ConfigError if .env names it more than once."""
    v = os.environ.get(name)
    if v:
        return v.strip().strip("'\"")
    path = os.path.join(root or ROOT, ".env")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        found = [l.split("=", 1)[1].strip().strip("'\"") for l in f if l.startswith(name + "=")]
    if len(found) > 1:
        raise ConfigError(".env has %d %s lines; keep exactly one" % (len(found), name))
    return found[0] if found and found[0] else None
