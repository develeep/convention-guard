"""Per-session state kept between hook invocations, in the store (store.py).

- touched: paths the agent edited, in touch order. Parallel PostToolUse hooks
  each add rows; nothing is read-modify-written.
- base: the first HEAD seen for a session. The first writer wins.
- foreign: lines in touched files the agent did not write (see below).
- bash snapshot / bash miss: what a Bash call's Pre saw, and Bash calls whose
  Pre never ran.
- state: everything else, written only by the Stop hook, which Claude Code
  runs one at a time per session.

Every function swallows a store failure where 3.x swallowed a file failure:
a collect hook must not take the tool call down. The Stop hook reads through
the same functions, and its caller (check.py) says so when the store itself
cannot be opened.
"""

import json
import os

from . import store

DEFAULT_STATE = {
    'consecutive_blocks': 0,   # blocks in a row without a clean turn (loop guard)
    'blocks': 0,
    'fired_rules': [],         # rules whose findings were fixed this session (once_per_session)
    'cycle': None,             # the open verification cycle, if any (see cycle.py)
    'unresolved': [],          # candidate keys a closed cycle left unfixed
    'closed_in_continuation': False,
}


def _sid(session_id):
    return str(session_id or 'unknown')


def _conn():
    return store.connect()


def load(session_id):
    row = _conn().execute('SELECT state FROM session_state WHERE session = ?',
                          (_sid(session_id),)).fetchone()
    state = {}
    if row is not None:
        try:
            state = json.loads(row[0])
        except ValueError:
            state = {}
    if not isinstance(state, dict):
        state = {}
    for key, value in DEFAULT_STATE.items():
        if isinstance(value, (list, dict)):
            value = type(value)(value)
        state.setdefault(key, value)
    return state


def save(session_id, state):
    conn = _conn()
    with store.transaction(conn):
        conn.execute('INSERT OR REPLACE INTO session_state (session, state) VALUES (?, ?)',
                     (_sid(session_id), json.dumps(state, ensure_ascii=False)))
        store.seen(conn, _sid(session_id))


# ---------------------------------------------------------------- base

def record_base(session_id, root, ref):
    """Persist the first HEAD seen for a session; later calls only keep it alive."""
    if not ref:
        return
    try:
        conn = _conn()
        with store.transaction(conn):
            conn.execute('INSERT OR IGNORE INTO session_base (session, root, ref) VALUES (?, ?, ?)',
                         (_sid(session_id), os.path.abspath(root), str(ref)))
            store.seen(conn, _sid(session_id))
    except Exception:       # noqa: BLE001 -- a tool call outlives us
        pass


def read_base(session_id, root):
    row = _conn().execute('SELECT root, ref FROM session_base WHERE session = ?',
                          (_sid(session_id),)).fetchone()
    if row is None or row[0] != os.path.abspath(root):
        return None
    return row[1] or None


# ---------------------------------------------------------------- bash snapshots

def save_bash_snapshot(session_id, tool_use_id, root, fingerprints, head=None, started=None):
    body = {'root': os.path.abspath(root), 'fingerprints': fingerprints,
            'head': head, 'started': started}
    conn = _conn()
    with store.transaction(conn):
        conn.execute('INSERT OR REPLACE INTO bash_snapshot (session, tool_use_id, body) '
                     'VALUES (?, ?, ?)',
                     (_sid(session_id), str(tool_use_id or 'unknown'),
                      json.dumps(body, ensure_ascii=False)))
        store.seen(conn, _sid(session_id))


def read_bash_snapshot(session_id, tool_use_id, root):
    """{'fingerprints', 'head', 'started'} saved before the Bash call, or None."""
    row = _conn().execute('SELECT body FROM bash_snapshot WHERE session = ? AND tool_use_id = ?',
                          (_sid(session_id), str(tool_use_id or 'unknown'))).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row[0])
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get('root') != os.path.abspath(root):
        return None
    if not isinstance(payload.get('fingerprints'), dict):
        return None
    return payload


def delete_bash_snapshot(session_id, tool_use_id):
    conn = _conn()
    with store.transaction(conn):
        conn.execute('DELETE FROM bash_snapshot WHERE session = ? AND tool_use_id = ?',
                     (_sid(session_id), str(tool_use_id or 'unknown')))


def append_bash_miss(session_id):
    """A Bash call ended without its PreToolUse snapshot: what it changed is
    unknown, which the Stop has to say (R23d)."""
    conn = _conn()
    with store.transaction(conn):
        conn.execute('INSERT INTO bash_miss (session, count) VALUES (?, 1) '
                     'ON CONFLICT(session) DO UPDATE SET count = count + 1', (_sid(session_id),))
        store.seen(conn, _sid(session_id))


def take_bash_misses(session_id):
    """How many Bash calls went uncollected since the last Stop; resets the count."""
    conn = _conn()
    with store.transaction(conn):
        row = conn.execute('SELECT count FROM bash_miss WHERE session = ?',
                           (_sid(session_id),)).fetchone()
        conn.execute('DELETE FROM bash_miss WHERE session = ?', (_sid(session_id),))
    return int(row[0]) if row else 0


# ---------------------------------------------------------------- touched

def append_touched(session_id, relpaths):
    if not relpaths:
        return
    conn = _conn()
    with store.transaction(conn):
        conn.executemany('INSERT INTO touched (session, path) VALUES (?, ?)',
                         [(_sid(session_id), rel) for rel in relpaths])
        store.seen(conn, _sid(session_id))


def read_touched(session_id):
    """Distinct paths in most-recent-touch order."""
    seen = {}
    for (rel,) in _conn().execute('SELECT path FROM touched WHERE session = ? ORDER BY id',
                                  (_sid(session_id),)):
        if rel:
            seen.pop(rel, None)
            seen[rel] = True
    return list(seen)


# ---------------------------------------------------------------- foreign lines
#
# Lines in a touched file the agent did not write, as {line key: count}:
# - baseline: what the file already added over the session base the first time
#   the agent was about to change it. The first record for a file wins, so a
#   later Pre -- after the agent wrote -- never re-baselines its own lines.
# - arrived: lines other people's commits brought in during a Bash call (pull,
#   merge, checkout). These add up.

def append_foreign(session_id, root, counts_by_file, kind='baseline'):
    if not counts_by_file:
        return
    top = os.path.abspath(root)
    conn = _conn()
    with store.transaction(conn):
        conn.executemany(
            'INSERT INTO foreign_lines (session, root, kind, path, lines) VALUES (?, ?, ?, ?, ?)',
            [(_sid(session_id), top, kind, rel, json.dumps(counts, ensure_ascii=False))
             for rel, counts in counts_by_file.items()])
        store.seen(conn, _sid(session_id))


def read_foreign(session_id, root):
    """(files with a baseline, {relpath: {line key: count}})."""
    baselined, counts = set(), {}
    rows = _conn().execute('SELECT kind, path, lines FROM foreign_lines '
                           'WHERE session = ? AND root = ? ORDER BY id',
                           (_sid(session_id), os.path.abspath(root)))
    for kind, rel, raw in rows:
        try:
            lines = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(lines, dict):
            continue
        if kind == 'baseline':
            if rel in baselined:
                continue
            baselined.add(rel)
        merged = counts.setdefault(rel, {})
        for key, n in lines.items():
            if isinstance(n, int) and n > 0:
                merged[key] = merged.get(key, 0) + n
    return baselined, counts


def gc_old_sessions(max_age_days=store.SESSION_MAX_AGE_DAYS):
    try:
        store.gc(max_age_days=max_age_days)
    except Exception:       # noqa: BLE001 -- housekeeping only
        pass
