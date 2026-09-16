#!/usr/bin/env python3
"""PostToolUse hook: record which files the agent touched. Injects nothing.

Cost is a few milliseconds and zero context. The queue is what makes the Stop
check precise -- `git diff` alone also picks up the human's own edits and
misses anything the agent committed mid-session.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.paths import (load_state, project_dir,  # noqa: E402
                       remember_plugin_root, save_state)

WATCHED = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'str_replace_editor'}


def candidate_paths(tool_input):
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


def main():
    remember_plugin_root()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get('tool_name') not in WATCHED:
        return 0

    root = project_dir(payload.get('cwd'))
    found = []
    for raw in candidate_paths(payload.get('tool_input')):
        absolute = raw if os.path.isabs(raw) else os.path.join(root, raw)
        absolute = os.path.abspath(absolute)
        try:
            rel = os.path.relpath(absolute, root)
        except ValueError:
            continue
        if rel.startswith('..'):
            continue  # outside the project; not ours to check
        found.append(rel.replace(os.sep, '/'))

    if not found:
        return 0

    session = payload.get('session_id')
    state = load_state(session)
    touched = state.get('touched') or []
    for rel in found:
        if rel not in touched:
            touched.append(rel)
    state['touched'] = touched[-500:]
    save_state(session, state)
    return 0


if __name__ == '__main__':
    sys.exit(main())
