#!/usr/bin/env python3
"""The public door: analyze(), language_of(), the cache, and the engine behind it.

One call builds everything, nothing raises, the same text answers the same
way every time -- and without the engine the answer is "could not read",
never a guess (design §4.6).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, needs_engine  # noqa: E402
from lib import structure  # noqa: E402
from lib.engine import loader  # noqa: E402

PHP = '<?php\nfunction f() {\n    $s = "x"; // c\n}\n'


def case_analyze():
    print('case_analyze:')
    fs = structure.analyze(PHP, 'php')
    check('a clean file is ok', fs.ok and fs.reason is None, str(fs.reason))
    check('it records the language and backend',
          fs.language == 'php' and fs.backend == 'tree-sitter', (fs.language, fs.backend))
    check('literal text and comments are found', len(fs.strings) == 1 and len(fs.comments) == 1,
          (fs.strings, fs.comments))
    check('the scope tree is built in the same call',
          fs.root.children and fs.root.children[0].kind == 'function')
    check('scopes are supported', fs.scope_supported is True)
    check('the text is carried for block_empty', fs.text == PHP)
    check('a clean file has no error regions', fs.errors == ())

    blade = structure.analyze("<p>It's x</p>\n@foreach ($a as $b)\n{{ $b }}\n@endforeach\n",
                              'blade')
    check('blade is read: its loop is a scope',
          blade.ok and [n.kind for n in blade.root.children] == ['loop'], blade.root)

    broken = structure.analyze('<?php\n$a = "oops;\n', 'php')
    check('a file that does not parse is still a value, with its error regions',
          broken.ok and broken.errors, broken.errors)
    check('and still answers coordinates', broken.line_of(0) == 1)


def case_unsupported():
    print('case_unsupported:')
    fs = structure.analyze('int main() {}', 'zig')
    check('an unknown language fails with a code',
          fs.ok is False and fs.reason == 'unsupported_language', str(fs.reason))
    check('the language is echoed back', fs.language == 'zig')
    check('it is not a crash', fs.root.kind == 'file')


def case_never_raises():
    print('case_never_raises:')
    from lib.structure import treesitter
    original = treesitter.analyze

    def explode(*_args):
        raise RuntimeError('boom')

    treesitter.analyze = explode
    try:
        structure.reset_cache()
        fs = structure.analyze(PHP, 'php')
    finally:
        treesitter.analyze = original
        structure.reset_cache()
    check('an internal error becomes a value',
          fs.ok is False and fs.reason == 'internal_error:RuntimeError', str(fs.reason))
    check('the message never leaks into the reason', 'boom' not in (fs.reason or ''))
    check('language_of never raises', structure.language_of(None) is None)


def case_engine_missing():
    print('case_engine_missing:')
    old = os.environ.get('CONVENTION_GUARD_NO_ENGINE')
    os.environ['CONVENTION_GUARD_NO_ENGINE'] = '1'
    loader.reset()
    structure.reset_cache()
    try:
        fs = structure.analyze(PHP, 'php')
    finally:
        if old is None:
            os.environ.pop('CONVENTION_GUARD_NO_ENGINE', None)
        else:
            os.environ['CONVENTION_GUARD_NO_ENGINE'] = old
        loader.reset()
        structure.reset_cache()
    check('without the engine a file is not read, and says why',
          fs.ok is False and fs.reason == 'engine_missing:disabled', fs.reason)
    check('no scope tree is pretended', fs.scope_supported is False and fs.root.children == ())


def case_cache():
    print('case_cache:')
    structure.reset_cache()
    first = structure.analyze(PHP, 'php')
    second = structure.analyze(PHP, 'php')
    check('the same text and language hits the cache', first is second)
    check('a different language is a different entry',
          structure.analyze(PHP, 'js') is not first)
    structure.reset_cache()
    check('reset_cache clears it', structure.analyze(PHP, 'php') is not first)
    check('an equal result is still produced after a reset',
          structure.analyze(PHP, 'php').comments == first.comments)

    structure.reset_cache()
    for i in range(structure.CACHE_MAX_ENTRIES + 5):
        structure.analyze('<?php\n$a = %d;\n' % i, 'php')
    check('the cache is bounded',
          structure.cache_size() == structure.CACHE_MAX_ENTRIES, str(structure.cache_size()))
    structure.reset_cache()


def case_language_of():
    print('case_language_of:')
    for name, want in (('a/b.blade.php', 'blade'), ('a/b.php', 'php'), ('a/b.tsx', 'tsx'),
                       ('a/b.ts', 'ts'), ('a/b.jsx', 'js'), ('a/b.mjs', 'js'), ('a/b.py', 'py'),
                       ('a/b.txt', None), ('a/b.go', None), ('.php', None)):
        check('language_of(%r) is %r' % (name, want), structure.language_of(name) == want,
              structure.language_of(name))


def main():
    case_unsupported()
    case_language_of()
    case_engine_missing()
    if needs_engine('structure facade'):
        for case in (case_analyze, case_never_raises, case_cache):
            case()
    return finish('structure facade')


if __name__ == '__main__':
    sys.exit(main())
