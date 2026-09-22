#!/usr/bin/env python3
"""Does this match satisfy the rule's structure conditions?

`business-rules.md` §4~§5. The layer only judges; keeping or dropping the
candidate is the detector's job (U2), and the snippet is never touched (D4).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure import conditions  # noqa: E402
from lib.structure.model import ACCEPT, REJECT, UNKNOWN, Span  # noqa: E402

PHP = '<?php\n'


def rule(**detect):
    return {'id': 'x', 'kind': 'line', 'detect': detect}


def judge(text, detect, needle, language='php'):
    fs = structure.analyze(text, language)
    start = text.index(needle)
    return conditions.evaluate(rule(**detect), fs, Span(start, start + len(needle)))


def case_gate():
    print('case_gate:')
    check('a rule without conditions has none',
          conditions.has_conditions(rule(when_line_added='x')) is False)
    check('not_in counts', conditions.has_conditions(rule(not_in=['comment'])) is True)
    check('in_scope counts', conditions.has_conditions(rule(in_scope='loop')) is True)
    check('block_empty counts', conditions.has_conditions(rule(block_empty=True)) is True)
    check('block_empty false does not count',
          conditions.has_conditions(rule(block_empty=False)) is False)
    check('a rule with no detect at all is safe',
          conditions.has_conditions({'id': 'x'}) is False)


def case_not_in():
    print('case_not_in:')
    text = PHP + '$a = 1; // dd(1)\n$b = "dd(2)";\ndd(3);\n'
    check('a match inside a comment is rejected',
          judge(text, {'not_in': ['comment']}, 'dd(1)') == REJECT)
    check('a match inside a string is rejected',
          judge(text, {'not_in': ['string']}, 'dd(2)') == REJECT)
    check('a match in code is accepted',
          judge(text, {'not_in': ['comment', 'string']}, 'dd(3)') == ACCEPT)
    check('a comment match survives a string-only condition',
          judge(text, {'not_in': ['string']}, 'dd(1)') == ACCEPT)
    check('not_in takes a bare string too',
          judge(text, {'not_in': 'comment'}, 'dd(1)') == REJECT)


def case_in_scope():
    print('case_in_scope:')
    text = PHP + '''function handle() {
    foreach ($xs as $x) {
        query($x);
    }
}
audit();
'''
    check('a match inside the named scope is accepted',
          judge(text, {'in_scope': 'loop'}, 'query($x)') == ACCEPT)
    check('a match outside it is rejected',
          judge(text, {'in_scope': 'loop'}, 'audit()') == REJECT)
    check('an enclosing function counts',
          judge(text, {'in_scope': 'function'}, 'query($x)') == ACCEPT)
    check('several scopes must all hold',
          judge(text, {'in_scope': ['loop', 'class']}, 'query($x)') == REJECT)


def case_block_empty():
    print('case_block_empty:')
    empty = PHP + 'try { go(); } catch (\\Throwable $e) {\n}\n'
    commented = PHP + 'try { go(); } catch (\\Throwable $e) {\n    // 캐시 미스는 무시\n}\n'
    logged = PHP + 'try { go(); } catch (\\Throwable $e) {\n    Log::warning($e);\n}\n'

    def catch_span(text):
        fs = structure.analyze(text, 'php')
        start = text.index('catch')
        return fs, Span(start, text.index('}', text.index('{', start)) + 1)

    for label, text, expected in (('an empty catch is empty', empty, ACCEPT),
                                  ('a comment is content (FR-02.1 정정)', commented, REJECT),
                                  ('a statement is content', logged, REJECT)):
        fs, span = catch_span(text)
        got = conditions.evaluate(rule(block_empty=True), fs, span)
        check(label, got == expected, got)

    fs = structure.analyze(PHP + 'dd(1);\n', 'php')
    check('no enclosing block is a rejection, not a shrug',
          conditions.evaluate(rule(block_empty=True), fs, Span(6, 11)) == REJECT)


def case_unknown():
    print('case_unknown:')
    broken = PHP + '$a = "oops;\ndd(1);\n'
    fs = structure.analyze(broken, 'php')
    span = Span(broken.index('dd(1)'), broken.index('dd(1)') + 5)
    check('a failed analysis makes every condition unknown (SR-27)',
          conditions.evaluate(rule(not_in=['comment']), fs, span) == UNKNOWN)
    check('so does block_empty',
          conditions.evaluate(rule(block_empty=True), fs, span) == UNKNOWN)

    blade = "<p>x</p>\n<?php dd(1); ?>\n"
    fs = structure.analyze(blade, 'blade')
    span = Span(blade.index('dd(1)'), blade.index('dd(1)') + 5)
    check('blade masks, so not_in still decides (CQ2=B)',
          conditions.evaluate(rule(not_in=['comment']), fs, span) == ACCEPT)
    check('blade has no scopes, so in_scope cannot decide',
          conditions.evaluate(rule(in_scope='function'), fs, span) == UNKNOWN)
    check('nor can block_empty',
          conditions.evaluate(rule(block_empty=True), fs, span) == UNKNOWN)


def case_combining():
    print('case_combining:')
    text = PHP + 'function f() {\n    // dd(1)\n}\n'
    fs = structure.analyze(text, 'php')
    start = text.index('dd(1)')
    span = Span(start, start + 5)
    check('all conditions must hold',
          conditions.evaluate(rule(not_in=['comment'], in_scope='function'), fs, span)
          == REJECT)

    blade = "<p>x</p>\n<?php /* dd(1) */ ?>\n"
    fs = structure.analyze(blade, 'blade')
    start = blade.index('dd(1)')
    span = Span(start, start + 5)
    check('a certain rejection outranks an unknown (SR-26)',
          conditions.evaluate(rule(not_in=['comment'], in_scope='function'), fs, span)
          == REJECT)


def case_never_raises():
    print('case_never_raises:')
    fs = structure.analyze(PHP + 'dd(1);\n', 'php')
    check('an unknown condition value does not crash',
          conditions.evaluate(rule(in_scope='nonsense'), fs, Span(6, 11)) == REJECT)
    check('a broken rule shape becomes unknown',
          conditions.evaluate({'detect': {'not_in': 7}}, fs, Span(6, 11)) in
          (UNKNOWN, ACCEPT))


def main():
    for case in (case_gate, case_not_in, case_in_scope, case_block_empty,
                 case_unknown, case_combining, case_never_raises):
        case()
    return finish('structure.conditions')


if __name__ == '__main__':
    sys.exit(main())
