#!/usr/bin/env python3
"""Value objects of the structure layer: spans, scope nodes, coordinates.

The contracts under test are `domain-entities.md` §2~§5 -- boundaries first,
because the whole layer reports positions and a one-character error there
turns into a wrong verdict about whether a match sits inside a comment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib.structure.model import (  # noqa: E402
    ACCEPT, REJECT, UNKNOWN, FileStructure, ScopeNode, Span, fail_code,
)


def build(text, **kw):
    """A successful FileStructure over `text` with no spans unless given."""
    kw.setdefault('language', 'php')
    kw.setdefault('backend', 'native')
    return FileStructure(text, **kw)


def case_span():
    print('case_span:')
    span = Span(2, 5)
    check('contains is start-inclusive', span.contains(2))
    check('contains is end-exclusive', not span.contains(5))
    check('an empty span contains nothing', not Span(3, 3).contains(3))
    check('adjacent spans do not overlap', not Span(0, 2).overlaps(Span(2, 4)))
    check('overlapping spans do', Span(0, 3).overlaps(Span(2, 4)))
    check('spans compare by value', Span(1, 2) == Span(1, 2))


def case_coordinates():
    print('case_coordinates:')
    text = 'aa\nbbbb\n\nc'
    fs = build(text)
    check('line 1 starts at 0', fs.offset_of(1) == 0)
    check('line 2 starts after the first newline', fs.offset_of(2) == 3)
    check('a column is added to the line start', fs.offset_of(2, 2) == 5)
    check('the empty line 3 is counted', fs.offset_of(3) == 8)
    check('offset 0 is line 1', fs.line_of(0) == 1)
    check('the newline itself belongs to its line', fs.line_of(2) == 1)
    check('the first byte after a newline is the next line', fs.line_of(3) == 2)
    check('end of text is the last line', fs.line_of(len(text)) == 4)

    for lineno in range(1, 5):
        got = fs.line_of(fs.offset_of(lineno))
        check('round trip holds for line %d' % lineno, got == lineno, 'got %d' % got)

    check('a column past the end clamps to the line end', fs.offset_of(1, 99) == 2)
    check('a line number below range clamps', fs.offset_of(-5) == 0)
    check('a line number above range clamps', fs.offset_of(999) == fs.offset_of(4))
    check('a negative offset is line 1', fs.line_of(-3) == 1)

    trailing = build('a\n')
    check('a trailing newline leaves an empty last line', trailing.line_of(2) == 2)
    empty = build('')
    check('an empty file has one line', empty.line_of(0) == 1 and empty.offset_of(1) == 0)


def case_containment():
    print('case_containment:')
    #      0123456789...
    text = 'x = "abc"; // note'
    fs = build(text, strings=(Span(4, 9),), comments=(Span(11, 18),))
    check('a span inside a string is in_string', fs.in_string(Span(5, 8)))
    check('the whole literal counts as inside', fs.in_string(Span(4, 9)))
    check('a span crossing the quote is not inside', not fs.in_string(Span(3, 6)))
    check('a comment span is in_comment', fs.in_comment(Span(14, 18)))
    check('a code span is in neither',
          not fs.in_string(Span(0, 1)) and not fs.in_comment(Span(0, 1)))
    check('a zero-width match is judged at its point', fs.in_string(Span(6, 6)))
    check('a zero-width match outside is not', not fs.in_string(Span(10, 10)))


def case_scopes():
    print('case_scopes:')
    inner = ScopeNode('catch', 4, 6, Span(40, 45), ())
    func = ScopeNode('function', 2, 8, Span(20, 60), (inner,))
    cls = ScopeNode('class', 1, 9, Span(10, 70), (func,))
    root = ScopeNode('file', 1, 10, Span(0, 80), (cls,))
    fs = build('\n' * 9, root=root)

    check('contains_line is inclusive at both ends',
          func.contains_line(2) and func.contains_line(8) and not func.contains_line(9))
    path = [node.kind for node in fs.scopes_at(5)]
    check('scopes_at walks outside in', path == ['file', 'class', 'function', 'catch'], str(path))
    check('scopes_at starts at the root', fs.scopes_at(1)[0].kind == 'file')
    check('innermost_function finds the function', fs.innermost_function(5) is func)
    check('innermost_function is None outside one', fs.innermost_function(10) is None)


def case_failure():
    print('case_failure:')
    fs = FileStructure.failed('unsupported_language', language='zig')
    check('a failed structure is not ok', fs.ok is False)
    check('it carries the reason', fs.reason == 'unsupported_language')
    check('it still answers coordinates', fs.line_of(0) == 1)
    check('it has an empty root', fs.root.kind == 'file' and fs.root.children == ())
    check('a successful structure has no reason', build('a').reason is None)
    check('fail_code names the exception class',
          fail_code(ValueError('x')) == 'internal_error:ValueError')
    check('a reason never leaks the message', 'x' not in fail_code(ValueError('x')))


def case_verdicts():
    print('case_verdicts:')
    check('the three verdicts are distinct', len({ACCEPT, REJECT, UNKNOWN}) == 3)


def main():
    for case in (case_span, case_coordinates, case_containment, case_scopes,
                 case_failure, case_verdicts):
        case()
    return finish('structure.model')


if __name__ == '__main__':
    sys.exit(main())
