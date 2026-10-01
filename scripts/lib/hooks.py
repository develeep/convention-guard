"""Collect policy: what the Pre/PostToolUse hooks record.

scripts/collect.py only parses stdin and calls these. The Stop hook is
stop.py (I/O) around decide.py (the decision).
"""

import os
import time

from . import config as configlib, gitdiff, state as statelib
from .candidate import fingerprint
from .paths import git_toplevel, hook_project_dir, repo_relative
from .scope import line_counts

EDIT_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
WATCHED_TOOLS = EDIT_TOOLS | {'Bash'}
# hooks.json also routes MCP tools here; one counts only when the config names
# it under collect.edit_tools, so a read-only MCP call costs a config read (R23e)
MCP_MATCHER = 'mcp__.*'


# ---------------------------------------------------------------- PostToolUse

def _tool_use_key(payload):
    ident = payload.get('tool_use_id')
    if ident:
        return ident
    tool_input = payload.get('tool_input')
    command = tool_input.get('command', '') if isinstance(tool_input, dict) else ''
    return 'command-%s' % fingerprint(command)


def on_pre_tool_use(payload):
    """Before the agent writes, remember what is not its own (R12).

    Every file it is about to touch gets a baseline -- the lines it already
    adds over the session base -- the first time. Bash also snapshots dirty
    files, so the Post can tell which of them the call actually changed.
    """
    root = _watched_root(payload)
    if root is None:
        return None
    session = payload.get('session_id')
    head = gitdiff.current_head(root)
    statelib.record_base(session, root, head or gitdiff.session_base(root))
    base = statelib.read_base(session, root)
    if payload.get('tool_name') != 'Bash':
        _record_baseline(session, root, base, _repo_paths(root, payload.get('tool_input')))
        return None
    # the same baseline the Post compares against, or a file committed
    # mid-session would be missing here and read as changed by this call
    paths = gitdiff.changed_paths(root, base)
    # ponytail: every dirty file is read once per session; a huge untracked
    # tree can eat the 10s budget, and then the call is not collected at all
    _record_baseline(session, root, base, paths)
    fingerprints = {rel: gitdiff.file_fingerprint(root, rel) for rel in paths}
    statelib.save_bash_snapshot(session, _tool_use_key(payload), root, fingerprints,
                                head=head, started=time.time())
    return None


def _watched_root(payload):
    """The work tree root when this tool call is one we collect, else None."""
    if not isinstance(payload, dict):
        return None
    name = str(payload.get('tool_name') or '')
    if name not in WATCHED_TOOLS and not name.startswith('mcp__'):
        return None
    root = git_toplevel(hook_project_dir(payload))
    if name in WATCHED_TOOLS:
        return root
    try:
        named = configlib.load(root).get('collect', {}).get('edit_tools') or ()
    except Exception:       # noqa: BLE001 -- a bad config must not break a tool call
        return None
    return root if name in named else None


def _record_baseline(session, root, base, rels):
    baselined, _ = statelib.read_foreign(session, root)
    todo = [rel for rel in dict.fromkeys(rels) if rel not in baselined]
    if not todo:
        return
    added = gitdiff.added_lines(root, todo, base)
    # a clean file is recorded too: empty, so no later Pre can baseline it
    # after the agent has written to it
    statelib.append_foreign(session, root, {rel: line_counts(added.get(rel, ())) for rel in todo})


def _claim(session, root, rels):
    """A file changed without a baseline (its Pre never ran) keeps every line
    -- as before baselines existed -- and no later Pre may baseline the agent's lines."""
    baselined, _ = statelib.read_foreign(session, root)
    missing = [rel for rel in dict.fromkeys(rels) if rel not in baselined]
    statelib.append_foreign(session, root, {rel: {} for rel in missing})


def _record_arrived(session, root, snapshot, rels):
    """Lines other people's commits brought in during this Bash call are theirs."""
    old, new = snapshot.get('head'), gitdiff.current_head(root)
    if old == new:
        return
    arrived = gitdiff.arrived_lines(root, old, new, snapshot.get('started'), rels)
    statelib.append_foreign(session, root,
                            {rel: line_counts(lines) for rel, lines in arrived.items()},
                            kind='arrived')


def _repo_paths(root, tool_input):
    """The tool's file paths, relative to the work tree; outside it is dropped."""
    found = []
    for raw in _candidate_paths(tool_input):
        rel = repo_relative(raw if os.path.isabs(raw) else os.path.join(root, raw), root)
        if rel is not None:
            found.append(rel)
    return found


def _candidate_paths(tool_input):
    paths = []
    if not isinstance(tool_input, dict):
        return paths
    for key in ('file_path', 'path', 'notebook_path', 'filePath'):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for edit in tool_input.get('edits') or []:
        if isinstance(edit, dict) and isinstance(edit.get('file_path'), str):
            paths.append(edit['file_path'])
    return paths


def on_post_tool_use(payload):
    """Record which files the agent touched. Injects nothing, prints nothing."""
    root = _watched_root(payload)
    if root is None:
        return None
    session = payload.get('session_id')
    statelib.record_base(session, root, gitdiff.session_base(root))
    if payload.get('tool_name') == 'Bash':
        tool_key = _tool_use_key(payload)
        snapshot = statelib.read_bash_snapshot(session, tool_key, root)
        if snapshot is None:
            statelib.append_bash_miss(session)      # said at Stop (R23d)
            return None
        before = snapshot['fingerprints']
        base_ref = statelib.read_base(session, root)
        changed = gitdiff.changed_paths(root, base_ref)
        found = [rel for rel in changed
                 if before.get(rel) != gitdiff.file_fingerprint(root, rel)]
        _record_arrived(session, root, snapshot, found)
        _claim(session, root, found)
        statelib.append_touched(session, found)
        # A missing tool_use_id cannot distinguish identical parallel Bash
        # calls. Keep their shared snapshot until GC so every Post can consume it.
        if payload.get('tool_use_id'):
            statelib.delete_bash_snapshot(session, tool_key)
        return None
    found = _repo_paths(root, payload.get('tool_input'))
    _claim(session, root, found)
    statelib.append_touched(session, found)
    return None
