"""Source code that looks like source code, from a seed.

Two callers, one generator (PT-12). The property tests wrap `make_source` in
a Hypothesis strategy; the performance harness calls it directly with a seed
and a size, so `tests/perf/` needs no development dependency at all.

Roughly a quarter of the generated fragments are pathological on purpose --
an unterminated string, a stray brace, a heredoc whose terminator appears in
its own body. Generating only valid code would leave the failure paths, which
are the ones that must never raise, untested (PBT-07).
"""

import random

LANGUAGES = ('php', 'js', 'go', 'java', 'rust', 'c', 'py', 'blade')

_IDENTIFIERS = ('handle', 'run', 'value', 'user', 'items', 'cache', 'x', 'total')

_CODE = {
    'php': ['$%(id)s = %(num)d;', 'echo $%(id)s;', 'return $%(id)s;',
            '$%(id)s = "%(id)s";', "$%(id)s = '%(id)s';", '$%(id)s = "a {$b->c()} z";'],
    'js': ['const %(id)s = %(num)d;', 'return %(id)s;', 'let %(id)s = "%(id)s";',
           'const %(id)s = `a ${%(id)s} b`;', 'console.log(%(id)s);'],
    'go': ['%(id)s := %(num)d', 'return %(id)s', '%(id)s := "%(id)s"',
           '%(id)s := `raw %(id)s`'],
    'java': ['int %(id)s = %(num)d;', 'return %(id)s;', 'String %(id)s = "%(id)s";'],
    'rust': ['let %(id)s = %(num)d;', 'return %(id)s;', 'let %(id)s = r#"%(id)s"#;'],
    'c': ['int %(id)s = %(num)d;', 'return %(id)s;', 'char *%(id)s = "%(id)s";'],
    'py': ['%(id)s = %(num)d', 'return %(id)s', '%(id)s = "%(id)s"',
           '%(id)s = """doc %(id)s"""'],
    'blade': ['<p>{{ $%(id)s }}</p>', "<span>It's %(id)s</span>", '<div>%(id)s</div>'],
}

_COMMENTS = {
    'php': ['// %(id)s', '# %(id)s', '/* %(id)s */', '/* %(id)s\n   more */'],
    'js': ['// %(id)s', '/* %(id)s */', '/* %(id)s\n   more */'],
    'go': ['// %(id)s', '/* %(id)s */'],
    'java': ['// %(id)s', '/* %(id)s */'],
    'rust': ['// %(id)s', '/* outer /* inner */ %(id)s */'],
    'c': ['// %(id)s', '/* %(id)s */'],
    'py': ['# %(id)s'],
    'blade': ['{{-- %(id)s --}}'],
}

_BLOCKS = {
    'php': ['function %(id)s() {', 'foreach ($xs as $x) {', 'if ($%(id)s) {',
            'class %(id)s {', 'try {', '} catch (\\Throwable $e) {'],
    'js': ['function %(id)s() {', 'for (const x of xs) {', 'if (%(id)s) {',
           'class %(id)s {', 'try {', '} catch (e) {'],
    'go': ['func %(id)s() {', 'for i := range xs {', 'if %(id)s != nil {'],
    'java': ['public void %(id)s() {', 'for (int i = 0; i < 3; i++) {',
             'if (%(id)s) {', '} catch (Exception e) {'],
    'rust': ['fn %(id)s() {', 'for x in xs {', 'if %(id)s {'],
    'c': ['int %(id)s(void) {', 'for (i = 0; i < 3; i++) {', 'if (%(id)s) {'],
    'py': ['def %(id)s():', 'class %(id)s:', 'except ValueError:'],
    'blade': [],
}

_PATHOLOGICAL = {
    'php': ['$x = "unterminated;', '/* never closed', '$s = <<<SQL\nbody without end',
            'if (a) { missing_close();', "$q = 'it\\'s';", '$h = <<<SQL\nSQL body\nSQL;'],
    'js': ['const a = "unterminated;', '/* never closed', 'const t = `open ${x',
           'function f() { missing_close();', 'const s = "a\\"b";'],
    'go': ['s := "unterminated;', '/* never closed', 's := `open raw'],
    'java': ['String s = "unterminated;', '/* never closed'],
    'rust': ['let s = "unterminated;', '/* outer /* inner */'],
    'c': ['char *s = "unterminated;', '/* never closed'],
    'py': ['s = "unterminated;', 's = """open', 'def f():'],
    'blade': ["<p>It's</p>", '@php\n$x = "open;', '{{-- never closed'],
}

# How pathological a corpus is. The performance harness asks for 'sparse' or
# 'dense' comment and string density; the property tests take the default.
DENSITIES = {'sparse': 0.1, 'normal': 0.35, 'dense': 0.6}


def make_source(language, seed=0, lines=40, density='normal', broken=0.25):
    """Deterministic pseudo-source for `language`.

    The same arguments always produce the same text -- a local Random, never
    the module-level one, so nothing else in the process can shift it.
    """
    rng = random.Random(seed)
    weight = DENSITIES.get(density, DENSITIES['normal'])
    code = _CODE[language]
    comments = _COMMENTS[language]
    blocks = _BLOCKS[language]
    sick = _PATHOLOGICAL[language]

    out = []
    indent = 0
    open_blocks = 0
    while len(out) < lines:
        roll = rng.random()
        if sick and roll < broken:
            out.extend(_render(rng, sick, indent))
        elif roll < broken + weight:
            out.extend(_render(rng, comments or code, indent))
        elif blocks and roll < broken + weight + 0.2 and open_blocks < 3:
            out.extend(_render(rng, blocks, indent))
            indent += 1
            open_blocks += 1
        else:
            out.extend(_render(rng, code, indent))
            if open_blocks and rng.random() < 0.3:
                indent -= 1
                open_blocks -= 1
                if language != 'py':
                    out.append('    ' * indent + '}')
    if language != 'py':
        out.extend('    ' * i + '}' for i in reversed(range(open_blocks)))
    return '\n'.join(out[:lines]) + '\n'


def _render(rng, choices, indent):
    template = rng.choice(choices)
    body = template % {'id': rng.choice(_IDENTIFIERS), 'num': rng.randrange(100)}
    pad = '    ' * indent
    return [pad + line for line in body.split('\n')]


def prologue(language):
    """What a file of this language has to start with, if anything."""
    return '<?php\n' if language == 'php' else ''


def make_file(language, seed=0, lines=40, density='normal', broken=0.25):
    return prologue(language) + make_source(language, seed, lines, density, broken)
