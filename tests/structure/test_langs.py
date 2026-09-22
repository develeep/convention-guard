#!/usr/bin/env python3
"""Language definitions: the one file a new language should touch.

`domain-entities.md` §6. The extension table is inherited from
`context.py:BRACE_LANGS`, so the regression case pins every extension the 1.x
context pack understood -- with one intended change, `.blade.php`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib.structure.native import langs  # noqa: E402

# what context.py:language() answered in 1.x, verbatim
LEGACY = {
    '.php': 'php', '.js': 'js', '.jsx': 'js', '.mjs': 'js', '.cjs': 'js',
    '.ts': 'js', '.tsx': 'js', '.go': 'go', '.java': 'java', '.kt': 'java',
    '.cs': 'java', '.rs': 'rust', '.c': 'c', '.cc': 'c', '.cpp': 'c', '.h': 'c',
    '.swift': 'java', '.scala': 'java', '.dart': 'java', '.py': 'py',
}


def case_table():
    print('case_table:')
    names = sorted(langs.LANGUAGES)
    check('eight languages are defined',
          names == ['blade', 'c', 'go', 'java', 'js', 'php', 'py', 'rust'], str(names))
    for name in names:
        definition = langs.definition(name)
        check('%s has a definition' % name, definition is not None and definition.name == name)
    check('an unknown language has none', langs.definition('zig') is None)


def case_extensions():
    print('case_extensions:')
    for ext, expected in sorted(LEGACY.items()):
        got = langs.language_of('src/app%s' % ext)
        check('%s stays %s' % (ext, expected), got == expected, 'got %r' % got)
    check('.blade.php is its own language now',
          langs.language_of('resources/views/home.blade.php') == 'blade')
    check('a plain .php file is unaffected',
          langs.language_of('app/Models/User.php') == 'php')
    check('the longest suffix wins over the shortest',
          langs.language_of('a.blade.php') == 'blade')
    check('case does not matter', langs.language_of('A.PHP') == 'php')
    check('an unknown extension is None', langs.language_of('Makefile') is None)
    check('a dotfile without extension is None', langs.language_of('.gitignore') is None)


def case_shapes():
    print('case_shapes:')
    php = langs.definition('php')
    check('php is brace-scoped', php.block_style == 'brace')
    check('php knows its tags', ('<?php', '?>') in php.tag_boundaries)
    check('php does not start in code', php.starts_in_code is False)
    check('php declares its heredoc form',
          any(spec.terminator == 'heredoc_line' for spec in php.multiline_strings))

    js = langs.definition('js')
    check('js declares the template literal',
          [spec.open for spec in js.multiline_strings] == ['`'])
    check('js starts in code', js.starts_in_code is True)
    check('js has no tag boundaries', not js.tag_boundaries)

    rust = langs.definition('rust')
    nestable = [nest for _open, _close, nest in rust.block_comment]
    check('rust block comments nest', nestable == [True], str(nestable))

    c = langs.definition('c')
    check('c block comments do not nest',
          all(not nest for _o, _c, nest in c.block_comment))

    py = langs.definition('py')
    check('python is indent-scoped', py.block_style == 'indent')
    check('python has except as its only block keyword beyond def/class',
          py.catch_keywords == ('except',) and py.loop_keywords == ()
          and py.branch_keywords == ())

    blade = langs.definition('blade')
    check('blade has no scope tree', blade.block_style is None)
    check('blade recognises its own comment in text',
          any(open_ == '{{--' for open_, _c, _n in blade.text_comment))
    check('blade enters code at @php', ('@php', '@endphp') in blade.tag_boundaries)
    check('blade keeps the php string rules inside tags',
          [d.open for d in blade.string_delims] == [d.open for d in php.string_delims])
    check('php interpolates inside double quotes only',
          [d.interpolation for d in php.string_delims] == [None, ('{$', '}')])
    check('php guards the attribute syntax',
          any(tok.text == '#' and tok.guard for tok in php.line_comment))


def case_patterns():
    print('case_patterns:')
    for name in ('php', 'js', 'go', 'java', 'rust', 'c', 'py'):
        definition = langs.definition(name)
        check('%s has a function pattern' % name, definition.function_pattern is not None)
    check('blade has none', langs.definition('blade').function_pattern is None)

    php = langs.definition('php')
    check('a php method header matches',
          php.function_pattern.search('    public function handle($req) {') is not None)
    js = langs.definition('js')
    check('an arrow function matches',
          js.function_pattern.search('const run = async (a) =>') is not None)
    check('a for loop is not a function',
          js.function_pattern.search('  for (const x of xs) {') is None)
    py = langs.definition('py')
    check('a def matches', py.function_pattern.match('    def run(self):') is not None)


def main():
    for case in (case_table, case_extensions, case_shapes, case_patterns):
        case()
    return finish('structure.native.langs')


if __name__ == '__main__':
    sys.exit(main())
