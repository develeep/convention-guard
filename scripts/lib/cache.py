"""A small persistent cache keyed by file signature, in the store.

The Stop hook is a fresh process every turn, so memoization alone never
survives to the next turn. Parsed rule, preset and stack files change far less
often than the hook runs, so their parsed form is kept keyed by
(path, mtime, size) -- a changed file simply misses.

A bucket is read once per process and written back in one transaction at
exit. Everything here is best-effort: a cache that cannot be read or written
only costs the parse it would have saved.
"""

import atexit
import json

from . import store

MISS = object()

# One bundle of rules, presets and stack files is ~60 entries; the ceiling only
# stops a cache that is shared across many plugin versions from growing forever.
MAX_ENTRIES = 1000

_loaded = {}
_dirty = {}


def _bucket(bucket):
    if bucket not in _loaded:
        data = {}
        try:
            rows = store.connect().execute('SELECT key, sig, value FROM parse_cache WHERE bucket = ?',
                                           (bucket,))
            for key, sig, value in rows:
                try:
                    data[key] = (json.loads(sig), json.loads(value))
                except ValueError:
                    continue
        except Exception:       # noqa: BLE001 -- a cache miss, nothing more
            data = {}
        _loaded[bucket] = data
    return _loaded[bucket]


def get(bucket, key, signature):
    entry = _bucket(bucket).get(key)
    if entry is not None and entry[0] == list(signature):
        return entry[1]
    return MISS


def put(bucket, key, signature, value):
    _bucket(bucket)[key] = (list(signature), value)
    if not _dirty:
        atexit.register(flush)
    _dirty.setdefault(bucket, set()).add(key)


def flush():
    if not _dirty:
        return
    try:
        conn = store.connect()
        with store.transaction(conn):
            for bucket, keys in _dirty.items():
                rows = []
                for key in keys:
                    sig, value = _loaded[bucket][key]
                    try:
                        rows.append((bucket, key, json.dumps(sig),
                                     json.dumps(value, ensure_ascii=False, default=str)))
                    except (TypeError, ValueError):
                        continue
                conn.executemany('INSERT OR REPLACE INTO parse_cache (bucket, key, sig, value) '
                                 'VALUES (?, ?, ?, ?)', rows)
                count = conn.execute('SELECT COUNT(*) FROM parse_cache WHERE bucket = ?',
                                     (bucket,)).fetchone()[0]
                if count > MAX_ENTRIES:
                    conn.execute('DELETE FROM parse_cache WHERE bucket = ? AND key NOT IN '
                                 '(SELECT key FROM parse_cache WHERE bucket = ? '
                                 'ORDER BY rowid DESC LIMIT ?)', (bucket, bucket, MAX_ENTRIES))
    except Exception:           # noqa: BLE001 -- best-effort, see the module doc
        pass
    _dirty.clear()
