"""A small persistent cache keyed by file signature.

The Stop hook is a fresh process every turn, so memoization alone never
survives to the next turn. Parsed rule, preset and stack files change far less
often than the hook runs, so their parsed form is kept in the data dir keyed by
(path, mtime, size) -- a changed file simply misses.

Everything here is best-effort: a cache that cannot be read or written only
costs the parse it would have saved.
"""

import atexit
import json
import os

from .paths import atomic_write, data_dir

MISS = object()

# One bundle of rules, presets and stack files is ~60 entries; the ceiling only
# stops a cache that is shared across many plugin versions from growing forever.
MAX_ENTRIES = 1000

_loaded = {}
_dirty = set()


def _path(bucket):
    return os.path.join(data_dir(), 'cache-%s.json' % bucket)


def _bucket(bucket):
    if bucket not in _loaded:
        data = {}
        try:
            with open(_path(bucket), 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        _loaded[bucket] = data if isinstance(data, dict) else {}
    return _loaded[bucket]


def get(bucket, key, signature):
    entry = _bucket(bucket).get(key)
    if isinstance(entry, list) and len(entry) == 2 and entry[0] == list(signature):
        return entry[1]
    return MISS


def put(bucket, key, signature, value):
    data = _bucket(bucket)
    data[key] = [list(signature), value]
    if len(data) > MAX_ENTRIES:
        for stale in list(data)[:len(data) - MAX_ENTRIES]:
            del data[stale]
    if not _dirty:
        atexit.register(flush)
    _dirty.add(bucket)


def flush():
    for bucket in list(_dirty):
        try:
            text = json.dumps(_loaded[bucket], ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            continue
        atomic_write(_path(bucket), text)
        _dirty.discard(bucket)
