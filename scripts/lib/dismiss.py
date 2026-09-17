"""Findings the team looked at and called false positives.

The hook tells the agent "if it is a false positive, do not fix it -- say why".
That sentence used to go nowhere: the reason lived in the chat and the log kept
only `fixed: false`, indistinguishable from "the agent ignored us". So the fix
rate -- the one number the tuning cycle runs on -- conflated two opposite
things.

A dismissal is recorded in the repo, next to the rules it is about:

    <repo>/.claude/convention-rules/dismissed.yaml

    dismissed:
      - rule: core/php-line-too-long
        file: app/Http/Controllers/OrderController.php
        hash: 6f1c93ab24            # fingerprint of the dismissed snippet
        reason: "라라벨 체이닝이라 끊으면 가독성이 더 나빠짐"
        at: 2026-09-16

The fingerprint is of the code, not the line number, so the suppression
survives edits above it and expires the moment the line itself changes -- a
rewritten line is a new decision. Omit `hash` to dismiss a rule for a whole
file.
"""

import json
import os
import time

from .candidate import fingerprint  # noqa: F401  (re-exported)
from .rules import repo_dir
from .yamlio import read as read_yaml

FILENAME = 'dismissed.yaml'


def path(root):
    return os.path.join(repo_dir(root), FILENAME)


def load(root):
    """Returns (keys, entries).

    keys holds `(rule_id, file, hash)` for exact dismissals and
    `(rule_id, file)` for file-wide ones, which is what Context matches on.
    """
    target = path(root)
    if not os.path.isfile(target):
        return frozenset(), []
    try:
        data = read_yaml(target) or {}
    except Exception:
        return frozenset(), []
    entries = data.get('dismissed') or []
    if isinstance(entries, dict):
        entries = [entries]
    keys, kept = set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rule_id = str(entry.get('rule') or '').strip()
        relpath = str(entry.get('file') or '').strip().replace(os.sep, '/')
        if not rule_id or not relpath:
            continue
        digest = entry.get('hash')
        if digest:
            keys.add((rule_id, relpath, str(digest).strip()))
        else:
            keys.add((rule_id, relpath))
        kept.append(entry)
    return frozenset(keys), kept


def predicate(keys):
    """is_dismissed(rule_id, relpath, digest) over the keys load() returned."""
    def is_dismissed(rule_id, relpath, digest):
        return (rule_id, relpath) in keys or (rule_id, relpath, digest) in keys
    return is_dismissed


def _yaml_line(key, value):
    # json.dumps produces a double-quoted scalar that both PyYAML and the
    # bundled parser read back identically, including Korean text and colons.
    return '%s: %s' % (key, json.dumps(str(value), ensure_ascii=False))


def append(root, rule_id, relpath, snippet, reason, line=None):
    """Add one dismissal. Returns the fingerprint that was written."""
    target = path(root)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    digest = fingerprint(snippet)
    block = ['  - %s' % _yaml_line('rule', rule_id),
             '    %s' % _yaml_line('file', relpath),
             '    %s' % _yaml_line('hash', digest),
             '    %s' % _yaml_line('reason', reason),
             '    %s' % _yaml_line('at', time.strftime('%Y-%m-%d'))]
    if line:
        block.append('    # %s:%s  %s' % (relpath, line, ' '.join(str(snippet).split())[:100]))
    exists = os.path.isfile(target)
    with open(target, 'a', encoding='utf-8') as fh:
        if not exists:
            fh.write('# convention-guard: 오탐으로 판단해 넘긴 지적들.\n'
                     '# hash 는 넘긴 코드의 지문입니다. 그 줄이 바뀌면 다시 지적됩니다.\n'
                     'dismissed:\n')
        fh.write('\n'.join(block) + '\n')
    return digest


def append_whole_file(root, rule_id, relpath, reason):
    """Turn a rule off for one file. No fingerprint, so it does not expire."""
    target = path(root)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    block = ['  - %s' % _yaml_line('rule', rule_id),
             '    %s' % _yaml_line('file', relpath),
             '    %s' % _yaml_line('reason', reason),
             '    %s' % _yaml_line('at', time.strftime('%Y-%m-%d'))]
    exists = os.path.isfile(target)
    with open(target, 'a', encoding='utf-8') as fh:
        if not exists:
            fh.write('# convention-guard: 오탐으로 판단해 넘긴 지적들.\n'
                     '# hash 가 있으면 그 코드가 바뀔 때 다시 지적되고, 없으면 파일 전체입니다.\n'
                     'dismissed:\n')
        fh.write('\n'.join(block) + '\n')
