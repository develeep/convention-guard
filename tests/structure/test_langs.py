#!/usr/bin/env python3
"""Language definitions: the one file a new language should touch.

`domain-entities.md` §6. The extension table is inherited from
`context.py:BRACE_LANGS`, so the regression case pins every extension the 1.x
context pack understood -- with the intended changes: `.blade.php`, `.kt`
(its own row since R1, so its statement grammar can differ from Java's), and
since R9 `.ts` (no JSX), `.swift`, `.cs` and `.dart` (their own literals).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish  # noqa: E402
from lib.structure.native import langs, mask  # noqa: E402

# what context.py:language() answered in 1.x, verbatim
LEGACY = {
    '.php': 'php', '.js': 'js', '.jsx': 'js', '.mjs': 'js', '.cjs': 'js',
    '.ts': 'ts', '.tsx': 'js', '.go': 'go', '.java': 'java', '.kt': 'kotlin',
    '.cs': 'csharp', '.rs': 'rust', '.c': 'c', '.cc': 'c', '.cpp': 'c', '.h': 'c',
    '.swift': 'swift', '.scala': 'java', '.dart': 'dart', '.py': 'py',
}


def case_table():
    print('case_table:')
    names = sorted(langs.LANGUAGES)
    check('fifteen languages are defined',
          names == ['blade', 'c', 'csharp', 'dart', 'go', 'java', 'js', 'kotlin', 'php', 'py',
                    'rust', 'svelte', 'swift', 'ts', 'vue'], str(names))
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
    check('python blocks are def, class, except and for/while',
          [kind for kind, _ in py.indent_headers] == ['function', 'class', 'catch', 'loop'],
          str(py.indent_headers))
    check('python tries the standard parser first', py.parser == 'python_ast')

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
    for name in ('php', 'js', 'ts', 'go', 'java', 'kotlin', 'swift', 'csharp', 'dart', 'rust', 'c'):
        definition = langs.definition(name)
        check('%s has a function pattern' % name, definition.function_pattern is not None)
    # python blocks come from `ast` or `indent_headers`, blade has none (R23k)
    for name in ('py', 'blade'):
        check('%s has none' % name, langs.definition(name).function_pattern is None)

    php = langs.definition('php')
    check('a php method header matches',
          php.function_pattern.search('    public function handle($req) {') is not None)
    js = langs.definition('js')
    check('an arrow function matches',
          js.function_pattern.search('const run = async (a) =>') is not None)
    check('a for loop is not a function',
          js.function_pattern.search('  for (const x of xs) {') is None)


# R23a: extensions the 1.x table missed
ADDED = {
    '.mts': 'ts', '.cts': 'ts', '.kts': 'kotlin', '.pyi': 'py',
    '.hpp': 'c', '.hh': 'c', '.hxx': 'c', '.cxx': 'c',
    '.vue': 'vue', '.svelte': 'svelte',
}
# what a stack's linter may also be handed without it being code
NOT_CODE = {'json', 'jsonc', 'css', 'scss', 'md', 'yaml', 'yml'}
_GLOB_EXTENSIONS = re.compile(r'\.(\w+)(?:$|[,}\]"\'])|\{([\w,]+)\}')


def case_added_extensions():
    print('case_added_extensions:')
    for ext, expected in sorted(ADDED.items()):
        got = langs.language_of('src/app%s' % ext)
        check('%s is %s' % (ext, expected), got == expected, 'got %r' % got)


def case_template_islands():
    """A .vue / .svelte file is markup with a script island, like Blade."""
    print('case_template_islands:')
    text = ("<template>\n  <p>It's {{ user.name }}</p>\n</template>\n"
            "<script setup lang=\"ts\">\nconst a = 'ok'; // note\n</script>\n")
    for language in ('vue', 'svelte'):
        res = mask.scan(text, langs.definition(language))
        got = [text[s.start:s.end] for s in res.strings]
        check('%s markup is text, the script is code' % language,
              res.ok and "'ok'" in got and [text[s.start:s.end] for s in res.comments] == ['// note'],
              '%s %s' % (res.reason, got))


def case_globs_have_languages():
    """Every code extension a bundled rule or stack names has a definition --
    otherwise its structure conditions are quietly unchecked (R23a)."""
    print('case_globs_have_languages:')
    missing = []
    for folder in ('rules', 'stacks'):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for name in sorted(files):
                if not name.endswith('.yaml'):
                    continue
                with open(os.path.join(dirpath, name), encoding='utf-8') as handle:
                    for line in handle:
                        if 'files:' not in line:
                            continue
                        for dotted, braced in _GLOB_EXTENSIONS.findall(line):
                            for ext in (braced.split(',') if braced else [dotted]):
                                if ext and ext not in NOT_CODE \
                                        and langs.language_of('x.%s' % ext) is None:
                                    missing.append('%s: .%s' % (name, ext))
    check('every globbed code extension has a language', not missing, ', '.join(missing))


def main():
    for case in (case_table, case_extensions, case_shapes, case_patterns,
                 case_added_extensions, case_template_islands, case_globs_have_languages):
        case()
    return finish('structure.native.langs')


if __name__ == '__main__':
    sys.exit(main())
