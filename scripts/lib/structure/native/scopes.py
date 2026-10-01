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
from . import pyast

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
# where a line break ends statements, `;` is part of the header instead
_BOUNDARY_NL = re.compile(r'[{}()\n]')
_TAG_OPEN_CACHE = {}
_TOKENIZER_CACHE = {}
_INDENT_CACHE = {}
_OPENERS = frozenset('([{')
_CLOSERS = frozenset(')]}')
# a line ending in one of these has finished its statement (Go's semicolon
# insertion rule, which Kotlin follows closely enough for block headers)
_VALUE_END = frozenset(')]}"\'`')
# ...unless the next line carries on the expression
_CONTINUES = ('.', '?.', '&&', '||', '?:')


def build(text, langdef, masked):
    """The root ScopeNode for this file."""
    root_body = Span(0, len(text))
    starts = line_starts(text)
    last_line = len(starts)
    if langdef.block_style is None:
        return ScopeNode('file', 1, last_line, root_body, ())
    skip = _merge(masked.comments + masked.strings + masked.texts)
    if langdef.block_style == 'indent':
        children = pyast.build(text, starts) if langdef.parser == 'python_ast' else None
        if children is None:
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
    begin = _statement_start(text, skip, floor, brace, langdef.newline_ends_statement)
    header = _code_only(text, skip, begin, brace)
    stripped = header.lstrip()
    if not stripped:
        return (), lineno
    header_line = _line_of(starts, begin + (len(header) - len(stripped)))
    if len(stripped) > MAX_HEADER_CHARS:
        stripped = stripped[-MAX_HEADER_CHARS:]
    return _classify(stripped, langdef), header_line


def _statement_start(text, skip, floor, brace, newline_ends=False):
    """Just after the previous `;`, `{` or `}` that was real code.

    Walking backwards, a closing parenthesis opens a region whose semicolons
    belong to it -- `for (a; b; c) {` keeps its whole header. Where a line
    break ends statements, the break takes the place of `;`.
    """
    depth = 0
    pattern = _BOUNDARY_NL if newline_ends else _BOUNDARY
    for match in reversed(list(pattern.finditer(text, floor, brace))):
        pos = match.start()
        if _in_skip(skip, pos):
            continue
        char = text[pos]
        if char == ')':
            depth += 1
        elif char == '(':
            depth = max(0, depth - 1)
        elif depth == 0 and (char != '\n' or _line_break_ends(text, skip, floor, pos, brace)):
            return match.end()
    return floor


def _line_break_ends(text, skip, floor, pos, brace):
    before = _code_char(text, skip, pos - 1, floor - 1, -1)
    if before < 0:
        return True
    char = text[before]
    ends = (char.isalnum() or char in '_$' or char in _VALUE_END
            or (char in '+-' and before > floor and text[before - 1] == char))
    if not ends:
        return False
    after = _code_char(text, skip, pos + 1, brace, 1)
    return after < 0 or not text.startswith(_CONTINUES, after)


def _code_char(text, skip, index, stop, step):
    """The next offset from `index` towards `stop` that is neither blank nor
    inside a comment or string, or -1."""
    while index != stop:
        if text[index].isspace():
            index += step
            continue
        at = bisect.bisect_right(skip, (index, math.inf)) - 1
        if at >= 0 and skip[at].contains(index):
            index = skip[at].start - 1 if step < 0 else skip[at].end
            if (step < 0 and index <= stop) or (step > 0 and index >= stop):
                return -1
            continue
        return index
    return -1


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


def _tokenizer(langdef):
    pattern = _TOKENIZER_CACHE.get(langdef.name)
    if pattern is None:
        operators = sorted({op for op in langdef.member_ops + langdef.lambda_heads
                            if not op[0].isalpha()}, key=len, reverse=True)
        pattern = _TOKENIZER_CACHE[langdef.name] = re.compile('|'.join(
            [r'(?:[^\W\d]|\$)[\w$]*', r'\d[\w.]*']
            + [re.escape(op) for op in operators] + [r'\S']))
    return pattern


def _classify(header, langdef):
    """The kinds this header opens, outermost first (SR-13~SR-20a).

    Usually one. `xs.map(x => {` is two: the block iterates *and* is a
    function body, and both readings are used -- a rule asks `in_scope: loop`
    while the context pack asks for the enclosing function.

    A keyword counts only at the level of the block's own brace: inside the
    innermost parenthesis still open at the brace (the argument the block is
    passed in), outside any nested bracket, and never after a member
    operator. `foreach ([A::class] as $m) {` is a loop, `if (n.class) {` a
    branch, and `repo.find({` nothing at all.
    """
    tokens = _tokenizer(langdef).findall(header)
    opener, level, pairs = _brace_level(tokens)
    member_ops = langdef.member_ops
    free = [tokens[i] for i in level if i == 0 or tokens[i - 1] not in member_ops]
    for kind, words in (('catch', langdef.catch_keywords),
                        ('class', langdef.class_keywords)):
        if any(word in words for word in free):
            return (kind,)
    is_function = (_signature(header, langdef)
                   or _lambda_body(tokens, level, free, langdef))
    if _iterates(tokens, opener, level, pairs, free, langdef):
        return ('loop', 'function') if is_function else ('loop',)
    if is_function:
        return ('function',)
    # the last one owns the brace: `else if (...) {`, and the `if` that follows
    # a statement a missing semicolon did not end
    for word in reversed(free):
        if word in langdef.loop_keywords:
            return ('loop',)
        if word in langdef.branch_keywords:
            return ('branch',)
    return ()


def _brace_level(tokens):
    """(innermost unclosed opener or -1, token indexes at the brace's level,
    closer -> opener).

    The level is what follows that opener -- after its last top-level comma,
    so only the argument the block belongs to -- with nested brackets
    collapsed to their two ends. Outside any opener a comma is part of the
    statement (`if v, ok := m[k]; ok {`).
    """
    stack, pairs = [], {}
    for index, token in enumerate(tokens):
        if token in _OPENERS:
            stack.append(index)
        elif token in _CLOSERS and stack:
            pairs[index] = stack.pop()
    opener = stack[-1] if stack else -1
    level, depth = [], 0
    for index in range(opener + 1, len(tokens)):
        token = tokens[index]
        if token in _OPENERS:
            if depth == 0:
                level.append(index)
            depth += 1
        elif token in _CLOSERS:
            depth = max(0, depth - 1)
            if depth == 0:
                level.append(index)
        elif depth == 0:
            if token == ',' and opener >= 0:
                level = []
            else:
                level.append(index)
    return opener, level, pairs


def _signature(header, langdef):
    """Does a function pattern match the header?

    One line at a time first -- the inherited patterns are anchored per line
    -- then the whole signature on one line, for `run(\n  a,\n) {`.
    """
    pattern = langdef.function_pattern
    if pattern is None:
        return False
    if langdef.optional_semicolons:
        header = _last_statement(header)
    lines = header.split('\n')
    if any(pattern.search(line) for line in lines):
        return True
    return len(lines) > 1 and pattern.search(' '.join(header.split())) is not None


def _last_statement(header):
    """From the last line break that ended a statement, for languages where a
    semicolon is optional: a line that closes a value followed by one that
    opens a new statement."""
    depth, cut = 0, 0
    for index, char in enumerate(header):
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        elif char == '\n' and depth == 0:
            before = header[:index].rstrip()
            after = header[index + 1:].lstrip()
            if (before and after and (before[-1].isalnum() or before[-1] in '_$)]')
                    and (after[0].isalnum() or after[0] in '_$@#')):
                cut = index + 1
    return header[cut:]


def _lambda_body(tokens, level, free, langdef):
    """Is the block a lambda's body -- `x => {`, `() -> {`, `|x| {`, or an
    anonymous `function (...) {` / `func() {`?"""
    if not level:
        return False
    heads = langdef.lambda_heads
    last = tokens[level[-1]]
    if last in heads and not last[0].isalpha():
        # an arrow after a keyword is a switch arm: `case 1 -> {`
        keywords = (langdef.loop_keywords + langdef.branch_keywords
                    + langdef.class_keywords + langdef.catch_keywords)
        return not any(word in keywords for word in free)
    return any(word in heads and word[0].isalpha() for word in free)


def _iterates(tokens, opener, level, pairs, free, langdef):
    """Is this block the body of a callback handed to an iteration call?

    `xs.map(x => {` and `$u->each(function ($u) {` are; `xs.map(f)` closed
    before the brace, or an object literal passed to `find({`, are not.
    """
    if (opener >= 0 and tokens[opener] == '(' and _lambda_body(tokens, level, free, langdef)
            and _iteration_name(tokens, opener - 1, langdef)):
        return True
    if langdef.trailing_lambdas and level:
        last = level[-1]
        if tokens[last] == ')' and last in pairs:
            return _iteration_name(tokens, pairs[last] - 1, langdef)
        return _iteration_name(tokens, last, langdef)
    return False


def _iteration_name(tokens, index, langdef):
    if index < 0:
        return False
    member = index > 0 and tokens[index - 1] in langdef.member_ops
    names = langdef.iteration_methods if member else langdef.iteration_functions
    return tokens[index] in names


# ---------------------------------------------------------------- indent languages

def _indent_headers(langdef):
    compiled = _INDENT_CACHE.get(langdef.name)
    if compiled is None:
        compiled = _INDENT_CACHE[langdef.name] = tuple(
            (kind, re.compile(r'^(\s*)' + pattern)) for kind, pattern in langdef.indent_headers)
    return compiled


def _indent_blocks(text, langdef, starts, skip):
    """A header owns the lines indented deeper than itself.

    Counted from where the header's brackets close (a signature split over
    lines), not breaking on a line inside a string or one that is only a
    comment, and with the decorators above it (R21).
    """
    cursor = _Cursor(skip)
    headers = _indent_headers(langdef)
    comments = tuple(token.text for token in langdef.line_comment)
    decorator = langdef.decorator_prefix
    lines = text.split('\n')
    nodes = []
    for index, line in enumerate(lines):
        kind = match = None
        for kind, pattern in headers:
            match = pattern.match(line)
            if match is not None:
                break
        if match is None or not cursor.is_code(starts[index]):
            continue
        indent = len(match.group(1))
        header_end, depth = index, _open_brackets(line)
        while depth > 0 and header_end + 1 < len(lines):
            header_end += 1
            depth += _open_brackets(lines[header_end])
        end = header_end
        for following in range(header_end + 1, len(lines)):
            text_line = lines[following]
            if text_line.strip() and _in_skip(skip, starts[following]):
                end = following             # inside a string that started in the block
                continue
            if comments and text_line.lstrip().startswith(comments):
                continue                    # a comment does not end a block
            if text_line.strip() and len(text_line) - len(text_line.lstrip()) <= indent:
                break
            end = following
        first = index
        while decorator and first > 0 and lines[first - 1].strip().startswith(decorator) \
                and len(lines[first - 1]) - len(lines[first - 1].lstrip()) == indent:
            first -= 1
        body_start = min(starts[header_end] + len(lines[header_end]) + 1, len(text))
        body_end = _line_bounds(text, starts, end + 1)[1]
        nodes.append(ScopeNode(kind, first + 1, end + 1,
                               Span(body_start, max(body_start, body_end)), ()))
    return _nest(nodes)


def _open_brackets(line):
    return sum(line.count(c) for c in '([{') - sum(line.count(c) for c in ')]}')


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
