"""YAML in and out, with the bundled parser only.

Rules have to load before anything is installed, so the parser cannot be a
download. And it is the only one: PyYAML is not used even when it is there,
so two machines can never read the same rule two ways. (PyYAML stays a
development dependency -- tests/unit/test_yaml_parity.py uses it as the
answer key for miniyaml.) Writing never needs a YAML library: values are
emitted as JSON-quoted scalars, which read back identically.
"""

import json
import os

from . import miniyaml

YamlError = miniyaml.YamlError


def load(text):
    return miniyaml.load(text)


def read(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return load(fh.read()) or {}


_memo = {}


def read_cached(path):
    """read(), memoized on (mtime, size) for the life of the process.

    The Stop hook parses every rule, preset and stack file on every turn; the
    persistent cache in lib/cache.py builds on this for across-process reuse.
    """
    try:
        st = os.stat(path)
    except OSError:
        return read(path)          # let the caller see the real error
    sig = (st.st_mtime_ns, st.st_size)
    hit = _memo.get(path)
    if hit and hit[0] == sig:
        return hit[1]
    from . import cache
    value = cache.get('yaml', path, sig)
    if value is cache.MISS:
        value = read(path)
        cache.put('yaml', path, sig, value)
    _memo[path] = (sig, value)
    return value


def scalar(value):
    """One YAML scalar that round-trips through both parsers."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def flow_list(values):
    return '[%s]' % ', '.join(scalar(v) for v in values)
