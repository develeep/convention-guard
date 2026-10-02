"""Deterministic detection: rules × change scope -> candidates.

Each rule kind differs in what it looks at and in what anchors a finding to
*this* change rather than to the repo's history:

  line      추가된 줄                 줄 자체가 앵커
  file      파일 전체 (다줄 패턴)       매치 구간이 변경된 줄과 겹치거나 그 안이 지워져야 함
  requires  조건 + 파일 전체            조건이 '추가된 줄'에 있어야 함
  absent    새 파일 전체               파일이 새것이어야 함
  paired    변경 집합 (줄만 지운 파일 포함)  변경 집합 자체가 앵커

A rule with semantic_review uses the same detectors; its candidates are
routed to a reviewer instead of straight to the agent (see pipeline.py).

`absent` and `paired` describe what a file *lacks*, so their snippet is a
fixed phrase and their fingerprint is constant. A dismissal of one is
therefore file-level and does not expire when the file changes -- which is
the right granularity for "this file needs no pair", not an oversight.
"""

from . import rules as rulelib, structure
from .candidate import Candidate, clip
from .structure import conditions as structure_conditions
from .structure.model import REJECT, UNKNOWN, Span


class Unchecked:
    """Files whose structure could not be read, and why.

    A structure condition that cannot be evaluated does not quietly pass: the
    candidate is kept and the file is named, so "no findings" never means "we
    could not look" (FR-01.5, US-06). The first reason for a file wins -- rule
    order is deterministic, so the report is too.
    """

    __slots__ = ('_reasons',)

    def __init__(self):
        self._reasons = {}

    def record(self, relpath, reason):
        self._reasons.setdefault(relpath, reason)

    def reason(self, relpath):
        return self._reasons.get(relpath)

    def files(self):
        return tuple(sorted(self._reasons))

    def summary(self, limit=None):
        """(paths to show, how many were folded away)."""
        paths = self.files()
        if limit is None or len(paths) <= limit:
            return paths, 0
        return paths[:limit], len(paths) - limit

    def __bool__(self):
        return bool(self._reasons)

    def __len__(self):
        return len(self._reasons)


def _span_of(analysed, lineno, match):
    """Match position -> file offset, or a reason why it cannot be trusted.

    The match was found in the line the diff reported; the analysis read the
    file on disk. They are normally the same text, but an edit between the two
    would put the offset somewhere else entirely -- so the slice is compared
    against what matched, and a mismatch keeps the candidate instead of
    judging it on the wrong position (SR-31).
    """
    offset = analysed.offset_of(lineno, match.start())
    matched = match.group(0)
    if analysed.text[offset:offset + len(matched)] != matched:
        return None, 'stale_line:%d' % lineno
    return Span(offset, offset + len(matched)), None


def _trimmed(match):
    """(start, end) of a match without the whitespace around it: the blank
    lines a `\\s*` swallowed are not where the code is, and counting them
    made the key and the changed-line window move with them (R11)."""
    text = match.group(0)
    if not text.strip():
        return match.start(), match.end()
    return (match.start() + len(text) - len(text.lstrip()),
            match.end() - (len(text) - len(text.rstrip())))


def _window(rule, relpath, body, match, start, end, unchecked=None):
    """The lines a change has to touch for this file match to be its doing.

    The match itself, except for `block_empty`: what it judges is the block,
    and emptying that block touches its body, not the header the pattern
    matched (R19). A file the layer cannot read keeps the match's own lines;
    the condition then reports it as unchecked.
    """
    if not (rule.get('detect') or {}).get('block_empty'):
        return start, end
    try:
        analysed = structure.analyze(body, structure.language_of(relpath))
        if not analysed.ok or not analysed.scope_supported:
            # where the block ends is unknown, so a change inside it could be
            # missed: the file is named, never passed in silence (design §4.6)
            _note(unchecked, relpath, analysed.reason or 'no_scope')
            return start, end
        node = structure_conditions.judged_block(analysed, Span(match.start(), match.end()))
    except Exception:       # noqa: BLE001 -- as in judge(): the hook outlives the layer
        return start, end
    if node is None:
        return start, end
    return min(start, node.start_line), max(end, node.end_line)


def _line_spans(pattern, text, lineno):
    """Every match on the line, lazily, as span makers for `_verdict`.

    The candidate is the line, so one surviving match is enough -- and a
    rejected first match (`"dd("` before `dd($user)`) must not hide a real one
    after it. Lazy, so the usual line with one match is judged once (R5).
    """
    return (lambda fs, m=m: _span_of(fs, lineno, m) for m in pattern.finditer(text))


def _has_requirement(rule, relpath, text, unchecked):
    """Is `must_contain_in_file` in `text` where it counts? A requirement
    that only sits in a comment is not there (R6) -- an unreadable file keeps
    the plain match and is reported as unchecked."""
    found, reason = structure_conditions.requirement_present(
        rule, text, lambda: structure.analyze(text, structure.language_of(relpath)))
    if reason:
        _note(unchecked, relpath, reason)
    return found


def _verdict(rule, relpath, lineno, span, source, unchecked):
    """ACCEPT / REJECT / UNKNOWN for one match, recording what it could not read."""
    language = structure.language_of(relpath)
    analysed = structure.analyze(source() if source else '', language)
    if not analysed.ok:
        _note(unchecked, relpath, analysed.reason)
        return UNKNOWN
    if callable(span):
        span, reason = span(analysed)
        if span is None:
            _note(unchecked, relpath, reason)
            return UNKNOWN
    verdict = structure_conditions.evaluate(rule, analysed, span)
    if verdict == UNKNOWN:
        _note(unchecked, relpath, _why_unknown(rule, analysed))
    return verdict


def _why_unknown(rule, analysed):
    if analysed.errors:
        return 'parse_error'
    if not analysed.scope_supported:
        return 'no_scope:%s' % (analysed.language or 'unknown')
    return analysed.reason or 'internal_error:Unknown'


def _note(unchecked, relpath, reason):
    if unchecked is not None:
        unchecked.record(relpath, reason or 'internal_error:Unknown')


class Stacks:
    """What stack detection concluded, in the shape the gates need."""

    def __init__(self, tags=(), versions=None, ids=(), lint=(), notes=()):
        self.tags = set(tags)
        self.versions = dict(versions or {})
        self.ids = list(ids)
        self.lint = list(lint)
        self.notes = list(notes)

    @classmethod
    def from_detected(cls, detected):
        return cls(detected['tags'], detected['versions'], detected['stacks'],
                   detected['lint'], detected.get('notes') or ())


def _never_dismissed(_rule_id, _relpath, _digest):
    return False


def scan(rule, scope, stacks, cap, is_dismissed=_never_dismissed, unchecked=None):
    """Candidates this rule reports for this change, at most `cap`."""
    kind = rule.get('kind', 'line')
    found = []
    # asked once per rule: a rule without structure conditions must run the
    # 1.x path exactly, reading nothing (FR-02.3, NR-U2-13)
    wants = structure_conditions.has_conditions(rule)

    def judge(relpath, lineno, span, source):
        try:
            return _verdict(rule, relpath, lineno, span, source, unchecked)
        except Exception:       # noqa: BLE001 -- the layer promises not to
            # raise; if that promise breaks the hook lives
            _note(unchecked, relpath, 'internal_error:Detect')
            return UNKNOWN

    def add(relpath, lineno, snippet, spans=None, source=None, code=None):
        """Returns True once the cap is reached. `spans` are the matches the
        candidate stands for; it is kept unless every one is REJECT. `code` is
        what the key covers."""
        cand = Candidate(rule['id'], relpath, lineno, snippet, code=code)
        if is_dismissed(rule['id'], relpath, cand.code_hash):
            return False
        if wants and spans is not None and source is not None:
            if all(judge(relpath, lineno, span, source) == REJECT for span in spans):
                return False    # filtered, so it does not fill the cap either
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
            source = (lambda path=relpath: scope.text(path)) if wants else None
            for lineno, text in scope.lines(relpath):
                if not rule['compiled_when'].search(text):
                    continue
                spans = _line_spans(rule['compiled_when'], text, lineno) if wants else None
                if add(relpath, lineno, clip(text), spans, source, code=text):
                    return found

        elif kind == 'absent':
            # only a file the agent just created -- on an existing file the
            # missing declaration is the repo's history, not this change
            if not scope.is_new(relpath):
                continue
            if not _has_requirement(rule, relpath, scope.added_body(relpath), unchecked):
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
            seams = scope.seams_of(relpath)
            is_new = scope.is_new(relpath)
            source = (lambda text=body: text) if wants else None
            for match in rule['compiled_file'].finditer(body):
                lo, hi = _trimmed(match)
                start = body.count('\n', 0, lo) + 1
                end = body.count('\n', 0, hi) + 1
                if not is_new:
                    first, last = _window(rule, relpath, body, match, start, end, unchecked)
                    # an added line inside, or a removal between two lines inside
                    if not (any(first <= n <= last for n in touched_lines)
                            or any(first <= n < last for n in seams)):
                        continue
                # a file match is already in file coordinates -- nothing to convert
                spans = [Span(match.start(), match.end())] if wants else None
                code = body[lo:hi]
                if add(relpath, start, clip(code.replace('\n', ' ⏎ ')), spans, source,
                       code=code):
                    return found

        elif kind == 'requires':
            # the condition must be in what was just added; the requirement is
            # looked for across the whole file, which is the context we lacked.
            # Without the file there is no "in file" to answer, and the added
            # lines alone would report every file as missing the requirement.
            body = scope.text(relpath)
            if not body or _has_requirement(rule, relpath, body, unchecked):
                continue
            before = len(found)
            source = (lambda text=body: text) if wants else None
            for lineno, text in scope.lines(relpath):
                if rule['compiled_when'].search(text):
                    # the trigger is judged by the rule's conditions; the
                    # requirement above only by `must_not_in` (R6, was DR-18)
                    spans = _line_spans(rule['compiled_when'], text, lineno) \
                        if wants else None
                    if add(relpath, lineno, clip(text), spans, source, code=text):
                        return found
                    if len(found) > before:
                        break   # one candidate per file -- but a dismissed line
                                # is not one, so keep looking for a live trigger

    return found


def run(rules, scope, stacks, cap, is_dismissed=_never_dismissed, unchecked=None):
    """[(rule, [Candidate])] for every rule with at least one candidate,
    most severe first, then most candidates first."""
    hits = []
    for rule in rules:
        found = scan(rule, scope, stacks, cap, is_dismissed, unchecked)
        if found:
            hits.append((rule, found))
    hits.sort(key=lambda h: (rulelib.severity_rank(h[0]), -len(h[1])))
    return hits
