"""Deterministic detection: rules × change scope -> candidates.

Each rule kind differs in what it looks at and in what anchors a finding to
*this* change rather than to the repo's history:

  line      추가된 줄                 줄 자체가 앵커
  file      파일 전체 (다줄 패턴)       매치 구간이 변경된 줄과 겹쳐야 함
  requires  조건 + 파일 전체            조건이 '추가된 줄'에 있어야 함
  absent    새 파일 전체               파일이 새것이어야 함
  paired    변경 집합                  변경 집합 자체가 앵커

A rule with semantic_review uses the same detectors; its candidates are
routed to a reviewer instead of straight to the agent (see pipeline.py).

`absent` and `paired` describe what a file *lacks*, so their snippet is a
fixed phrase and their fingerprint is constant. A dismissal of one is
therefore file-level and does not expire when the file changes -- which is
the right granularity for "this file needs no pair", not an oversight.
"""

from . import rules as rulelib
from .candidate import Candidate, clip


class Stacks:
    """What stack detection concluded, in the shape the gates need."""

    def __init__(self, tags=(), versions=None, ids=(), lint=()):
        self.tags = set(tags)
        self.versions = dict(versions or {})
        self.ids = list(ids)
        self.lint = list(lint)

    @classmethod
    def from_detected(cls, detected):
        return cls(detected['tags'], detected['versions'], detected['stacks'],
                   detected['lint'])


def _never_dismissed(_rule_id, _relpath, _digest):
    return False


def scan(rule, scope, stacks, cap, is_dismissed=_never_dismissed):
    """Candidates this rule reports for this change, at most `cap`."""
    kind = rule.get('kind', 'line')
    found = []

    def add(relpath, lineno, snippet):
        """Returns True once the cap is reached."""
        cand = Candidate(rule['id'], relpath, lineno, snippet)
        if is_dismissed(rule['id'], relpath, cand.code_hash):
            return False
        found.append(cand)
        return len(found) >= cap

    if kind == 'paired':
        # changeset-level: A changed, B did not. This branch never reaches
        # `applies()`, so the stack gate is applied by hand -- without it a
        # Laravel rule fires in a Go repo.
        if not rulelib.stack_ok(rule, stacks.tags, stacks.versions):
            return []
        visible = [f for f in scope.paths()
                   if not rulelib.match_any(rule.get('repo_exclude'), f)
                   and not rulelib.match_any(rule.get('exclude'), f)]
        touched = [f for f in visible if rulelib.match_any(rule['when_changed'], f)]
        if not touched:
            return []
        if any(rulelib.match_any(rule['require_changed'], f) for f in visible):
            return []
        for relpath in touched:
            if add(relpath, 1, '(짝이 되는 파일 변경 없음)'):
                break
        return found

    for relpath in scope.paths():
        if not rulelib.applies(rule, relpath, stacks.tags, stacks.versions):
            continue

        if kind == 'line':
            for lineno, text in scope.lines(relpath):
                if rule['compiled_when'].search(text) and add(relpath, lineno, clip(text)):
                    return found

        elif kind == 'absent':
            # only a file the agent just created -- on an existing file the
            # missing declaration is the repo's history, not this change
            if not scope.is_new(relpath):
                continue
            if not rule['compiled_must'].search(scope.added_body(relpath)):
                if add(relpath, 1, '(새 파일에 해당 선언이 없음)'):
                    return found

        elif kind == 'file':
            # whole file, so multi-line patterns are visible -- but the match
            # must touch a changed line, or every legacy block would fire.
            # No file text, no line numbers: counting newlines in the added
            # lines alone would report a match at a line it is not on.
            body = scope.text(relpath)
            if not body:
                continue
            touched_lines = scope.changed_linenos(relpath)
            is_new = scope.is_new(relpath)
            for match in rule['compiled_file'].finditer(body):
                start = body.count('\n', 0, match.start()) + 1
                end = body.count('\n', 0, match.end()) + 1
                if not is_new and not any(start <= n <= end for n in touched_lines):
                    continue
                if add(relpath, start, clip(match.group(0).replace('\n', ' ⏎ '))):
                    return found

        elif kind == 'requires':
            # the condition must be in what was just added; the requirement is
            # looked for across the whole file, which is the context we lacked.
            # Without the file there is no "in file" to answer, and the added
            # lines alone would report every file as missing the requirement.
            body = scope.text(relpath)
            if not body or rule['compiled_must'].search(body):
                continue
            before = len(found)
            for lineno, text in scope.lines(relpath):
                if rule['compiled_when'].search(text):
                    if add(relpath, lineno, clip(text)):
                        return found
                    if len(found) > before:
                        break   # one candidate per file -- but a dismissed line
                                # is not one, so keep looking for a live trigger

    return found


def run(rules, scope, stacks, cap, is_dismissed=_never_dismissed):
    """[(rule, [Candidate])] for every rule with at least one candidate,
    most severe first, then most candidates first."""
    hits = []
    for rule in rules:
        found = scan(rule, scope, stacks, cap, is_dismissed)
        if found:
            hits.append((rule, found))
    hits.sort(key=lambda h: (rulelib.severity_rank(h[0]), -len(h[1])))
    return hits
