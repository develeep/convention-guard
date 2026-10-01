#!/usr/bin/env python3
"""The scope tree: which block is a function, a loop, a catch -- and where it ends.

`business-rules.md` SR-13~SR-20 for the classification, NR-10/NR-11 for the
guards that keep a minified line from reaching the header regex.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib.structure.native import langs, mask, scopes  # noqa: E402

PHP = '<?php\n'


def tree(text, language='php'):
    definition = langs.definition(language)
    return scopes.build(text, definition, mask.scan(text, definition))


def flatten(node, out=None):
    out = [] if out is None else out
    for child in node.children:
        out.append(child)
        flatten(child, out)
    return out


def kinds(node):
    return [child.kind for child in flatten(node)]


def case_kinds():
    print('case_kinds:')
    text = PHP + '''class A {
    public function handle($r) {
        foreach ($r as $x) {
            if ($x) { continue; }
        }
        try { go(); } catch (\\Throwable $e) { }
    }
}
'''
    root = tree(text)
    check('the root is the file', root.kind == 'file')
    got = kinds(root)
    check('every block kind is recognised',
          got == ['class', 'function', 'loop', 'branch', 'catch'], str(got))

    names = kinds(tree('function f() {\n  for (;;) { if (a) {} else if (b) {} }\n}\n', 'js'))
    check('else if is one branch, not two',
          names == ['function', 'loop', 'branch', 'branch'], str(names))

    got = kinds(tree('const conf = { a: 1, b: { c: 2 } };\n', 'js'))
    check('object literals make no nodes (SR-18)', got == [], str(got))

    got = kinds(tree('function f() {\n  { const x = 1; function g() {} }\n}\n', 'js'))
    check('an anonymous block is transparent to nesting',
          got == ['function', 'function'], str(got))


def case_bounds():
    print('case_bounds:')
    text = PHP + 'function f() {\n    return 1;\n}\n'
    root = tree(text)
    func = flatten(root)[0]
    check('the node starts at the header line', func.start_line == 2, str(func.start_line))
    check('the node ends at the closing brace line', func.end_line == 4, str(func.end_line))
    body = text[func.body.start:func.body.end]
    check('the body excludes the braces', body == '\n    return 1;\n', repr(body))

    text = PHP + '''function outer(
    $a,
    $b
) {
    return 1;
}
'''
    func = flatten(tree(text))[0]
    check('a multi-line signature starts at its first line',
          func.start_line == 2, str(func.start_line))

    text = PHP + 'function f() {\n    return 1;\n'
    func = flatten(tree(text))[0]
    check('a block left open closes at the last line (D-2)',
          func.end_line == 3 and func.body.end == len(text), str(func.end_line))

    text = PHP + 'interface I {\n    public function f();\n}\n'
    got = kinds(tree(text))
    check('a declaration without a body makes no function node',
          got == ['class'], str(got))


def case_masking_is_respected():
    print('case_masking_is_respected:')
    text = PHP + 'function f() {\n    $s = "}";  // }\n    return 1;\n}\n'
    func = flatten(tree(text))[0]
    check('braces in strings and comments do not close the block (D-1)',
          func.end_line == 5, str(func.end_line))

    text = PHP + '$doc = "function ghost() {";\nfunction real() { return 1; }\n'
    names = [(n.kind, n.start_line) for n in flatten(tree(text))]
    check('a header inside a string is not a header (D-3)',
          names == [('function', 3)], str(names))

    text = '<div>{ not code }</div>\n' + PHP + 'function f() { return 1; }\n'
    names = [(n.kind, n.start_line) for n in flatten(tree(text))]
    check('braces in template text are not code (SR-11)',
          names == [('function', 3)], str(names))


def case_callback_iteration():
    """`map`/`each` are loops too -- FR-01.2 lists them next to `for`."""
    print('case_callback_iteration:')
    text = 'const out = xs.map(x => {\n    return x.load();\n});\n'
    root = tree(text, 'js')
    # R2: the callback is a function as well, like a `function` callback always was
    check('an arrow callback iteration is a loop wrapping a function',
          kinds(root) == ['loop', 'function'], str(kinds(root)))

    text = 'xs.forEach(function (x) {\n    x.load();\n});\n'
    root = tree(text, 'js')
    check('a function callback is a loop wrapping a function',
          kinds(root) == ['loop', 'function'], str(kinds(root)))
    fs_like = flatten(root)[1]
    check('the inner function covers the same block',
          fs_like.start_line == flatten(root)[0].start_line
          and fs_like.end_line == flatten(root)[0].end_line)

    text = PHP + '$users->each(function ($u) {\n    $u->posts;\n});\n'
    check('a laravel collection callback is a loop wrapping a function',
          kinds(tree(text)) == ['loop', 'function'], str(kinds(tree(text))))

    text = PHP + '$rows = array_map(function ($r) {\n    return $r->id;\n}, $rows);\n'
    check('array_map counts too',
          kinds(tree(text)) == ['loop', 'function'], str(kinds(tree(text))))

    text = 'function handle() {\n    return 1;\n}\n'
    check('a plain function is still only a function',
          kinds(tree(text, 'js')) == ['function'], str(kinds(tree(text, 'js'))))

    text = 'const m = new Map();\nfunction mapper() {\n    return 1;\n}\n'
    check('a function whose name contains map is not a loop',
          kinds(tree(text, 'js')) == ['function'], str(kinds(tree(text, 'js'))))

    # the ported languages keep 1.x behaviour (SR-41): no callback iteration
    text = 'class A {\n    void f() {\n        xs.forEach(x -> {\n            g(x);\n        });\n    }\n}\n'
    got = kinds(tree(text, 'java'))
    check('java keeps its 1.x classification', 'loop' not in got, str(got))


def case_python():
    print('case_python:')
    text = '''class A:
    def run(self):
        for x in y:
            if x:
                pass
        try:
            go()
        except ValueError:
            pass
'''
    got = kinds(tree(text, 'py'))
    # R1: loops too -- `in_scope: loop` used to reject every python file
    check('python makes class, function, loop and catch nodes',
          got == ['class', 'function', 'loop', 'catch'], str(got))

    node = flatten(tree(text, 'py'))[1]
    check('a python block ends at the dedent, trailing blanks included as in 1.x',
          (node.start_line, node.end_line) == (2, 10), str((node.start_line, node.end_line)))

    text = 'def f():\n    return 1\n\n\ndef g():\n    return 2\n'
    spans = [(n.start_line, n.end_line) for n in flatten(tree(text, 'py'))]
    check('blank lines do not end a block (context.py:_python_block, verbatim)',
          spans == [(1, 4), (5, 7)], str(spans))

    text = 'DOC = """\ndef ghost():\n    pass\n"""\ndef real():\n    pass\n'
    spans = [(n.start_line, n.end_line) for n in flatten(tree(text, 'py'))]
    check('a def inside a triple-quoted string is ignored',
          spans == [(5, 7)], str(spans))


def around(text, language, needle):
    """Scope kinds around the line holding `needle`, outermost first, file excluded."""
    root = tree(text, language)
    lineno = text[:text.index(needle)].count('\n') + 1
    path, node = [], root
    while True:
        for child in node.children:
            if child.contains_line(lineno):
                path.append(child.kind)
                node = child
                break
        else:
            return path


def case_header_tokens():
    """R1: the kind comes from the header's own tokens, not a keyword anywhere in it."""
    print('case_header_tokens:')
    text = 'package m\nfunc f() {\n\tfor i := 0; i < n; i++ {\n\t\tdb.Query(q)\n\t}\n}\n'
    got = around(text, 'go', 'db.Query')
    check('a go three-clause for is a loop', got == ['function', 'loop'], str(got))

    text = 'package m\nfunc f() {\n\tif v, ok := m[k]; ok {\n\t\tuse(v)\n\t}\n}\n'
    got = around(text, 'go', 'use(v)')
    check('a go if with an init statement is a branch', got == ['function', 'branch'], str(got))

    for prev in ('\tdone := make(chan struct{})\n', '\tdone := make(chan bool)\n'):
        text = 'package m\nfunc f(xs []int) {\n%s\tfor _, x := range xs {\n\t\tgo1(x)\n\t}\n}\n' % prev
        got = around(text, 'go', 'go1(x)')
        check('a go loop after %r is still a loop' % prev.strip(),
              got == ['function', 'loop'], str(got))

    text = 'async function f() {\n  const u = await repo.find({\n    where: { id: await getId() },\n  });\n}\n'
    got = around(text, 'js', 'await getId')
    check('an object literal argument is not an iteration', 'loop' not in got, str(got))

    text = 'function f() {\n  if (xs.some(x => x.ok)) {\n    go();\n  }\n}\n'
    got = around(text, 'js', 'go()')
    check('a closed iteration call in a condition is not a loop',
          got == ['function', 'branch'], str(got))

    text = 'function f(n) {\n  if (n.class === "a") {\n    go();\n  }\n}\n'
    got = around(text, 'js', 'go()')
    check('a member named class is not a class', got == ['function', 'branch'], str(got))

    for method in ('catch', 'finally'):
        text = 'function f() {\n  p.%s(function (e) {\n    go();\n  });\n}\n' % method
        got = around(text, 'js', 'go()')
        check('.%s(cb) is not a catch block' % method, 'catch' not in got, str(got))

    for semi in ('', ';'):
        text = ('function f(users) {\n  const ids = users.map(u => u.id)%s\n'
                '  if (ids.length) {\n    go()\n  }\n}\n' % semi)
        got = around(text, 'js', 'go()')
        check('an if after a map call is a branch (semicolon=%r)' % semi,
              got == ['function', 'branch'], str(got))

    text = 'function f() {\n  xs.forEach((x) => {\n    save(x);\n  });\n}\n'
    got = around(text, 'js', 'save(x)')
    check('an arrow callback of an iteration method is still a loop',
          got == ['function', 'loop', 'function'], str(got))

    text = PHP + 'function f() {\n    foreach ([User::class, Post::class] as $m) {\n        $m::all();\n    }\n}\n'
    got = around(text, 'php', '$m::all')
    check('::class inside a foreach header is not a class',
          got == ['function', 'loop'], str(got))

    text = 'class A {\n  fun f() {\n    items.forEach {\n      repo.save(it)\n    }\n  }\n}\n'
    got = around(text, 'kotlin', 'repo.save')
    check('a kotlin trailing-lambda forEach is a loop',
          got == ['class', 'function', 'loop'], str(got))

    text = 'fun f() {\n    repeat(3) {\n        go()\n    }\n    xs.fold(0) { acc, x ->\n        acc + x\n    }\n}\n'
    check('kotlin repeat(n) { is a loop', around(text, 'kotlin', 'go()') == ['function', 'loop'],
          str(around(text, 'kotlin', 'go()')))
    check('kotlin .fold(0) { is a loop', around(text, 'kotlin', 'acc + x') == ['function', 'loop'],
          str(around(text, 'kotlin', 'acc + x')))

    text = 'fun f() {\n    items\n        .forEach {\n            go(it)\n        }\n}\n'
    got = around(text, 'kotlin', 'go(it)')
    check('a kotlin chain continued on the next line is one statement',
          got == ['function', 'loop'], str(got))

    for text, needle in (('def f(xs):\n    for x in xs:\n        db.query(x)\n', 'db.query'),
                         ('def f():\n    while True:\n        db.query(1)\n', 'db.query'),
                         ('async def f(xs):\n    async for x in xs:\n        await db.query(x)\n',
                          'await db'),
                         ('def f(xs):\n    return [db.query(x)\n            for x in xs]\n',
                          'db.query')):
        got = around(text, 'py', needle)
        check('python %r is a loop' % text.split('\n')[1].strip()[:12],
              got == ['function', 'loop'], str(got))


def case_functions():
    """R2: methods, callbacks and lambdas are functions; control headers are not."""
    print('case_functions:')
    cases = (
        ('a js class method', 'js',
         'class A {\n  run(a) {\n    go();\n  }\n}\n', ['class', 'function']),
        ('a js method with a multi-line signature', 'js',
         'class A {\n  run(\n    a,\n  ) {\n    go();\n  }\n}\n', ['class', 'function']),
        ('an arrow callback', 'js',
         "app.get('/', async (req, res) => {\n  go();\n});\n", ['function']),
        ('a class-field arrow', 'js',
         'class A {\n  handle = async () => {\n    go();\n  }\n}\n', ['class', 'function']),
        ('a call line before an if in semicolon-less js', 'js',
         'function f() {\n  save(x)\n  if (y) {\n    go()\n  }\n}\n', ['function', 'branch']),
        ('a php anonymous function', 'php',
         PHP + '$f = function ($x) use ($y) {\n    go();\n};\n', ['function']),
        ('a go deferred func literal', 'go',
         'package m\nfunc f() {\n\tdefer func() {\n\t\tgo()\n\t}()\n}\n', ['function', 'function']),
        ('a rust closure', 'rust',
         'fn f() {\n    let g = |x| {\n        go(x)\n    };\n}\n', ['function', 'function']),
        ('a java lambda', 'java',
         'class A {\n  void f() {\n    run(() -> {\n      go();\n    });\n  }\n}\n',
         ['class', 'function', 'function']),
        ('a java switch arm is not a lambda', 'java',
         'class A {\n  void f(int x) {\n    switch (x) {\n      case 1 -> {\n        go();\n'
         '      }\n    }\n  }\n}\n', ['class', 'function', 'branch', 'branch']),
        ('a java multi-line signature', 'java',
         'class A {\n  public void f(\n      int a) {\n    go();\n  }\n}\n', ['class', 'function']),
        ('a java throws clause on the next line', 'java',
         'class A {\n  public void f()\n      throws IOException {\n    go();\n  }\n}\n',
         ['class', 'function']),
        ('a swift function with a return arrow', 'java',
         'func f() -> Int {\n    return go()\n}\n', ['function']),
        ('a c else-if is a branch, not a function', 'c',
         'void f() {\n  if (a) {\n  } else if (b) {\n    go();\n  }\n}\n', ['function', 'branch']),
    )
    for name, language, text, expected in cases:
        got = around(text, language, 'go(')
        check(name, got == expected, str(got))


def case_python_fallback():
    """A file `ast` cannot read still gets its loops from the indentation."""
    print('case_python_fallback:')
    text = 'def f(xs):\n    for x in xs:\n        db.query(x)\n    print "py2"\n'
    got = around(text, 'py', 'db.query')
    check('a syntax error falls back to the indent rules', got == ['function', 'loop'], str(got))


def case_guards():
    print('case_guards:')
    long_line = 'x' * 2500
    text = PHP + 'const A = [%s];\nfunction real() { return 1; }\n' % long_line
    names = [n.kind for n in flatten(tree(text))]
    check('a long line does not stop the shorter headers around it',
          names == ['function'], str(names))

    text = PHP + 'function minified() { var a = [%s]; }\n' % long_line
    root = tree(text)
    check('a header on a very long line is not recognised (NR-10)',
          kinds(root) == [], str(kinds(root)))

    header = 'const data = [%s]\n' % ('1,' * 1200)
    text = PHP + header + 'function pulled() { return 1; }\n'
    names = [n.kind for n in flatten(tree(text))]
    check('a header that reaches back over a long line still resolves (NR-11)',
          names == ['function'], str(names))


def case_blade():
    print('case_blade:')
    text = "<p>x</p>\n@php\nfunction f() { return 1; }\n@endphp\n"
    root = tree(text, 'blade')
    check('blade has no scope tree at all (CQ2=B)',
          root.kind == 'file' and root.children == ())


def main():
    for case in (case_kinds, case_bounds, case_masking_is_respected,
                 case_callback_iteration, case_python, case_header_tokens, case_functions,
                 case_python_fallback, case_guards, case_blade):
        case()
    return finish('structure.native.scopes')


if __name__ == '__main__':
    sys.exit(main())
