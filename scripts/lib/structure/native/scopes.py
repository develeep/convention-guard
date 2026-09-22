"""The block structure of a file.

Braces are counted only where they are code: the masking pass already said
which stretches are comments, strings or template text, and those are skipped
(which is the whole reason a `}` inside a string no longer ends a function).

Only the six kinds a rule can ask about become nodes. An object literal or a
bare `{ ... }` block still nests -- it just does not appear in the tree, so
`in_scope: loop` never matches something nobody named.

Two guards keep a minified file cheap: a line longer than MAX_LINE_FOR_SCOPE
grows no headers, and a header that reaches back across one keeps only its
last MAX_HEADER_CHARS characters -- the end nearest the brace, where the name
and the parameters are (NR-10, NR-11).
"""

import bisect
import math
import re

from ..model import ScopeNode, Span, line_starts

# A line this long is machine-written; nothing in it is a header worth finding.
MAX_LINE_FOR_SCOPE = 2000
# The header regexes carry nested quantifiers inherited from context.py, so
# what reaches them is bounded instead of the patterns being rewritten (CQ1=A).
MAX_HEADER_CHARS = 2000
# `context.py:43` -- one parameter per line is common in Go and TypeScript.
SIGNATURE_MAX_LINES = 12

_BRACES = re.compile(r'[{}]')
# `;` inside `for (a; b; c)` is not the end of the previous statement, so the
# walk back tracks parentheses as well.
_BOUNDARY = re.compile(r'[;{}()]')
_TAG_OPEN_CACHE = {}
_PY_HEADER = re.compile(r'^(\s*)(?:(?:async\s+)?def\s+\w+|class\s+\w+|except\b)')
_KEYWORD_CACHE = {}


def build(text, langdef, masked):
    """The root ScopeNode for this file."""
    root_body = Span(0, len(text))
    starts = line_starts(text)
    last_line = len(starts)
    if langdef.block_style is None:
        return ScopeNode('file', 1, last_line, root_body, ())
    skip = _merge(masked.comments + masked.strings + masked.texts)
    if langdef.block_style == 'indent':
        children = _indent_blocks(text, langdef, starts, skip)
    else:
        children = _brace_blocks(text, langdef, starts, skip)
    return ScopeNode('file', 1, last_line, root_body, children)


def _merge(spans):
    """Sorted, non-overlapping skip regions."""
    merged = []
    for span in sorted(spans):
        if merged and span.start <= merged[-1].end:
            merged[-1] = Span(merged[-1].start, max(merged[-1].end, span.end))
        else:
            merged.append(Span(span.start, span.end))
    return merged


class _Cursor:
    """Walks forward through the skip regions, answering 'is this code?'."""

    def __init__(self, spans):
        self._spans = spans
        self._at = 0

    def is_code(self, offset):
        while self._at < len(self._spans) and self._spans[self._at].end <= offset:
            self._at += 1
        return not (self._at < len(self._spans) and self._spans[self._at].contains(offset))


def _in_skip(skip, offset):
    index = bisect.bisect_right(skip, (offset, math.inf)) - 1
    return index >= 0 and skip[index].contains(offset)


def _tag_opens(langdef):
    pattern = _TAG_OPEN_CACHE.get(langdef.name, False)
    if pattern is False:
        opens = [open_ for open_, _close in langdef.tag_boundaries]
        pattern = _TAG_OPEN_CACHE[langdef.name] = (
            re.compile('|'.join(re.escape(o) for o in sorted(opens, key=len, reverse=True)))
            if opens else None)
    return pattern


def _line_of(starts, offset):
    lo, hi = 0, len(starts)
    while lo < hi:
        mid = (lo + hi) // 2
        if starts[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _line_bounds(text, starts, lineno):
    start = starts[lineno - 1]
    end = starts[lineno] - 1 if lineno < len(starts) else len(text)
    return start, end


# ---------------------------------------------------------------- brace languages

class _Open:
    __slots__ = ('kinds', 'start_line', 'brace', 'children')

    def __init__(self, kinds, start_line, brace):
        # usually one kind; a callback iteration is both a loop and the
        # function that walks it, outermost first
        self.kinds = kinds
        self.start_line = start_line
        self.brace = brace
        self.children = []


def _brace_blocks(text, langdef, starts, skip):
    cursor = _Cursor(skip)
    stack = [_Open(None, 1, -1)]
    for match in _BRACES.finditer(text):
        offset = match.start()
        if not cursor.is_code(offset):
            continue
        if text[offset] == '{':
            kinds, header_line = _header_at(text, langdef, starts, skip, offset)
            stack.append(_Open(kinds, header_line, offset))
        elif len(stack) > 1:
            _close(stack, text, starts, offset)
    while len(stack) > 1:                      # blocks left open by the file (D-2)
        _close(stack, text, starts, len(text))
    return tuple(stack[0].children)


def _close(stack, text, starts, offset):
    block = stack.pop()
    parent = stack[-1]
    if not block.kinds:
        parent.children.extend(block.children)  # unclassified blocks stay invisible
        return
    end_line = _line_of(starts, min(offset, max(len(text) - 1, 0))) if text else 1
    body = Span(block.brace + 1, offset)
    node = None
    # innermost first, so `xs.map(x => {` ends up loop > function: `in_scope:
    # loop` sees the iteration and the context pack still finds the callback
    for kind in reversed(block.kinds):
        children = tuple(block.children) if node is None else (node,)
        node = ScopeNode(kind, block.start_line, end_line, body, children)
    parent.children.append(node)


def _header_at(text, langdef, starts, skip, brace):
    """(kinds, header start line) for the block opened at `brace`."""
    lineno = _line_of(starts, brace)
    line_start, line_end = _line_bounds(text, starts, lineno)
    if line_end - line_start > MAX_LINE_FOR_SCOPE:
        return (), lineno
    floor_line = max(1, lineno - SIGNATURE_MAX_LINES)
    floor = starts[floor_line - 1]
    tags = _tag_opens(langdef)
    if tags is not None:
        # a header never reaches back across `<?php` into the template text
        last = None
        for match in tags.finditer(text, floor, brace):
            last = match
        if last is not None:
            floor = max(floor, last.end())
    begin = _statement_start(text, skip, floor, brace)
    header = _code_only(text, skip, begin, brace)
    stripped = header.lstrip()
    if not stripped:
        return (), lineno
    header_line = _line_of(starts, begin + (len(header) - len(stripped)))
    if len(stripped) > MAX_HEADER_CHARS:
        stripped = stripped[-MAX_HEADER_CHARS:]
    return _classify(stripped, langdef), header_line


def _statement_start(text, skip, floor, brace):
    """Just after the previous `;`, `{` or `}` that was real code.

    Walking backwards, a closing parenthesis opens a region whose semicolons
    belong to it -- `for (a; b; c) {` keeps its whole header.
    """
    depth = 0
    for match in reversed(list(_BOUNDARY.finditer(text, floor, brace))):
        if _in_skip(skip, match.start()):
            continue
        char = text[match.start()]
        if char == ')':
            depth += 1
        elif char == '(':
            depth = max(0, depth - 1)
        elif depth == 0:
            return match.end()
    return floor


def _code_only(text, skip, begin, end):
    """The slice with comments, strings and template text blanked out.

    Only the spans that actually reach into the window are looked at -- the
    skip list holds every span in the file, and walking all of them for every
    brace is what made a 10,000 line file slow.
    """
    first = bisect.bisect_right(skip, (begin, math.inf)) - 1
    if first < 0:
        first = 0
    overlapping = []
    for index in range(first, len(skip)):
        span = skip[index]
        if span.start >= end:
            break
        if span.end > begin:
            overlapping.append(span)
    if not overlapping:
        return text[begin:end]
    out = []
    cursor = begin
    for span in overlapping:
        start, stop = max(span.start, begin), min(span.end, end)
        out.append(text[cursor:start])
        out.append(' ' * (stop - start))
        cursor = stop
    out.append(text[cursor:end])
    return ''.join(out)


def _keywords(langdef, kind, words):
    key = (langdef.name, kind)
    pattern = _KEYWORD_CACHE.get(key)
    if pattern is None:
        pattern = _KEYWORD_CACHE[key] = (
            re.compile(r'(?<![\w$])(?:%s)\b' % '|'.join(words)) if words else None)
    return pattern


def _classify(header, langdef):
    """The kinds this header opens, outermost first (SR-13~SR-19, SR-20a).

    Usually one. `xs.map(x => {` is two: the block iterates *and* is a
    function body, and both readings are used -- a rule asks `in_scope: loop`
    while the context pack asks for the enclosing function.
    """
    for kind, words in (('catch', langdef.catch_keywords),
                        ('class', langdef.class_keywords)):
        pattern = _keywords(langdef, kind, words)
        if pattern is not None and pattern.search(header):
            return (kind,)
    iterating = (langdef.iteration_call is not None
                 and langdef.iteration_call.search(header) is not None)
    pattern = langdef.function_pattern
    # one line at a time: the inherited patterns are anchored per line
    is_function = pattern is not None and any(
        pattern.search(line) for line in header.split('\n'))
    if iterating:
        return ('loop', 'function') if is_function else ('loop',)
    if is_function:
        return ('function',)
    for kind, words in (('loop', langdef.loop_keywords),
                        ('branch', langdef.branch_keywords)):
        keyword = _keywords(langdef, kind, words)
        if keyword is not None and keyword.search(header):
            return (kind,)
    return ()


# ---------------------------------------------------------------- indent languages

def _indent_blocks(text, langdef, starts, skip):
    """Python: a header owns the lines indented deeper than itself."""
    cursor = _Cursor(skip)
    lines = text.split('\n')
    nodes = []
    for index, line in enumerate(lines):
        match = _PY_HEADER.match(line)
        if match is None or not cursor.is_code(starts[index]):
            continue
        indent = len(match.group(1))
        end = index
        for following in range(index + 1, len(lines)):
            text_line = lines[following]
            if text_line.strip() and len(text_line) - len(text_line.lstrip()) <= indent:
                break
            end = following
        kind = ('catch' if line.lstrip().startswith('except')
                else 'class' if line.lstrip().startswith('class') else 'function')
        body_start = min(starts[index] + len(line) + 1, len(text))
        body_end = _line_bounds(text, starts, end + 1)[1]
        nodes.append(ScopeNode(kind, index + 1, end + 1,
                               Span(body_start, max(body_start, body_end)), ()))
    return _nest(nodes)


def _nest(nodes):
    """Turn a flat, source-ordered list into a tree by line containment."""
    roots, stack = [], []
    for node in nodes:
        while stack and stack[-1][0].end_line < node.start_line:
            stack.pop()
        entry = (node, [])
        (stack[-1][1] if stack else roots).append(entry)
        stack.append(entry)
    return _freeze(roots)


def _freeze(entries):
    return tuple(node._replace(children=_freeze(children)) for node, children in entries)
