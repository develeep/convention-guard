"""Findings the team looked at and called false positives.

A dismissal is recorded in the repo, next to the rules it is about, and is
meant to be committed:

    <repo>/.claude/convention-guard/dismissed.yaml

    dismissed:
      - rule: "core/php-line-too-long"
        file: "app/Http/Controllers/OrderController.php"
        hash: "6f1c93ab24"              # fingerprint of the dismissed code
        reason: "체이닝을 끊으면 가독성이 더 나빠짐"
        by: "agent"                      # agent | human
        at: "2026-09-16"

The fingerprint is of the code, not the line number, so the suppression
survives edits above it and expires the moment the line itself changes -- a
rewritten line is a new decision. Omit `hash` to dismiss a rule for a whole
file.

This file is a team artifact, so it is never rewritten wholesale (comments in
it are the team's) and never silently ignored: a file that does not parse is
an error every entry point reports, because treating it as empty would bring
back every finding the team already declined.
"""

import os
import re
import time

from .rules import repo_dir
from .yamlio import load as yaml_load, scalar

FILENAME = 'dismissed.yaml'
HEADER = ('# convention-guard: 오탐으로 판단해 넘긴 지적들. 커밋해서 팀과 공유하세요.\n'
          '# hash 는 넘긴 코드의 지문입니다. 그 코드가 바뀌면 다시 지적됩니다.\n'
          '# hash 가 없는 항목은 그 파일 전체에서 규칙을 끕니다.\n')


class DismissalError(Exception):
    pass


class Dismissals:
    def __init__(self, keys=frozenset(), entries=(), error=None, path=None):
        self.keys = keys          # {(rule, file, hash)} and {(rule, file)}
        self.entries = list(entries)
        self.error = error
        self.path = path

    def __len__(self):
        return len(self.entries)

    def is_dismissed(self, rule_id, relpath, digest):
        return (rule_id, relpath) in self.keys or (rule_id, relpath, digest) in self.keys

    def has(self, rule_id, relpath, digest=None):
        return (rule_id, relpath, digest) in self.keys if digest else \
            (rule_id, relpath) in self.keys


def path(root):
    return os.path.join(repo_dir(root), FILENAME)


def load(root):
    target = path(root)
    if not os.path.isfile(target):
        return Dismissals(path=target)
    try:
        with open(target, 'r', encoding='utf-8') as fh:
            text = fh.read()
    except OSError as exc:
        return Dismissals(error='%s 를 읽을 수 없습니다: %s' % (target, exc), path=target)
    if not text.strip():
        return Dismissals(path=target)
    try:
        data = yaml_load(text) or {}
    except Exception as exc:
        return Dismissals(error='%s 파싱 실패 — 기각 기록을 적용할 수 없습니다: %s'
                          % (target, exc), path=target)
    if not isinstance(data, dict):
        return Dismissals(error='%s: 최상위가 매핑이 아닙니다' % target, path=target)
    entries = data.get('dismissed') or []
    if isinstance(entries, dict):
        entries = [entries]
    keys, kept = set(), []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        rule_id = str(entry.get('rule') or '').strip()
        relpath = str(entry.get('file') or '').strip().replace(os.sep, '/')
        if not rule_id or not relpath:
            continue
        digest = entry.get('hash')
        keys.add((rule_id, relpath, str(digest).strip()) if digest else (rule_id, relpath))
        kept.append(entry)
    return Dismissals(frozenset(keys), kept, path=target)


def predicate(dismissals):
    """is_dismissed(rule_id, relpath, digest) for the detectors."""
    return dismissals.is_dismissed


def add(root, rule_id, relpath, reason, digest=None, snippet=None, line=None, by='human'):
    """Append one dismissal. Returns False when it is already recorded.

    Appends rather than rewrites, so the team's comments survive. Refuses to
    touch a file that does not parse -- appending to it would only bury the
    problem under more entries.
    """
    current = load(root)
    if current.error:
        raise DismissalError(current.error)
    if current.has(rule_id, relpath, digest):
        return False
    target = path(root)
    existing = ''
    if os.path.isfile(target):
        with open(target, 'r', encoding='utf-8', newline='') as fh:
            existing = fh.read()
    newline = '\r\n' if '\r\n' in existing else '\n'
    fields = [('rule', rule_id), ('file', relpath)]
    if digest:
        fields.append(('hash', digest))
    fields += [('reason', reason), ('by', by), ('at', time.strftime('%Y-%m-%d'))]
    block = ['  - %s: %s' % (fields[0][0], scalar(fields[0][1]))]
    block += ['    %s: %s' % (key, scalar(value)) for key, value in fields[1:]]
    if line and snippet:
        block.append('    # %s:%s  %s' % (relpath, line, ' '.join(str(snippet).split())[:100]))

    prefix = ''
    if not existing.strip():
        prefix = HEADER + 'dismissed:\n'
    else:
        if not existing.endswith(('\n', '\r\n')):
            prefix = '\n'
        if not re.search(r'^dismissed:\s*(#.*)?$', existing.replace('\r\n', '\n'), re.M):
            prefix += 'dismissed:\n'
        elif current.entries == [] and 'dismissed: []' in existing:
            raise DismissalError('%s 의 "dismissed: []" 를 "dismissed:" 로 바꾼 뒤 다시 실행하세요'
                                 % target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w' if not existing.strip() else 'a', encoding='utf-8', newline='') as fh:
        fh.write((prefix + '\n'.join(block) + '\n').replace('\n', newline))
    after = load(root)
    if after.error or not after.has(rule_id, relpath, digest):
        raise DismissalError('%s 에 기록한 뒤 다시 읽지 못했습니다: %s'
                             % (target, after.error or '항목이 보이지 않음'))
    return True
