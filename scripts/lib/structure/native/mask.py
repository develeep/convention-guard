"""Where the comments and the string literals are.

The scanner never walks the text character by character. Each state knows the
handful of tokens that can end it, those tokens are one compiled alternation,
and `search(text, pos)` jumps straight to the next one -- a long string or a
long comment costs one match, not its length (NR-03).

States nest, so the scanner keeps a stack rather than a single state: an
interpolation hole inside a template literal is code, and that code can open
another template literal (CQ1=A).

There used to be a second, line-at-a-time path for files with no token that
can cross a line. The U1 spike deleted it (gate A, NR-05/NR-06): real files
almost always contain a block comment, so it applied to 0.8% of the corpus,
and where it did apply it ran 27% slower than this scan -- skipping between
tokens leaves a line-based pass nothing to win. The measurements are in
tests/perf/results/gate-a-evidence.json.
"""

import re
from typing import NamedTuple, Optional, Tuple

from ..model import Span


class MaskResult(NamedTuple):
    comments: Tuple[Span, ...]
    strings: Tuple[Span, ...]
    reason: Optional[str] = None
    # Stretches outside the language's code tags -- the HTML around `<?php`.
    # Not comments and not strings, but not code either: the scope pass must
    # not count their braces (SR-11).
    texts: Tuple[Span, ...] = ()

    @property
    def ok(self):
        return self.reason is None


class _Patterns(NamedTuple):
    code: Optional[re.Pattern]
    code_interp: Optional[re.Pattern]
    text: Optional[re.Pattern]
    blocks: tuple            # per block-comment index: (pattern, close, nestable)
    strings: tuple           # per string-delimiter index: (pattern, delim)
    multilines: tuple        # per multiline index: (pattern or None, spec)


_NEWLINE = re.compile(r'\n')
_HEREDOC_ID = re.compile(r"[ \t]*(['\"]?)(\w+)\1")
_CACHE = {}
_TERMINATORS = {}


def _alternation(parts):
    """[(group, source, weight)] -> one compiled pattern, longest token first.

    Python's `re` takes the first alternative that matches, so ordering by
    token length is how SR-01 ("the longest token wins") is implemented:
    `r#"` has to be tried before `"`, `<?php` before `<?`.
    """
    if not parts:
        return None
    parts = sorted(parts, key=lambda part: -part[2])
    return re.compile('|'.join('(?P<%s>%s)' % (name, src) for name, src, _w in parts))


def patterns(langdef):
    """The compiled alternations for one language, built once per process."""
    cached = _CACHE.get(langdef.name)
    if cached is None:
        cached = _CACHE[langdef.name] = _build(langdef)
    return cached


def _build(langdef):
    code = []
    for i, token in enumerate(langdef.line_comment):
        code.append(('lc%d' % i, re.escape(token.text) + (token.guard or ''),
                     len(token.text)))
    for i, (open_, _close, _nest) in enumerate(langdef.block_comment):
        code.append(('bo%d' % i, re.escape(open_), len(open_)))
    for i, spec in enumerate(langdef.multiline_strings):
        code.append(('ml%d' % i, re.escape(spec.open), len(spec.open)))
    for i, delim in enumerate(langdef.string_delims):
        code.append(('sd%d' % i, re.escape(delim.open), len(delim.open)))
    for _open, close in langdef.tag_boundaries:
        code.append(('tagclose', re.escape(close), len(close)))
        break                                   # every boundary shares one closer

    text = []
    for i, (open_, _close) in enumerate(langdef.tag_boundaries):
        text.append(('tagopen%d' % i, re.escape(open_), len(open_)))
    offset = len(langdef.block_comment)
    for i, (open_, _close, _nest) in enumerate(langdef.text_comment):
        text.append(('tc%d' % (offset + i), re.escape(open_), len(open_)))

    blocks = []
    for open_, close, nestable in langdef.block_comment + langdef.text_comment:
        parts = [('close', re.escape(close), len(close))]
        if nestable:
            parts.append(('bopen', re.escape(open_), len(open_)))
        blocks.append((_alternation(parts), close, nestable))

    strings = []
    for delim in langdef.string_delims:
        parts = [('close', re.escape(delim.open), len(delim.open)),
                 ('nl', r'\n', 1)]
        if delim.escape:
            parts.append(('esc', re.escape(delim.escape), 9))
        if delim.interpolation:
            parts.append(('interp', re.escape(delim.interpolation[0]),
                          len(delim.interpolation[0]) + 1))
        strings.append((_alternation(parts), delim))

    multilines = []
    for spec in langdef.multiline_strings:
        parts = []
        if spec.terminator == 'token':
            parts.append(('close', re.escape(spec.close), len(spec.close)))
        if spec.escape:
            parts.append(('esc', re.escape(spec.escape), 9))
        if spec.interpolation:
            parts.append(('interp', re.escape(spec.interpolation[0]),
                          len(spec.interpolation[0]) + 1))
        multilines.append((_alternation(parts), spec))

    return _Patterns(
        code=_alternation(code),
        code_interp=_alternation(code + [('lb', r'\{', 1), ('rb', r'\}', 1)]),
        text=_alternation(text),
        blocks=tuple(blocks),
        strings=tuple(strings),
        multilines=tuple(multilines),
    )


def _terminator(name):
    """The line that closes a heredoc opened with `name` (SR-09)."""
    pattern = _TERMINATORS.get(name)
    if pattern is None:
        pattern = _TERMINATORS[name] = re.compile(
            r'(?P<close>^[ \t]*%s)(?![\w])' % re.escape(name), re.M)
    return pattern


class _Frame:
    __slots__ = ('kind', 'start', 'index', 'depth', 'pattern', 'spec', 'interp')

    def __init__(self, kind, start, index=0, pattern=None, spec=None, interp=False):
        self.kind = kind
        self.start = start
        self.index = index
        self.depth = 0
        self.pattern = pattern
        self.spec = spec
        self.interp = interp


def scan(text, langdef):
    """MaskResult for the whole text."""
    comments, strings, reason, texts = _scan(
        text, langdef, patterns(langdef), in_code=langdef.starts_in_code)
    return MaskResult(tuple(comments), tuple(strings), reason, tuple(texts))


def _scan(text, langdef, pats, in_code, base=0):
    """The state machine. Returns (comments, strings, reason, texts)."""
    comments, strings, texts = [], [], []
    stack = [_Frame('code' if in_code else 'text', 0)]
    pos, size = 0, len(text)

    while pos < size:
        frame = stack[-1]
        pattern = _pattern_for(frame, pats)
        if pattern is None:
            break
        match = pattern.search(text, pos)
        if match is None:
            break
        group = match.lastgroup
        pos = match.end()

        if frame.kind == 'code':
            handled = _step_code(text, langdef, pats, stack, frame, match, group,
                                 comments, strings, base)
            if handled is not None:
                pos = handled
        elif frame.kind == 'text':
            if group.startswith('tagopen'):
                if match.start() > frame.start:
                    texts.append(Span(base + frame.start, base + match.start()))
                frame.start = match.end()     # where template text would resume
                stack.append(_Frame('code', match.end()))
            else:
                stack.append(_Frame('block', match.start(), int(group[2:])))
        elif frame.kind == 'line_comment':
            comments.append(Span(base + frame.start, base + match.start()))
            stack.pop()
        elif frame.kind == 'block':
            _pattern, _close, nestable = pats.blocks[frame.index]
            if group == 'bopen' and nestable:
                frame.depth += 1
            elif nestable and frame.depth:
                frame.depth -= 1
            else:
                comments.append(Span(base + frame.start, base + match.end()))
                stack.pop()
        elif frame.kind in ('string', 'multiline'):
            pos = _step_literal(text, pats, stack, frame, match, group, strings, base, pos)
            if pos is None:
                return comments, strings, _reason(frame, text, base), texts

    return _close_out(text, stack, comments, strings, texts, base)


def _pattern_for(frame, pats):
    if frame.kind == 'code':
        return pats.code_interp if frame.interp else pats.code
    if frame.kind == 'text':
        return pats.text
    if frame.kind == 'line_comment':
        return _NEWLINE
    if frame.kind == 'block':
        return pats.blocks[frame.index][0]
    if frame.kind == 'string':
        return pats.strings[frame.index][0]
    return frame.pattern


def _step_code(text, langdef, pats, stack, frame, match, group, comments, strings, base):
    if group.startswith('lc'):
        stack.append(_Frame('line_comment', match.start()))
    elif group.startswith('bo'):
        stack.append(_Frame('block', match.start(), int(group[2:])))
    elif group.startswith('sd'):
        index = int(group[2:])
        frame = _Frame('string', match.start(), index)
        frame.interp = pats.strings[index][1].interpolation is not None
        stack.append(frame)
    elif group.startswith('ml'):
        return _open_multiline(text, pats, stack, match, int(group[2:]))
    elif group == 'tagclose':
        if len(stack) > 1:
            stack.pop()
            stack[-1].start = match.end()             # text resumes after `?>`
    elif group == 'lb':
        frame.depth += 1
    elif group == 'rb':
        if frame.depth:
            frame.depth -= 1
        elif frame.interp:
            stack.pop()
            stack[-1].start = match.start()       # the next fragment owns the `}`
    return None


def _open_multiline(text, pats, stack, match, index):
    """Push a multiline literal frame; returns the new scan position."""
    pattern, spec = pats.multilines[index]
    if spec.terminator == 'heredoc_line':
        ident = _HEREDOC_ID.match(text, match.end())
        if ident is None:
            return match.end()                    # `<<<` that opens nothing
        nowdoc = ident.group(1) == "'"
        frame = _Frame('multiline', match.start(), index,
                       pattern=_terminator(ident.group(2)), spec=spec)
        frame.interp = not nowdoc
        stack.append(frame)
        return ident.end()
    frame = _Frame('multiline', match.start(), index, pattern=pattern, spec=spec)
    frame.interp = spec.interpolation is not None
    stack.append(frame)
    return match.end()


def _step_literal(text, pats, stack, frame, match, group, strings, base, pos):
    """One step inside a string or multiline literal. None means failure."""
    if group == 'esc':
        return min(match.end() + 1, len(text))
    if group == 'nl':
        return None
    if group == 'close':
        strings.append(Span(base + frame.start, base + match.end()))
        stack.pop()
        return pos
    if group == 'interp' and frame.interp:
        strings.append(Span(base + frame.start, base + match.end()))
        stack.append(_Frame('code', match.end(), interp=True))
        return pos
    return pos


def _reason(frame, text, base):
    """A single-line string that ran into a newline (SR-10).

    The line number is local to `text`, which is the whole file on the full
    path. The fast path throws the result away and rescans, so its shorter
    view never reaches a caller.
    """
    return 'unterminated_string:%d' % (text.count('\n', 0, frame.start) + 1)


def _close_out(text, stack, comments, strings, texts, base):
    """What is still open at end of file decides success (Q2=B)."""
    reason = None
    topmost = True
    while stack:
        frame = stack.pop()
        # only a text frame that nothing sits on top of is still template text
        if topmost and frame.kind == 'text' and frame.start < len(text):
            texts.append(Span(base + frame.start, base + len(text)))
        topmost = False
        line = text.count('\n', 0, frame.start) + 1
        if frame.kind == 'line_comment':
            comments.append(Span(base + frame.start, base + len(text)))
        elif frame.kind == 'block':
            reason = reason or 'unterminated_block_comment:%d' % line
        elif frame.kind == 'string':
            reason = reason or 'unterminated_string:%d' % line
        elif frame.kind == 'multiline':
            reason = reason or 'unterminated_heredoc:%d' % line
        elif frame.kind == 'code' and frame.interp:
            reason = reason or 'unterminated_interpolation:%d' % line
    comments.sort()
    strings.sort()
    texts.sort()
    return comments, strings, reason, texts
