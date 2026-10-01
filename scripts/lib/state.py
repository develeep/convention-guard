"""The Stop hook's own memory between turns: the verification cycle and its
counters (decide.DEFAULT_STATE), one row per session in the store.

Who wrote which line is not here -- that is the edit ledger (ledger.py).
"""

import json

from . import decide, store


def _sid(session_id):
    return str(session_id or 'unknown')


def load(session_id):
    row = store.connect().execute('SELECT state FROM session_state WHERE session = ?',
                                  (_sid(session_id),)).fetchone()
    state = {}
    if row is not None:
        try:
            state = json.loads(row[0])
        except ValueError:
            state = {}
    return decide.normalized(state if isinstance(state, dict) else {})


def save(session_id, state):
    conn = store.connect()
    with store.transaction(conn):
        conn.execute('INSERT OR REPLACE INTO session_state (session, state) VALUES (?, ?)',
                     (_sid(session_id), json.dumps(state, ensure_ascii=False)))
        store.seen(conn, _sid(session_id))


def gc_old_sessions(max_age_days=store.SESSION_MAX_AGE_DAYS):
    try:
        store.gc(max_age_days=max_age_days)
    except Exception:       # noqa: BLE001 -- housekeeping only
        pass
