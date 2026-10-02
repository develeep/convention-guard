#!/usr/bin/env python3
"""Structure accuracy: is this spot code, a comment or literal text, inside a
loop, inside a function? One YAML file per language in tests/structure/cases/.

With the engine every case must come out as written. Without it (the
CONVENTION_GUARD_NO_ENGINE=1 run) every case must come out unread -- the file
is not analysed and every structure condition is UNKNOWN, so the candidate is
kept and the file is named (design §4.6). Nothing in between: a case that is
"right by luck" without a parser would hide a hole.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from helpers import check, finish  # noqa: E402
from lib import structure  # noqa: E402
from lib.engine import loader  # noqa: E402
from lib.structure import conditions  # noqa: E402
from lib.structure.model import UNKNOWN, Span  # noqa: E402
from lib.yamlio import read as read_yaml  # noqa: E402

CASES = os.path.join(HERE, 'cases')
LANGUAGES = {'js', 'ts', 'tsx', 'php', 'blade', 'py'}


def load_cases():
    found = []
    for name in sorted(os.listdir(CASES)):
        if name.endswith('.yaml'):
            for case in read_yaml(os.path.join(CASES, name))['cases']:
                found.append((name, case))
    return found


def locate(code, needle, nth=1):
    at = -1
    for _ in range(int(nth or 1)):
        at = code.find(needle, at + 1)
        if at < 0:
            return None
    return Span(at, at + len(needle))


def judge(fs, span):
    kind = 'comment' if fs.in_comment(span) else 'string' if fs.in_string(span) else 'code'
    kinds = {node.kind for node in fs.scopes_around(span.start)}
    return kind, 'loop' in kinds, 'function' in kinds


def rule(**detect):
    return {'detect': detect}


def case_cases_are_well_formed(cases):
    print('case_cases_are_well_formed:')
    bad = [(f, c.get('name')) for f, c in cases
           if c.get('lang') not in LANGUAGES or locate(c['code'], str(c['at']), c.get('nth')) is None
           or not ({'kind', 'loop', 'function'} & set(c))]
    check('every case names a language, a spot that exists and something to expect', not bad, bad)
    check('more cases than the 29 the 3.3 review measured', len(cases) > 29, len(cases))
    by_lang = {}
    for _f, c in cases:
        by_lang[c['lang']] = by_lang.get(c['lang'], 0) + 1
    check('every language has cases', set(by_lang) == LANGUAGES, by_lang)


def case_with_engine(cases):
    print('case_with_engine (%d cases):' % len(cases))
    for name, case in cases:
        code = case['code']
        span = locate(code, str(case['at']), case.get('nth'))
        fs = structure.analyze(code, case['lang'])
        if not fs.ok or fs.in_error(span):
            check('%s: %s' % (name, case['name']), False,
                  'not read: %s %s' % (fs.reason, fs.errors[:2]))
            continue
        kind, loop, function = judge(fs, span)
        wrong = []
        if 'kind' in case and case['kind'] != kind:
            wrong.append('kind %s (want %s)' % (kind, case['kind']))
        if 'loop' in case and bool(case['loop']) != loop:
            wrong.append('loop %s' % loop)
        if 'function' in case and bool(case['function']) != function:
            wrong.append('function %s' % function)
        check('%s: %s' % (name, case['name']), not wrong, ', '.join(wrong))


def case_without_engine(cases):
    print('case_without_engine (%d cases):' % len(cases))
    wrong = []
    for name, case in cases:
        code = case['code']
        span = locate(code, str(case['at']), case.get('nth'))
        fs = structure.analyze(code, case['lang'])
        verdicts = {conditions.evaluate(rule(**detect), fs, span)
                    for detect in ({'not_in': ['comment', 'string']}, {'in_scope': 'loop'},
                                   {'in_scope': 'function'}, {'block_empty': True})}
        if fs.ok or not str(fs.reason).startswith('engine_missing:') or verdicts != {UNKNOWN}:
            wrong.append('%s: %s -> %s %s' % (name, case['name'], fs.reason, sorted(verdicts)))
    check('without the engine every case is unread and every condition UNKNOWN',
          not wrong, '; '.join(wrong[:5]))


def main():
    cases = load_cases()
    case_cases_are_well_formed(cases)
    engine = loader.get()
    if engine.ok:
        case_with_engine(cases)
    elif os.environ.get('CONVENTION_GUARD_NO_ENGINE'):
        case_without_engine(cases)
    else:
        check('구조 엔진이 있다 (python3 scripts/engine.py ensure --dir .engine)', False,
              engine.describe())
    return finish('구조 정확도')


if __name__ == '__main__':
    sys.exit(main())
