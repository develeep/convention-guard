#!/usr/bin/env python3
"""Judgment units: what a `when_code_added` rule asks a reviewer about.

One question per unit, never per line:
  function   the outermost function around added lines (closures fold in)
  header     every added line outside a function, one per file
  file       the whole file, when its structure could not be read
A unit stands only on an added line with a word in it: a `}` the ledger
paired with the wrong brace must not pull a legacy function into review.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, needs_engine  # noqa: E402
from lib import units  # noqa: E402

PHP = '''<?php

namespace App\\Http\\Controllers;

use App\\Models\\Order;

class OrderController extends Controller
{
    public function legacy()
    {
        return 1;
    }

    public function store()
    {
        $total = collect($items)->sum(fn ($i) => $i['price']);
        DB::transaction(function () use ($total) {
            Order::create(['total' => $total]);
        });
    }
}
'''

PY = '''import os


class Svc:
    limit = 3

    def run(self):
        return os.getcwd()
'''


def added(text, *linenos):
    lines = text.split('\n')
    return [(n, lines[n - 1]) for n in linenos]


def summary(found):
    return [(u.kind, u.start, u.end, list(u.lines)) for u in found]


def case_meaningful():
    print('case_meaningful:')
    check('a word is meaningful', units.meaningful('    return 1;'))
    check('a brace alone is not', not units.meaningful('    }'))
    check('nor punctuation', not units.meaningful('  });'))
    check('nor a blank line', not units.meaningful('   '))


def case_function_units():
    print('case_function_units:')
    found = units.of(PHP, 'php', added(PHP, 16, 17, 18, 19))
    check('lines in a method, its closure and its arrow fn are one unit',
          summary(found) == [('function', 14, 20, [16, 17, 18])], summary(found))
    check('the unit code is the whole method',
          found[0].code.startswith('    public function store()')
          and found[0].code.rstrip().endswith('}'), found[0].code)
    check('labelled by its first line', found[0].label == 'public function store()',
          found[0].label)

    found = units.of(PHP, 'php', added(PHP, 12))
    check('a brace alone in a legacy method makes no unit', found == [], summary(found))

    found = units.of(PHP, 'php', added(PHP, 11, 16))
    check('two methods are two units, in file order',
          [u.start for u in found] == [9, 14], summary(found))


def case_header_unit():
    print('case_header_unit:')
    found = units.of(PHP, 'php', added(PHP, 1, 3, 5, 7, 8))
    check('every added line outside a function is one header unit',
          summary(found) == [('header', 1, 21, [1, 3, 5, 7])], summary(found))
    head = found[0]
    check('its code is the file without function bodies',
          'use App\\Models\\Order;' in head.code and 'Order::create' not in head.code,
          head.code)
    check('labelled as the file head', head.label == '(파일 머리)', head.label)

    found = units.of(PHP, 'php', added(PHP, 5, 16))
    check('a header and a function unit side by side',
          [u.kind for u in found] == ['header', 'function'], summary(found))

    body_only = units.of(PHP, 'php', added(PHP, 16))[0]
    other = PHP.replace("['total' => $total]", "['sum' => $total]")
    check('a function body change leaves the header code alone',
          units.of(PHP, 'php', added(PHP, 5))[0].code
          == units.of(other, 'php', added(other, 5))[0].code)
    check('and changes the function code',
          body_only.code != units.of(other, 'php', added(other, 16))[0].code)

    found = units.of(PY, 'py', added(PY, 5, 8))
    check('python: a class attribute is header, a method is a function',
          [(u.kind, list(u.lines)) for u in found] == [('header', [5]), ('function', [8])],
          summary(found))


def case_parse_error():
    print('case_parse_error:')
    broken = PHP.replace("        return 1;\n", "        return (1;\n")
    found = units.of(broken, 'php', added(broken, 16))
    check('a file the parser could not fully read is one file unit',
          [u.kind for u in found] == ['file'], summary(found))


def case_without_structure():
    print('case_without_structure:')
    found = units.of('whatever\n}\nmore\n', None, [(1, 'whatever'), (2, '}')])
    check('an unknown language is one file unit',
          summary(found) == [('file', 1, 3, [1])], summary(found))
    check('labelled as the whole file', found[0].label == '(파일 전체)', found[0].label)
    check('nothing meaningful added, no unit', units.of('}\n', None, [(1, '}')]) == [])


if __name__ == '__main__':
    case_meaningful()
    case_without_structure()
    if needs_engine('판정 단위 (함수 경계)'):
        case_function_units()
        case_header_unit()
        case_parse_error()
    sys.exit(finish('판정 단위'))
