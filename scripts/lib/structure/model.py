"""What the structure layer knows about one file, as plain values.

Everything here is immutable and computed once. A `FileStructure` is the
answer to "where are the comments, the strings and the blocks in this text",
and callers judge positions against it without reading the file again.

Failure is a value, not an exception: a file the layer could not parse comes
back with `ok=False` and a machine-readable `reason`, and the caller decides
what to do (see FR-01.5 -- silence is not an option, the candidate is kept
and the file is reported as unchecked).

Offsets are character indexes into the original text, `[start, end)`, and
include the delimiters: `"abc"` spans the quotes, `// x` spans the slashes
but stops before the newline, so line numbers survive masking.
"""

import bisect
import math
from typing import NamedTuple, Optional, Tuple

# Verdicts of a structure condition. Strings, so a failed comparison shows the
# value in the test output instead of an enum repr.
ACCEPT = 'accept'
REJECT = 'reject'
UNKNOWN = 'unknown'

SCOPE_KINDS = ('file', 'class', 'function', 'loop', 'branch', 'catch')


def fail_code(exc):
    """'internal_error:ValueError' -- the class, never the message.

    The message could carry a path or a fragment of the file, and this string
    ends up in a systemMessage and in test expectations, so it has to be the
    same on every machine (NFR-02.3).
    """
    return 'internal_error:%s' % type(exc).__name__


def line_starts(text):
    """Character offset of every line, 1-based line N at index N-1."""
    starts = [0]
    find = text.find
    pos = find('\n')
    while pos >= 0:
        starts.append(pos + 1)
        pos = find('\n', pos + 1)
    return tuple(starts)


class Span(NamedTuple):
    """A half-open character range of the original text."""

    start: int
    end: int

    def contains(self, offset):
        return self.start <= offset < self.end

    def overlaps(self, other):
        return self.start < other.end and other.start < self.end


def _within(outer, inner):
    """Is `inner` entirely inside `outer`?

    A zero-width match -- a rule whose regex is all lookahead -- is judged at
    its point: the general rule would call it "contained" by every span, so
    every such match outside a comment would be rejected.
    """
    if inner.start == inner.end:
        return outer.contains(inner.start)
    return outer.start <= inner.start and inner.end <= outer.end


class ScopeNode(NamedTuple):
    """One block of the file: the file itself, a class, a function, a loop,
    a branch or a catch. Lines are 1-based and inclusive; `body` is the block
    contents without the braces, which is what `block_empty` judges."""

    kind: str
    start_line: int
    end_line: int
    body: Optional[Span]
    children: Tuple['ScopeNode', ...]

    def contains_line(self, lineno):
        return self.start_line <= lineno <= self.end_line


def _empty_root(text):
    return ScopeNode('file', 1, max(1, text.count('\n') + 1), Span(0, len(text)), ())


class FileStructure:
    """The analysis result for one (text, language) pair.

    `ok=False` means the whole result is untrusted: `comments` and `strings`
    still hold what was found before the failure, for diagnosis, but condition
    evaluation stops at `ok` and returns UNKNOWN without reading them.

    `scope_supported` is a different thing: the language declares whether it
    offers a scope tree at all. Blade is masked but not scoped, so `not_in`
    works there while `in_scope` cannot (CQ2=B).
    """

    __slots__ = ('text', 'ok', 'reason', 'language', 'backend',
                 'scope_supported', 'comments', 'strings', 'root', '_starts')

    def __init__(self, text, ok=True, reason=None, language='', backend='',
                 scope_supported=True, comments=(), strings=(), root=None,
                 starts=None):
        self.text = text
        self.ok = ok
        self.reason = reason
        self.language = language
        self.backend = backend
        self.scope_supported = scope_supported
        self.comments = tuple(comments)
        self.strings = tuple(strings)
        self.root = root if root is not None else _empty_root(text)
        self._starts = starts if starts is not None else line_starts(text)

    @classmethod
    def failed(cls, reason, text='', language='', backend='',
               comments=(), strings=(), scope_supported=False):
        return cls(text, ok=False, reason=reason, language=language, backend=backend,
                   scope_supported=scope_supported, comments=comments, strings=strings)

    # -- coordinates

    def line_count(self):
        return len(self._starts)

    def offset_of(self, lineno, col=0):
        """1-based line + 0-based column -> character offset.

        Out-of-range input clamps instead of raising: the line numbers come
        from a diff and the text from the working tree, and those two can be
        one edit apart. A wrong offset is caught by the caller comparing the
        matched text (SR-31); an exception would take the hook down.
        """
        lineno = min(max(lineno, 1), len(self._starts))
        start = self._starts[lineno - 1]
        end = (self._starts[lineno] - 1 if lineno < len(self._starts)
               else len(self.text))
        return min(start + max(col, 0), end)

    def line_of(self, offset):
        if offset <= 0:
            return 1
        return bisect.bisect_right(self._starts, min(offset, len(self.text)))

    def line_length(self, lineno):
        return self.offset_of(lineno, len(self.text)) - self.offset_of(lineno)

    # -- masking

    def in_comment(self, span):
        return self._inside(self.comments, span)

    def in_string(self, span):
        return self._inside(self.strings, span)

    @staticmethod
    def _inside(spans, span):
        # spans are sorted and never overlap, so at most one can contain the
        # match: the last one that starts at or before it. The `inf` end makes
        # the probe sort after a span that starts at the very same offset.
        idx = bisect.bisect_right(spans, (span.start, math.inf)) - 1
        return idx >= 0 and _within(spans[idx], span)

    # -- scopes

    def scopes_at(self, lineno):
        """The chain of scopes around `lineno`, outermost first."""
        path = [self.root]
        node = self.root
        while True:
            for child in node.children:
                if child.contains_line(lineno):
                    path.append(child)
                    node = child
                    break
            else:
                return tuple(path)

    def innermost_function(self, lineno):
        return self.innermost(lineno, ('function',))

    def innermost(self, lineno, kinds):
        """The deepest scope around `lineno` whose kind is one of `kinds`."""
        found = None
        for node in self.scopes_at(lineno):
            if node.kind in kinds:
                found = node
        return found

    def __repr__(self):
        return ('FileStructure(%s, language=%r, comments=%d, strings=%d)'
                % ('ok' if self.ok else self.reason, self.language,
                   len(self.comments), len(self.strings)))
