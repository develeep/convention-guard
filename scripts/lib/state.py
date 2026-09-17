"""Per-session state kept between hook invocations.

Two stores with different write patterns:

- touched-<session>.txt: append-only list of paths the agent edited. The
  PostToolUse hook can run several times in parallel, and a read-modify-write
  JSON file loses entries when two of them interleave. Appending one short
  line per path does not.
- session-<session>.json: everything else, written only by the Stop hook,
  which Claude Code runs one at a time per session.
"""

import json
import os
import time

from .paths import atomic_write, data_dir, safe_name

TOUCHED_CAP = 500
VERSION = 2

DEFAULT_STATE = {
    'version': VERSION,
    'consecutive_blocks': 0,   # blocks in a row without a clean turn (loop guard)
    'blocks': 0,
    'fired_rules': [],         # rules whose findings were fixed this session (once_per_session)
    'cycle': None,             # the open verification cycle, if any (see cycle.py)
    'unresolved': [],          # candidate keys a closed cycle left unfixed
    'closed_in_continuation': False,
}


def state_path(session_id, kind=''):
    suffix = '-%s' % safe_name(kind) if kind else ''
    return os.path.join(data_dir(),
                        'session-%s%s.json' % (safe_name(session_id or 'unknown'), suffix))


def load(session_id, kind=''):
    path = state_path(session_id, kind)
    state = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
    if not isinstance(state, dict) or (not kind and state.get('version') != VERSION):
        state = {}          # a pre-1.0 session file: start clean rather than misread it
    for key, value in DEFAULT_STATE.items():
        if isinstance(value, (list, dict)):
            value = type(value)(value)
        state.setdefault(key, value)
    return state


def save(session_id, state, kind=''):
    atomic_write(state_path(session_id, kind),
                 json.dumps(state, ensure_ascii=False))


# ---------------------------------------------------------------- touched queue

def touched_path(session_id):
    return os.path.join(data_dir(), 'touched-%s.txt' % safe_name(session_id or 'unknown'))


def append_touched(session_id, relpaths):
    if not relpaths:
        return
    try:
        with open(touched_path(session_id), 'a', encoding='utf-8') as fh:
            fh.write(''.join('%s\n' % rel for rel in relpaths))
    except OSError:
        pass


def read_touched(session_id):
    """Distinct paths in first-touched order, capped to the most recent ones."""
    try:
        with open(touched_path(session_id), 'r', encoding='utf-8') as fh:
            lines = [line.rstrip('\n') for line in fh]
    except OSError:
        return []
    seen = {}
    for rel in lines:
        if rel:
            seen.pop(rel, None)
            seen[rel] = True
    return list(seen)[-TOUCHED_CAP:]


def clear_touched(session_id, keep=()):
    path = touched_path(session_id)
    if keep:
        atomic_write(path, ''.join('%s\n' % rel for rel in keep))
    else:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- housekeeping

def gc_old_sessions(max_age_days=7):
    cutoff = time.time() - max_age_days * 86400
    try:
        base = data_dir()
        for name in os.listdir(base):
            if not name.startswith(('session-', 'touched-')):
                continue
            full = os.path.join(base, name)
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
    except OSError:
        pass
