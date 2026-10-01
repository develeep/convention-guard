"""The edit-event ledger: who wrote each line, recorded as it happens.

For every file the session has seen, the ledger keeps the last content it
observed and, per line, where that line came from:

    p  pre       there when the ledger first saw the file
    a  agent     appeared during one of the agent's tool calls (Pre -> Post)
    o  other     brought in by someone else's commit that a Bash call pulled
    u  unknown   appeared outside any tool call (a person, an editor, a
                 background process) -- not checked, but named at Stop

An uppercase letter also marks a seam: the agent removed lines right after
this one. `^` in front of the string is a seam before line 1. 3.x worked the
same facts out at Stop from `git diff`, by subtracting other people's lines
by text and count; here they are written down as each tool call happens, and
the Stop only reads them (docs/design-4.0.md §1).

Two ways of watching a call:

    file  Write, Edit, MultiEdit, NotebookEdit -- the tool names its paths
    tree  Bash and every MCP tool -- anything in the work tree may change;
          `git status` before and after tells which files did

A Pre with no Post, a Post with no Pre, a change no call explains, a collect
hook that failed: each is recorded as an issue, and the Stop names it
(observation gaps, design §2). Nothing here ever raises into a tool call --
collect.py catches and records.
"""

import difflib
import json
import os
import time
import zlib

from . import observe, store
from .paths import hook_project_dir, repo_relative

PRE, AGENT, OTHER, UNKNOWN = 'p', 'a', 'o', 'u'
SEAM0 = '^'

FILE_TOOLS = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')

# issue kinds, in the order the Stop names them
POST_MISSING = 'post_missing'      # a call's Pre ran, its Post never came; its change is checked
PRE_MISSING = 'pre_missing'        # a Post came with no Pre; what changed is taken as the agent's
UNKNOWN_CHANGE = 'unknown_change'  # changed outside every call; not checked
TREE_FAILED = 'tree_failed'        # git could not say what a Bash/MCP call changed
OUTSIDE = 'outside_root'           # a path outside the work tree
NOT_A_REPO = 'not_a_repo'
COLLECT_ERROR = 'collect_error'    # the collect hook itself failed


# ---------------------------------------------------------------- origins

def apply(old, origins, new, label, pool=None, arrived=None):
    """Origins for `new`, carried over from `old` (a list of lines and its
    origin string, `^` included) by aligning the two.

    - unchanged lines keep their origin
    - a new line takes `label` -- unless the same event removed a line with
      exactly that text (here, or in a file it deleted: `pool`), in which case
      it is a moved line and keeps that line's origin; or it is one of the
      lines someone else's commit brought in (`arrived`, text -> count): `o`
    - where the agent only removed lines -- and did not write them again
      elsewhere, which is a move -- the line before is marked a seam
    """
    seam0, marks = _split(origins)
    n_old, n_new = len(old), len(new)
    lo = 0
    while lo < n_old and lo < n_new and old[lo] == new[lo]:
        lo += 1
    hi = 0
    while hi < n_old - lo and hi < n_new - lo and old[n_old - 1 - hi] == new[n_new - 1 - hi]:
        hi += 1
    a, b, am = old[lo:n_old - hi], new[lo:n_new - hi], marks[lo:n_old - hi]
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if (a or b) else []

    gone = {}
    for text, mark in (pool or ()):
        gone.setdefault(text, []).append(mark.lower())
    for tag, i1, i2, _j1, _j2 in ops:
        if tag in ('delete', 'replace'):
            for k in range(i1, i2):
                gone.setdefault(a[k], []).append(am[k].lower())
    arrived = dict(arrived or {})
    written = {b[k] for tag, _i1, _i2, j1, j2 in ops if tag in ('insert', 'replace')
               for k in range(j1, j2)}

    mid, seams = [], []
    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            mid.extend(am[i1:i2])
            continue
        if tag == 'delete':
            if label == AGENT and any(a[k] not in written for k in range(i1, i2)):
                seams.append(lo + j1 - 1)       # between new lines lo+j1-1 and lo+j1
            continue
        for k in range(j1, j2):
            text = b[k]
            if gone.get(text):
                mid.append(gone[text].pop(0))
            elif arrived.get(text):
                arrived[text] -= 1
                mid.append(OTHER)
            else:
                mid.append(label)
    out = list(marks[:lo]) + mid + list(marks[n_old - hi:])
    for index in seams:
        if index < 0:
            seam0 = True
        elif index < len(out):
            out[index] = out[index].upper()
    return (SEAM0 if seam0 else '') + ''.join(out)


def _split(origins):
    origins = origins or ''
    if origins.startswith(SEAM0):
        return True, list(origins[1:])
    return False, list(origins)


def marks_of(origins):
    return _split(origins)[1]


def pool_of(entry):
    """What a deleted file leaves for the event's new files: (text, origin) pairs."""
    if not entry or not entry.lines:
        return []
    return list(zip(entry.lines, marks_of(entry.origins)))


# ---------------------------------------------------------------- one file

class Entry:
    """What the ledger knows about one file."""

    __slots__ = ('path', 'exists', 'lines', 'origins', 'sig', 'flag', 'first_absent', 'created',
                 'touched')

    def __init__(self, path, exists=False, lines=None, origins='', sig=None, flag=None,
                 first_absent=False, created=False, touched=False):
        self.path, self.exists, self.lines, self.origins = path, exists, lines, origins
        self.sig, self.flag = sig, flag
        self.first_absent, self.created, self.touched = first_absent, created, touched

    @classmethod
    def first(cls, rel, snap):
        """The first sight of a file: every line is `p`."""
        lines = snap.lines if snap.exists else None
        return cls(rel, snap.exists, lines, PRE * len(lines or ()), snap.sig, snap.flag,
                   first_absent=not snap.exists)

    def agent_lines(self):
        return [(i + 1, line) for i, (line, mark) in
                enumerate(zip(self.lines or (), marks_of(self.origins))) if mark.lower() == AGENT]

    def seams(self):
        seam0, marks = _split(self.origins)
        found = {i + 1 for i, mark in enumerate(marks) if mark.isupper()}
        return found | ({0} if seam0 else set())

    def owned(self):
        """Is there anything in this file the agent answers for?"""
        return self.exists and (self.created or bool(self.agent_lines()) or bool(self.seams())
                                or (self.touched and self.flag == 'too_large'))

    def update(self, snap, label, pool=None, arrived=None):
        """Bring the entry to `snap`, attributing what changed to `label`.
        True when the content changed."""
        before = (self.exists, self.lines)
        if not snap.exists:
            self.exists, self.lines, self.origins, self.sig, self.flag = False, None, '', None, None
        elif snap.lines is None:                    # too large, binary, unreadable
            self.exists, self.lines, self.origins = True, None, ''
            self.sig, self.flag = snap.sig, snap.flag
        else:
            old = self.lines if (self.exists and self.lines is not None) else []
            origins = self.origins if (self.exists and self.lines is not None) else ''
            born = not self.exists
            self.origins = apply(old, origins, snap.lines, label,
                                 pool=pool if born else None, arrived=arrived)
            # a file the agent wrote into being -- not one it only moved here
            if born and self.first_absent and label == AGENT and AGENT in self.origins.lower():
                self.created = True
            self.exists, self.lines, self.sig, self.flag = True, snap.lines, snap.sig, None
        if label == AGENT:
            self.touched = True
        return before != (self.exists, self.lines)


def _pack(lines):
    return zlib.compress('\n'.join(lines).encode('utf-8')) if lines is not None else None


def _unpack(blob, count):
    if blob is None:
        return None
    if count == 0:
        return []
    return zlib.decompress(blob).decode('utf-8').split('\n')


def _load(conn, session, root, rel):
    row = conn.execute(
        'SELECT exists_, content, origins, sig, flag, first_absent, created, touched '
        'FROM ledger_file WHERE session = ? AND root = ? AND path = ?',
        (session, root, rel)).fetchone()
    return _entry(rel, row) if row else None


def _entry(rel, row):
    exists, content, origins, sig, flag, first_absent, created, touched = row
    seam0, marks = _split(origins)
    return Entry(rel, bool(exists), _unpack(content, len(marks)), origins, sig, flag,
                 bool(first_absent), bool(created), bool(touched))


def load_all(conn, session, root):
    rows = conn.execute(
        'SELECT path, exists_, content, origins, sig, flag, first_absent, created, touched '
        'FROM ledger_file WHERE session = ? AND root = ?', (session, root))
    return {row[0]: _entry(row[0], row[1:]) for row in rows}


def _save(conn, session, root, entry):
    conn.execute(
        'INSERT OR REPLACE INTO ledger_file (session, root, path, exists_, content, origins, sig, '
        'flag, first_absent, created, touched) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (session, root, entry.path, int(entry.exists), _pack(entry.lines), entry.origins,
         entry.sig, entry.flag, int(entry.first_absent), int(entry.created), int(entry.touched)))


def issue(conn, session, root, kind, path='', detail=''):
    conn.execute('INSERT INTO observe_issue (session, root, kind, path, detail, at) '
                 'VALUES (?, ?, ?, ?, ?, ?)', (session, root or '', kind, path, detail, time.time()))


def record_failure(payload, code):
    """collect.py's last word: its own failure goes where the Stop will read it."""
    try:
        session = str((payload or {}).get('session_id') or 'unknown')
        conn = store.connect()
        with store.transaction(conn):
            issue(conn, session, '', COLLECT_ERROR, detail=code)
            store.seen(conn, session)
    except Exception:       # noqa: BLE001 -- nothing left to tell
        pass


# ---------------------------------------------------------------- the collect hook

def collect(payload):
    if not isinstance(payload, dict):
        return
    tool = str(payload.get('tool_name') or '')
    kind = 'file' if tool in FILE_TOOLS else (
        'tree' if tool == 'Bash' or tool.startswith('mcp__') else None)
    if kind is None:
        return
    session = str(payload.get('session_id') or 'unknown')
    root = observe.toplevel(hook_project_dir(payload))
    conn = store.connect()
    if root is None:
        _not_a_repo(conn, session, hook_project_dir(payload))
        return
    key = _event_key(payload, tool)
    pre = payload.get('hook_event_name') == 'PreToolUse'
    if kind == 'file':
        rels, outside = _paths(root, payload.get('tool_input'))
        with store.transaction(conn):
            _ensure_session(conn, session, root)
            for raw in outside:
                issue(conn, session, root, OUTSIDE, raw)
            if pre:
                _file_pre(conn, session, root, key, tool, rels)
            else:
                _file_post(conn, session, root, key, rels)
            store.seen(conn, session)
        return
    status = observe.status(root)
    with store.transaction(conn):
        _ensure_session(conn, session, root, status)
        if status is None:
            issue(conn, session, root, TREE_FAILED, detail=tool)
        elif pre:
            _tree_pre(conn, session, root, key, tool, status)
        else:
            event = _take_event(conn, session, key)
            _tree_apply(conn, session, root, event, status, PRE_MISSING if event is None else None)
        store.seen(conn, session)


def _event_key(payload, tool):
    ident = payload.get('tool_use_id')
    if ident:
        return str(ident)
    # without an id, Pre and Post of one call still describe the same input
    raw = json.dumps(payload.get('tool_input'), sort_keys=True, default=str)
    return 'noid-%s-%x' % (tool, zlib.crc32(raw.encode('utf-8')))


def _paths(root, tool_input):
    """(repo-relative paths, paths outside the work tree) the tool names."""
    found, outside = [], []
    if not isinstance(tool_input, dict):
        return found, outside
    raws = [tool_input.get(key) for key in ('file_path', 'path', 'notebook_path', 'filePath')]
    raws += [e.get('file_path') for e in tool_input.get('edits') or [] if isinstance(e, dict)]
    for raw in raws:
        if not isinstance(raw, str) or not raw:
            continue
        rel = repo_relative(raw if os.path.isabs(raw) else os.path.join(root, raw), root)
        if rel is None:
            outside.append(raw)
        elif not observe.skipped(rel) and rel not in found:
            found.append(rel)
    return found, outside


def _not_a_repo(conn, session, cwd):
    with store.transaction(conn):
        seen = conn.execute('SELECT 1 FROM observe_issue WHERE session = ? AND kind = ?',
                            (session, NOT_A_REPO)).fetchone()
        if not seen:
            issue(conn, session, cwd, NOT_A_REPO, cwd)
        store.seen(conn, session)


def _ensure_session(conn, session, root, status=None):
    """The first event of a session remembers which paths were already dirty
    and how they looked, so a later change to one of them that no tool call
    explains can be named."""
    row = conn.execute('SELECT 1 FROM ledger_session WHERE session = ? AND root = ?',
                       (session, root)).fetchone()
    if row:
        return
    if status is None:
        status = observe.status(root)
    tree = (status or (None, {}))[1]
    conn.execute('INSERT INTO ledger_session (session, root, tree) VALUES (?, ?, ?)',
                 (session, root, json.dumps(tree)))


def _open_event(conn, session, key, root, tool, kind, paths=(), head=None):
    conn.execute('INSERT OR REPLACE INTO ledger_event (session, tool_use_id, root, tool, kind, '
                 'started, head, paths) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                 (session, key, root, tool, kind, time.time(), head, json.dumps(list(paths))))


def _take_event(conn, session, key):
    row = conn.execute('SELECT root, tool, kind, started, head, paths FROM ledger_event '
                       'WHERE session = ? AND tool_use_id = ?', (session, key)).fetchone()
    if row is None:
        return None
    conn.execute('DELETE FROM ledger_event WHERE session = ? AND tool_use_id = ?', (session, key))
    return {'root': row[0], 'tool': row[1], 'kind': row[2], 'started': row[3], 'head': row[4],
            'paths': json.loads(row[5] or '[]')}


def _catch_up(conn, session, root, entry):
    """Before a call starts, a file that changed since we last looked changed
    outside every call: `u`, and named."""
    snap = observe.read(root, entry.path)
    if entry.update(snap, UNKNOWN):
        issue(conn, session, root, UNKNOWN_CHANGE, entry.path)
    else:
        entry.sig = snap.sig                # touched, not changed
    _save(conn, session, root, entry)


def _file_pre(conn, session, root, key, tool, rels):
    for rel in rels:
        entry = _load(conn, session, root, rel)
        if entry is None:
            _save(conn, session, root, Entry.first(rel, observe.read(root, rel)))
        elif observe.signature(root, rel) != entry.sig:
            _catch_up(conn, session, root, entry)
    _open_event(conn, session, key, root, tool, 'file', rels)


def _file_post(conn, session, root, key, rels):
    event = _take_event(conn, session, key)
    for rel in rels:
        entry = _load(conn, session, root, rel)
        if entry is not None and observe.signature(root, rel) == entry.sig:
            continue
        if entry is None:
            # no Pre ever saw it: the best "before" is what git has
            head = observe.blobs(root, 'HEAD', [rel]).get(rel)
            entry = Entry.first(rel, observe.Snapshot(head is not None, head))
        if entry.update(observe.read(root, rel), AGENT) and event is None:
            issue(conn, session, root, PRE_MISSING, rel)
        _save(conn, session, root, entry)


def _tree_pre(conn, session, root, key, tool, status):
    head, dirty = status
    entries = load_all(conn, session, root)
    for rel, entry in entries.items():
        if observe.signature(root, rel) != entry.sig:
            _catch_up(conn, session, root, entry)
    for rel in dirty:
        if rel not in entries:
            # dirty before the agent's call: whatever is in it is not the agent's
            _save(conn, session, root, Entry.first(rel, observe.read(root, rel)))
    _forget_tree(conn, session, root, dirty)
    _open_event(conn, session, key, root, tool, 'tree', head=head)


def _forget_tree(conn, session, root, rels):
    """Paths the ledger now follows leave the session's dirty-path memory."""
    row = conn.execute('SELECT tree FROM ledger_session WHERE session = ? AND root = ?',
                       (session, root)).fetchone()
    tree = json.loads(row[0]) if row and row[0] else {}
    left = {k: v for k, v in tree.items() if k not in rels}
    if left != tree:
        conn.execute('UPDATE ledger_session SET tree = ? WHERE session = ? AND root = ?',
                     (json.dumps(left), session, root))


def _tree_apply(conn, session, root, event, status, issue_kind):
    """After a Bash or MCP call (or for one whose Post never came): every file
    that is not what the ledger last saw changed during the call."""
    from . import gitdiff
    head_now, dirty = status
    entries = load_all(conn, session, root)
    old_head = (event or {}).get('head') or head_now
    changed = {rel: entry for rel, entry in entries.items()
               if observe.signature(root, rel) != entry.sig}
    fresh = [rel for rel in dirty if rel not in entries]
    if old_head and head_now and old_head != head_now:
        fresh += [rel for rel in observe.changed_between(root, old_head, head_now)
                  if rel not in entries and rel not in fresh]
    before = observe.blobs(root, old_head, fresh) if fresh else {}
    for rel in fresh:
        lines = before.get(rel)
        changed[rel] = Entry.first(rel, observe.Snapshot(lines is not None, lines))
    if not changed:
        return
    arrived = {}
    if event and old_head and head_now and old_head != head_now:
        for rel, lines in gitdiff.arrived_lines(root, old_head, head_now, event.get('started'),
                                                sorted(changed)).items():
            counts = arrived.setdefault(rel, {})
            for _n, text in lines:
                counts[text] = counts.get(text, 0) + 1
    snaps = {rel: observe.read(root, rel) for rel in changed}
    pool = [pair for rel, entry in changed.items() if not snaps[rel].exists
            for pair in pool_of(entry)]
    for rel, entry in changed.items():
        if entry.update(snaps[rel], AGENT, pool=pool, arrived=arrived.get(rel)) and issue_kind:
            issue(conn, session, root, issue_kind, rel)
        _save(conn, session, root, entry)
    _forget_tree(conn, session, root, set(changed))


# ---------------------------------------------------------------- the Stop

class StopLedger:
    """What the Stop takes from the ledger: the files the agent answers for,
    and every observation gap since the last Stop."""

    def __init__(self, entries=(), issues=()):
        self.entries = list(entries)
        self.issues = list(issues)          # [(kind, path, detail)]

    def owned(self):
        return [e for e in self.entries if e.owned()]


def take_issues(conn, session):
    rows = conn.execute('SELECT kind, path, detail FROM observe_issue WHERE session = ? '
                        'ORDER BY id', (session,)).fetchall()
    conn.execute('DELETE FROM observe_issue WHERE session = ?', (session,))
    return [tuple(r) for r in rows]


def at_stop(session, root):
    """Settle the ledger for a Stop and hand back what it owns.

    1. a call whose Post never came: what changed is the agent's, and said
    2. a file that changed outside every call: `u`, and said
    3. a dirty path the ledger does not follow that changed since the last
       Stop: said
    """
    session = str(session or 'unknown')
    conn = store.connect()
    with store.transaction(conn):
        if root is None:
            return StopLedger(issues=take_issues(conn, session))
        known = conn.execute('SELECT tree FROM ledger_session WHERE session = ? AND root = ?',
                             (session, root)).fetchone()
        if known is None:
            return StopLedger(issues=take_issues(conn, session))
        stranded = conn.execute('SELECT tool_use_id FROM ledger_event WHERE session = ? '
                                'AND root = ?', (session, root)).fetchall()
        status = observe.status(root)
        for (key,) in stranded:
            event = _take_event(conn, session, key)
            if event['kind'] == 'file':
                _file_stranded(conn, session, root, event)
            elif status is not None:
                _tree_apply(conn, session, root, event, status, POST_MISSING)
            else:                           # what it changed cannot be known now
                issue(conn, session, root, TREE_FAILED, detail=event['tool'])
        for entry in load_all(conn, session, root).values():
            if observe.signature(root, entry.path) != entry.sig:
                _catch_up(conn, session, root, entry)
        if status is not None:
            _tree_since(conn, session, root, status[1], json.loads(known[0] or '{}'))
        entries = load_all(conn, session, root).values()
        store.seen(conn, session)
        return StopLedger(entries, take_issues(conn, session))


def _file_stranded(conn, session, root, event):
    for rel in event['paths']:
        entry = _load(conn, session, root, rel)
        if entry is None or observe.signature(root, rel) == entry.sig:
            continue                        # never ran (denied, blocked): nothing to say
        if entry.update(observe.read(root, rel), AGENT):
            issue(conn, session, root, POST_MISSING, rel)
        _save(conn, session, root, entry)


def _tree_since(conn, session, root, dirty, tree):
    followed = {row[0] for row in conn.execute(
        'SELECT path FROM ledger_file WHERE session = ? AND root = ?', (session, root))}
    now = {rel: sig for rel, sig in dirty.items() if rel not in followed}
    for rel, sig in now.items():
        if tree.get(rel) != sig:
            issue(conn, session, root, UNKNOWN_CHANGE, rel)
    conn.execute('UPDATE ledger_session SET tree = ? WHERE session = ? AND root = ?',
                 (json.dumps(now), session, root))


def refresh(session, root, rels, label=AGENT):
    """Files the Stop itself rewrote (auto-fix) are brought up to date: the
    fix is made on the agent's behalf, so its lines are the agent's."""
    conn = store.connect()
    with store.transaction(conn):
        for rel in rels:
            entry = _load(conn, session, root, rel) or Entry.first(rel, observe.ABSENT)
            entry.update(observe.read(root, rel), label)
            _save(conn, session, root, entry)
        return list(load_all(conn, session, root).values())
