"""Per-session state kept between hook invocations.

Two stores with different write patterns:

- touched-<session>.txt: append-only list of paths the agent edited. The
  PostToolUse hook can run several times in parallel, and a read-modify-write
  JSON file loses entries when two of them interleave. Appending one short
  line per path does not.
- foreign-<session>.jsonl: append-only, lines in touched files the agent did
  not write (see "foreign lines" below).
- session-<session>.json: everything else, written only by the Stop hook,
  which Claude Code runs one at a time per session.
"""

import json
import os
import time

from .paths import atomic_write, data_dir, safe_name

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


def base_path(session_id):
    return os.path.join(data_dir(), 'base-%s.json' % safe_name(session_id or 'unknown'))


def record_base(session_id, root, ref):
    """Persist the first HEAD seen for a session without a racy read-modify-write."""
    if not ref:
        return
    path = base_path(session_id)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump({'root': os.path.abspath(root), 'ref': str(ref)}, fh)
    except FileExistsError:
        # a live session: keep its files out of the 7-day GC (R23c)
        for kept in (path, foreign_path(session_id)):
            try:
                os.utime(kept)
            except OSError:
                pass
    except OSError:
        pass


def read_base(session_id, root):
    try:
        with open(base_path(session_id), 'r', encoding='utf-8') as fh:
            value = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('root') != os.path.abspath(root):
        return None
    ref = value.get('ref')
    return str(ref) if ref else None


def bash_snapshot_path(session_id, tool_use_id):
    return os.path.join(data_dir(), 'bash-%s-%s.json'
                        % (safe_name(session_id or 'unknown'),
                           safe_name(tool_use_id or 'unknown')))


def save_bash_snapshot(session_id, tool_use_id, root, fingerprints, head=None, started=None):
    payload = {'root': os.path.abspath(root), 'fingerprints': fingerprints,
               'head': head, 'started': started}
    atomic_write(bash_snapshot_path(session_id, tool_use_id),
                 json.dumps(payload, ensure_ascii=False))


def read_bash_snapshot(session_id, tool_use_id, root):
    """{'fingerprints', 'head', 'started'} saved before the Bash call, or None."""
    path = bash_snapshot_path(session_id, tool_use_id)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get('root') != os.path.abspath(root):
        return None
    if not isinstance(payload.get('fingerprints'), dict):
        return None
    return payload


def delete_bash_snapshot(session_id, tool_use_id):
    try:
        os.remove(bash_snapshot_path(session_id, tool_use_id))
    except OSError:
        pass


def append_touched(session_id, relpaths):
    if not relpaths:
        return
    try:
        with open(touched_path(session_id), 'a', encoding='utf-8') as fh:
            fh.write(''.join('%s\n' % rel for rel in relpaths))
    except OSError:
        pass


# ---------------------------------------------------------------- foreign lines
#
# Lines in a touched file the agent did not write, as {line key: count}:
# - baseline: what the file already added over the session base the first time
#   the agent was about to change it. The first record for a file wins, so a
#   later Pre -- after the agent wrote -- never re-baselines its own lines.
# - arrived: lines other people's commits brought in during a Bash call (pull,
#   merge, checkout). These add up.
# Append-only for the same reason as the touched queue: Pre and Post hooks of
# parallel tool calls write here concurrently.

def foreign_path(session_id):
    return os.path.join(data_dir(), 'foreign-%s.jsonl' % safe_name(session_id or 'unknown'))


def append_foreign(session_id, root, counts_by_file, kind='baseline'):
    if not counts_by_file:
        return
    top = os.path.abspath(root)
    rows = ''.join(json.dumps({'root': top, 'kind': kind, 'file': rel, 'lines': counts},
                              ensure_ascii=False) + '\n'
                   for rel, counts in counts_by_file.items())
    try:
        with open(foreign_path(session_id), 'a', encoding='utf-8') as fh:
            fh.write(rows)
    except OSError:
        pass


def _foreign_rows(session_id, root):
    """(kind, relpath, {line key: count}) for this root, skipping torn writes."""
    top = os.path.abspath(root)
    try:
        with open(foreign_path(session_id), 'r', encoding='utf-8') as fh:
            raws = fh.readlines()
    except OSError:
        return
    for raw in raws:
        try:
            row = json.loads(raw)
        except ValueError:
            continue            # a hook killed mid-write
        if (isinstance(row, dict) and row.get('root') == top
                and isinstance(row.get('file'), str) and isinstance(row.get('lines'), dict)):
            yield row.get('kind'), row['file'], row['lines']


def read_foreign(session_id, root):
    """(files with a baseline, {relpath: {line key: count}})."""
    baselined, counts = set(), {}
    for kind, rel, lines in _foreign_rows(session_id, root):
        if kind == 'baseline':
            if rel in baselined:
                continue
            baselined.add(rel)
        merged = counts.setdefault(rel, {})
        for key, n in lines.items():
            if isinstance(n, int) and n > 0:
                merged[key] = merged.get(key, 0) + n
    return baselined, counts


def read_touched(session_id):
    """Distinct paths in most-recent-touch order without dropping session files."""
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
    return list(seen)


# ---------------------------------------------------------------- housekeeping

def bash_miss_path(session_id):
    return os.path.join(data_dir(), 'bashmiss-%s.txt' % safe_name(session_id or 'unknown'))


def append_bash_miss(session_id):
    """A Bash call ended without its PreToolUse snapshot: what it changed is
    unknown, which the Stop has to say (R23d). Append-only, like touched."""
    try:
        with open(bash_miss_path(session_id), 'a', encoding='utf-8') as fh:
            fh.write('x\n')
    except OSError:
        pass


def take_bash_misses(session_id):
    """How many Bash calls went uncollected since the last Stop; resets the count."""
    path = bash_miss_path(session_id)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            count = sum(1 for line in fh if line.strip())
        os.remove(path)
    except OSError:
        return 0
    return count


def gc_old_sessions(max_age_days=7):
    cutoff = time.time() - max_age_days * 86400
    try:
        base = data_dir()
        for name in os.listdir(base):
            if not name.startswith(('session-', 'touched-', 'base-', 'bash-', 'foreign-',
                                    'bashmiss-')):
                continue
            full = os.path.join(base, name)
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
    except OSError:
        pass
