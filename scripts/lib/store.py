"""The one place convention-guard keeps state: a sqlite database in the data dir.

    <data dir>/convention-guard.db

Everything a hook has to remember between invocations lives here -- session
state, the verdict cache, review batches, the parse cache. The Pre/PostToolUse
hooks of parallel tool calls, the Stop hook and a reviewer subagent can all
write at once; one transaction per write and sqlite's own locking keep them
from losing each other's rows, which the 3.x files did by hand (append-only
queues, O_EXCL markers, a lock file that was written through after 5s).

Not here, on purpose: the team's dismissals (a repo file, committed and
reviewed) and the firing log (an append-only JSONL people read and move).

The schema carries a version. A database another version wrote is not
migrated: its tables are dropped and made again. This is plugin state, not
user data, and 4.0 does not carry state across versions (docs/design-4.0.md).
"""

import contextlib
import os
import shutil
import sqlite3
import time

from .paths import data_dir

SCHEMA_VERSION = 1
FILENAME = 'convention-guard.db'
# How long a writer waits for another one. The collect hook has 10s in all.
BUSY_MS = 5000
SESSION_MAX_AGE_DAYS = 7

TABLES = {
    # session -> last write, what the session GC goes by
    'session_seen': 'session TEXT PRIMARY KEY, updated REAL NOT NULL',
    'session_state': 'session TEXT PRIMARY KEY, state TEXT NOT NULL',
    'session_base': 'session TEXT PRIMARY KEY, root TEXT NOT NULL, ref TEXT NOT NULL',
    'touched': ('id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, '
                'path TEXT NOT NULL'),
    'foreign_lines': ('id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, '
                      'root TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, '
                      'lines TEXT NOT NULL'),
    'bash_snapshot': ('session TEXT NOT NULL, tool_use_id TEXT NOT NULL, body TEXT NOT NULL, '
                      'PRIMARY KEY (session, tool_use_id)'),
    'bash_miss': 'session TEXT PRIMARY KEY, count INTEGER NOT NULL',
    'verdict': ('root TEXT NOT NULL, review_key TEXT NOT NULL, verdict TEXT NOT NULL, '
                'reason TEXT, rule_id TEXT, at REAL NOT NULL, PRIMARY KEY (root, review_key)'),
    'review_batch': ('id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, root TEXT NOT NULL, '
                     'created REAL NOT NULL, body TEXT NOT NULL'),
    'review_verdicts': 'batch_id INTEGER PRIMARY KEY, recorded REAL NOT NULL, body TEXT NOT NULL',
    'parse_cache': ('bucket TEXT NOT NULL, key TEXT NOT NULL, sig TEXT NOT NULL, '
                    'value TEXT NOT NULL, PRIMARY KEY (bucket, key)'),
}
INDEXES = (
    'CREATE INDEX touched_by_session ON touched(session)',
    'CREATE INDEX foreign_by_session ON foreign_lines(session, root)',
)
SESSION_TABLES = ('session_state', 'session_base', 'touched', 'foreign_lines', 'bash_snapshot',
                  'bash_miss', 'session_seen')

# What 3.x kept in the data dir. 4.0 reads none of it; the first 4.0 run
# clears it so nothing stale is left for a person to wonder about.
LEGACY_PREFIXES = ('session-', 'touched-', 'base-', 'bash-', 'foreign-', 'bashmiss-')
LEGACY_FILES = ('verdicts.json', 'verdicts.json.lock', 'cache-yaml.json')
LEGACY_DIRS = ('reviews',)


class StoreError(Exception):
    """The database could not be opened or used. Never means "nothing stored"."""


_connections = {}


def path(base=None):
    return os.path.join(base or data_dir(), FILENAME)


def connect(db_path=None):
    """A connection to the database at `db_path` (this install's by default),
    one per path per process, with the schema in place."""
    target = os.path.abspath(db_path or path())
    conn = _connections.get(target)
    if conn is not None:
        return conn
    try:
        conn = sqlite3.connect(target, timeout=BUSY_MS / 1000.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=%d' % BUSY_MS)
        # WAL lets readers and the one writer overlap. A file system that
        # cannot do it (some network mounts) answers with another mode; the
        # default journal is slower, not wrong.
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        fresh = _prepare(conn)
    except sqlite3.Error as exc:
        raise StoreError('상태 저장소를 열 수 없습니다 (%s): %s' % (target, exc))
    if fresh:
        _clear_legacy(os.path.dirname(target))
    _connections[target] = conn
    return conn


def close_all():
    """Tests only: forget every open connection."""
    for conn in _connections.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _connections.clear()


@contextlib.contextmanager
def transaction(conn):
    """One write. BEGIN IMMEDIATE takes the write lock up front, so a
    read-modify-write inside cannot interleave with another process's."""
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')


def _prepare(conn):
    """Make the schema current. True when the database was new."""
    with transaction(conn):
        conn.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if row is not None and row[0] == str(SCHEMA_VERSION):
            return False
        names = [name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT IN ('meta', 'sqlite_sequence')")]
        for name in names:
            conn.execute('DROP TABLE "%s"' % name)
        for name, columns in TABLES.items():
            conn.execute('CREATE TABLE %s (%s)' % (name, columns))
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)",
                     (str(SCHEMA_VERSION),))
    return row is None


def _clear_legacy(base):
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        full = os.path.join(base, name)
        try:
            if name in LEGACY_DIRS and os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            elif name.startswith(LEGACY_PREFIXES) or name in LEGACY_FILES:
                if os.path.isfile(full):
                    os.remove(full)
        except OSError:
            pass


def seen(conn, session):
    """Mark a session alive. Call inside the write that touches its rows."""
    conn.execute('INSERT OR REPLACE INTO session_seen (session, updated) VALUES (?, ?)',
                 (session or 'unknown', time.time()))


def gc(conn=None, max_age_days=SESSION_MAX_AGE_DAYS):
    """Drop sessions nobody wrote to for `max_age_days`, and review batches as old."""
    conn = conn or connect()
    cutoff = time.time() - max_age_days * 86400
    with transaction(conn):
        stale = [s for (s,) in conn.execute(
            'SELECT session FROM session_seen WHERE updated < ?', (cutoff,))]
        for session in stale:
            for table in SESSION_TABLES:
                conn.execute('DELETE FROM %s WHERE session = ?' % table, (session,))
        old = [i for (i,) in conn.execute('SELECT id FROM review_batch WHERE created < ?',
                                           (cutoff,))]
        for ident in old:
            conn.execute('DELETE FROM review_verdicts WHERE batch_id = ?', (ident,))
            conn.execute('DELETE FROM review_batch WHERE id = ?', (ident,))


def last_activity(db_path):
    """When any session last wrote, read without creating anything -- for the
    install check, which must not leave a database behind. None if unknown."""
    if not os.path.isfile(db_path):
        return None
    try:
        conn = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True, timeout=1.0)
        try:
            row = conn.execute('SELECT MAX(updated) FROM session_seen').fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row and row[0] else None
