#!/usr/bin/env python3
"""ledger.apply(): how line origins carry over one observed change, as a table.

Origins: p pre, a agent, o other (someone's commit), u unknown; uppercase
marks a seam (the agent removed lines right after it), a leading ^ a seam
before line 1.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import ledger  # noqa: E402
from lib.observe import Snapshot, split_lines  # noqa: E402

A, B, C, D = 'alpha();', 'beta();', 'gamma();', 'delta();'

ROWS = [
    # (name, old, origins, new, label, want, kwargs)
    ('unchanged keeps everything', [A, B], 'pa', [A, B], 'a', 'pa', {}),
    ('an inserted line is the label', [A, B], 'pp', [A, C, B], 'a', 'pap', {}),
    ('appending at the end', [A], 'p', [A, B], 'a', 'pa', {}),
    ('a rewritten line is the label', [A, B], 'pp', [A, C], 'a', 'pa', {}),
    ('the agent removing a line leaves a seam', [A, B, C], 'ppp', [A, C], 'a', 'Pp', {}),
    ('removing the first line: a seam before line 1', [A, B], 'pp', [B], 'a', '^p', {}),
    ('removing everything', [A, B], 'pp', [], 'a', '^', {}),
    ('a person removing a line leaves none', [A, B, C], 'ppp', [A, C], 'u', 'pp', {}),
    ('drift is unknown', [A], 'p', [A, B], 'u', 'pu', {}),
    ('a moved line keeps its origin', [A, B, C], 'ppa', [B, C, A], 'a', 'pap', {}),
    ('a line moved and kept: no seam where it left', [A, B, C], 'ppp', [B, A, C], 'a', 'ppp', {}),
    ('a whitespace change is a change', ['  ' + A], 'p', ['    ' + A], 'a', 'a', {}),
    ('a copy of a human line is the agent\'s', [A, B], 'pp', [A, A, B], 'a', 'pap', {}),
    ('lines someone\'s commit brought are other', [A], 'p', [A, B, C], 'a', 'poa',
     {'arrived': {B: 1}}),
    ('only as many as arrived', [A], 'p', [A, B, B], 'a', 'poa', {'arrived': {B: 1}}),
    ('a file moved whole inherits from the pool', [], '', [A, B], 'a', 'pa',
     {'pool': [(A, 'p'), (B, 'a')]}),
    ('seams travel with their line', [A, B], 'Pp', [C, A, B], 'a', 'aPp', {}),
    ('identical blocks align', [A, B, A, B], 'ppaa', [A, B, C, A, B], 'a', 'ppaaa', {}),
]


def case_apply_table():
    print('case_apply_table:')
    for name, old, origins, new, label, want, kw in ROWS:
        got = ledger.apply(old, origins, new, label, **kw)
        check(name, got == want, '%r -> %r, want %r' % (origins, got, want))


def case_entry():
    print('case_entry:')
    first = ledger.Entry.first('a.php', Snapshot(True, [A, B], 'sig1'))
    check('first sight is all pre', first.origins == 'pp' and not first.owned())
    first.update(Snapshot(True, [A, C, B], 'sig2'), 'a')
    check('the agent line is owned', first.agent_lines() == [(2, C)] and first.owned())
    first.update(Snapshot(True, [A, B], 'sig3'), 'a')
    check('removing it leaves a seam the agent owns', first.agent_lines() == []
          and first.seams() == {1} and first.owned(), (first.origins, first.seams()))

    born = ledger.Entry.first('n.php', Snapshot(False))
    born.update(Snapshot(True, [A], 's'), 'a')
    check('a file the agent writes into being is created', born.created and born.owned())
    moved = ledger.Entry.first('m.php', Snapshot(False))
    moved.update(Snapshot(True, [A], 's'), 'a', pool=[(A, 'p')])
    check('a file only moved here is not', not moved.created and not moved.owned(),
          moved.origins)
    human = ledger.Entry.first('h.php', Snapshot(False))
    human.update(Snapshot(True, [A], 's'), 'u')
    check('nor is one a person created', not human.created and not human.owned())

    big = ledger.Entry.first('b.php', Snapshot(True, [A], 's'))
    big.update(Snapshot(True, None, 's2', 'too_large'), 'a')
    check('a file grown too large is owned so it can be named', big.owned()
          and big.flag == 'too_large')


def case_lines():
    print('case_lines:')
    for raw, want in (('a\nb\n', ['a', 'b']), ('a\nb', ['a', 'b']), ('a\n\n', ['a', '']),
                      ('', []), ('\n', ['']), ('a\x0cb\n', ['a\x0cb'])):
        check('split_lines %r' % raw, split_lines(raw) == want, split_lines(raw))
    for lines in ([], [''], ['', ''], [A, '', B]):
        packed = ledger._pack(lines)
        check('content round-trips %r' % lines,
              ledger._unpack(packed, len(lines)) == lines, ledger._unpack(packed, len(lines)))


if __name__ == '__main__':
    case_apply_table()
    case_entry()
    case_lines()
    sys.exit(finish('원장 출처 연산'))
