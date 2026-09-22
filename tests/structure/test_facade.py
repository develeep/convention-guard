#!/usr/bin/env python3
"""The public door: analyze(), language_of(), the cache and the backends.

Contracts from `component-methods.md` §1 and `business-logic-model.md` §1:
one call builds everything, nothing raises, and the same text answers the
same way every time.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure import backend as backendlib  # noqa: E402

PHP = '<?php\nfunction f() {\n    $s = "x"; // c\n}\n'


def case_analyze():
    print('case_analyze:')
    fs = structure.analyze(PHP, 'php')
    check('a clean file is ok', fs.ok and fs.reason is None, str(fs.reason))
    check('it records the language and backend',
          fs.language == 'php' and fs.backend == 'native')
    check('masking is filled in', len(fs.strings) == 1 and len(fs.comments) == 1)
    check('the scope tree is built in the same call (Q7=A)',
          fs.root.children and fs.root.children[0].kind == 'function')
    check('a brace language supports scopes', fs.scope_supported is True)
    check('the text is carried for block_empty', fs.text == PHP)

    blade = structure.analyze("<p>It's x</p>\n", 'blade')
    check('blade is masked but not scoped',
          blade.ok and blade.scope_supported is False and blade.root.children == ())

    broken = structure.analyze('<?php\n$a = "oops;\n', 'php')
    check('an unterminated string is a failure value, not an exception',
          broken.ok is False and broken.reason == 'unterminated_string:2', str(broken.reason))
    check('a failed analysis still answers coordinates', broken.line_of(0) == 1)


def case_unsupported():
    print('case_unsupported:')
    fs = structure.analyze('int main() {}', 'zig')
    check('an unknown language fails with a code',
          fs.ok is False and fs.reason == 'unsupported_language', str(fs.reason))
    check('the language is echoed back', fs.language == 'zig')
    check('it is not a crash', fs.root.kind == 'file')


def case_never_raises():
    print('case_never_raises:')
    original = backendlib.resolve

    def explode(_language):
        raise RuntimeError('boom')

    backendlib.resolve = explode
    try:
        structure.reset_cache()
        fs = structure.analyze(PHP, 'php')
    finally:
        backendlib.resolve = original
        structure.reset_cache()
    check('an internal error becomes a value (NR-14)',
          fs.ok is False and fs.reason == 'internal_error:RuntimeError', str(fs.reason))
    check('the message never leaks into the reason', 'boom' not in (fs.reason or ''))
    check('language_of never raises', structure.language_of(None) is None)


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
    check('the cache is bounded (NR-13)',
          structure.cache_size() == structure.CACHE_MAX_ENTRIES, str(structure.cache_size()))
    structure.reset_cache()


def case_backends():
    print('case_backends:')
    check('the native backend is registered on import',
          backendlib.resolve('php') is not None)
    check('it answers for every language',
          all(backendlib.resolve(name) is not None
              for name in ('php', 'js', 'go', 'java', 'rust', 'c', 'py', 'blade')))
    check('an unknown language resolves to nothing', backendlib.resolve('zig') is None)

    class Fake:
        name = 'fake'

        def supports(self, language):
            return language == 'php'

        def analyze(self, text, language):
            raise AssertionError('not reached')

    backendlib.register(Fake(), ['php'])
    check('an explicit registration wins', backendlib.resolve('php').name == 'fake')
    backendlib.reset_backends()
    check('reset_backends restores the default',
          backendlib.resolve('php').name == 'native')


def case_language_of():
    print('case_language_of:')
    check('the facade re-exports the mapping',
          structure.language_of('a/b.blade.php') == 'blade'
          and structure.language_of('a/b.php') == 'php'
          and structure.language_of('a/b.txt') is None)


def main():
    for case in (case_analyze, case_unsupported, case_never_raises, case_cache,
                 case_backends, case_language_of):
        case()
    return finish('structure facade')


if __name__ == '__main__':
    sys.exit(main())
