#!/usr/bin/env python3
"""The node tables (structure/nodes.py) against the pinned grammars.

- every node name in a language's row exists in a grammar that row is used
  with -- a grammar upgrade that renames one fails here first, not as a
  silent "no comments found" in someone's repo
- a representative file per language produces every category at least once
- callback iteration is recognised for every listed call shape
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, needs_engine  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure import nodes  # noqa: E402

NODE_KEYS = ('comment', 'string', 'literal_parts', 'string_containers', 'function', 'loop',
             'class', 'catch', 'branch', 'argument_wrappers', 'decorated')

SAMPLES = {
    'js': ("// c\nclass A { m() { try { for (const x of y) { f(`a ${x}`, /r/g); } }"
           " catch (e) { log(e); } } }\nxs.forEach((x) => { g(x); });\n"),
    'ts': ("// c\nclass A { m(): void { try { for (const x of y) { f(`a ${x}`); } }"
           " catch (e) { log(e); } } }\n"),
    'tsx': ("// c\nconst C = () => { try { for (const x of y) { f('s'); } }"
            " catch (e) { log(e); } return <p>t</p>; };\nclass K {}\n"),
    'php': ("<?php\n// c\nclass A { public function m() { try { foreach ($a as $b) {"
            " f(\"x {$b}\"); } } catch (\\Throwable $e) { log($e); } } }\n"
            "$a->each(function ($x) { g($x); });\n"),
    'blade': "{{-- c --}}\n@foreach ($a as $b)\n{{ 'x' }}\n@endforeach\n",
    'py': ("# c\nclass A:\n    def m(self):\n        try:\n            for x in y:\n"
           "                f(f'a {x}')\n        except Exception:\n            log()\n"),
}
CALLBACKS = {
    'js': ['xs.map(x => «run»(x));', 'xs.forEach(function (x) { «run»(x); });'],
    'ts': ['xs.filter((x: number) => «run»(x));'],
    'php': ['<?php\n$xs->map(fn($x) => «run»($x));', '<?php\narray_map(fn($x) => «run»($x), $xs);',
            '<?php\n$xs?->each(function ($x) { «run»($x); });'],
    'py': ['ys = map(lambda x: «run»(x), xs)', 'ys = sorted(xs, key=lambda x: «run»(x))'],
}


def grammars_of(row_name):
    return sorted({g for lang, (row, g) in nodes.LANGUAGES.items() if row is row_name})


def case_names_exist():
    print('case_names_exist:')
    from lib.engine import loader
    engine = loader.get()
    for lang, (row, grammar) in sorted(nodes.LANGUAGES.items()):
        grammars = sorted({g for _l, (r, g) in nodes.LANGUAGES.items() if r is row})
        languages = [engine.language(g) for g in grammars]
        names = set(row['calls']) | set(row['member_name'])
        for key in NODE_KEYS:
            names |= set(row[key])
        missing = [n for n in sorted(names)
                   if not any(language.id_for_node_kind(n, True) for language in languages)]
        check('%s: every node name exists in %s' % (lang, '/'.join(grammars)), not missing,
              missing)


def kinds_in(node, out):
    out.add(node.kind)
    for child in node.children:
        kinds_in(child, out)
    return out


def case_every_category_shows_up():
    print('case_every_category_shows_up:')
    for lang, text in sorted(SAMPLES.items()):
        fs = structure.analyze(text, lang)
        found = kinds_in(fs.root, set())
        want = {'loop'} if lang == 'blade' else {'function', 'loop', 'class', 'catch'}
        check('%s: parses clean' % lang, fs.ok and not fs.errors, (fs.reason, fs.errors))
        check('%s: comments and literal text are found' % lang,
              bool(fs.comments) and bool(fs.strings), (fs.comments, fs.strings))
        check('%s: %s are found' % (lang, '/'.join(sorted(want))), want <= found, sorted(found))


def case_callbacks():
    print('case_callbacks:')
    for lang, samples in sorted(CALLBACKS.items()):
        for sample in samples:
            at = sample.index('«')
            text = sample.replace('«', '').replace('»', '')
            fs = structure.analyze(text, lang)
            kinds = {n.kind for n in fs.scopes_around(at)}
            check('%s: %s is a loop and a function' % (lang, sample.split('\n')[-1][:40]),
                  {'loop', 'function'} <= kinds, sorted(kinds))


def main():
    if needs_engine('node tables'):
        case_names_exist()
        case_every_category_shows_up()
        case_callbacks()
    return finish('노드 대응표')


if __name__ == '__main__':
    sys.exit(main())
