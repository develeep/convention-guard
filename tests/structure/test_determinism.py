#!/usr/bin/env python3
"""The structure layer must answer the same on every machine.

`dismissed.yaml` is committed and its keys come from detection, so a result
that shifts with the interpreter's hash seed would give one teammate a
dismissal that does not work for another (NFR-02.3, US-05).

Two checks, because neither is enough alone: a static one that catches the
usual suspects in this package, and a dynamic one that runs the analysis under
two different hash seeds and compares -- which also covers whatever the
static check cannot see.

A third check keeps `langs.py` the only file that knows a language by name
(NR-18): scanning or scoping must branch on the definition, never on 'php'.
"""
import ast
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from helpers import ROOT, check, finish  # noqa: E402
from lib.structure.native.langs import LANGUAGES  # noqa: E402

PACKAGE = os.path.join(ROOT, 'scripts', 'lib', 'structure')
FORBIDDEN_CALLS = {'hash', 'id'}
FORBIDDEN_MODULES = {'random', 'time', 'datetime', 'uuid', 'socket'}
LANGUAGE_FREE = ('native/mask.py', 'native/scopes.py', 'conditions.py', 'model.py',
                 'backend.py')


def sources():
    for dirpath, dirnames, filenames in os.walk(PACKAGE):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in sorted(filenames):
            if name.endswith('.py'):
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as handle:
                    yield os.path.relpath(path, PACKAGE), handle.read()


def case_no_unstable_apis():
    print('case_no_unstable_apis:')
    findings = []
    for relpath, text in sources():
        tree = ast.parse(text, relpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in FORBIDDEN_CALLS:
                findings.append('%s:%d %s()' % (relpath, node.lineno, node.func.id))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in FORBIDDEN_MODULES:
                        findings.append('%s:%d import %s' % (relpath, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split('.')[0] in FORBIDDEN_MODULES:
                    findings.append('%s:%d from %s' % (relpath, node.lineno, node.module))
            elif isinstance(node, ast.Attribute) and node.attr == 'environ':
                findings.append('%s:%d os.environ' % (relpath, node.lineno))
            elif isinstance(node, (ast.For, ast.comprehension)):
                iterated = node.iter
                if isinstance(iterated, (ast.Set, ast.SetComp)) or (
                        isinstance(iterated, ast.Call)
                        and isinstance(iterated.func, ast.Name)
                        and iterated.func.id in ('set', 'frozenset')):
                    line = getattr(node, 'lineno', getattr(iterated, 'lineno', 0))
                    findings.append('%s:%d iterating a set' % (relpath, line))
    check('nothing in the package depends on hash seed, clock or randomness',
          not findings, '; '.join(findings))


def case_languages_live_in_one_file():
    print('case_languages_live_in_one_file:')
    names = sorted(LANGUAGES)
    findings = []
    for relpath, text in sources():
        if relpath.replace(os.sep, '/') not in LANGUAGE_FREE:
            continue
        tree = ast.parse(text, relpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in names:
                findings.append('%s:%d %r' % (relpath, node.lineno, node.value))
    check('only langs.py names a language (NR-18)', not findings, '; '.join(findings))


DUMP = r'''
import json, os, sys
sys.path.insert(0, os.path.join(%r, 'scripts'))
sys.path.insert(0, os.path.join(%r, 'tests'))
from helpers import corpus
from lib import structure

def shape(node):
    return [node.kind, node.start_line, node.end_line,
            [shape(child) for child in node.children]]

out = []
for language in corpus.LANGUAGES:
    for seed in (1, 7, 13):
        text = corpus.make_file(language, seed=seed, lines=60)
        fs = structure.analyze(text, language)
        out.append([language, seed, fs.ok, fs.reason,
                    [list(s) for s in fs.comments], [list(s) for s in fs.strings],
                    shape(fs.root)])
print(json.dumps(out, ensure_ascii=False))
'''


def case_hash_seed_does_not_change_the_answer():
    print('case_hash_seed_does_not_change_the_answer:')
    script = DUMP % (ROOT, ROOT)
    results = []
    for seed in ('0', '1'):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.run([sys.executable, '-c', script], capture_output=True,
                              text=True, env=env, cwd=ROOT)
        if proc.returncode != 0:
            check('the dump runs under PYTHONHASHSEED=%s' % seed, False,
                  proc.stderr.strip()[-300:])
            return
        results.append(json.loads(proc.stdout))
    check('two hash seeds produce identical structures', results[0] == results[1],
          'first difference: %s' % _first_difference(results[0], results[1]))


def _first_difference(left, right):
    for a, b in zip(left, right):
        if a != b:
            return '%s vs %s' % (str(a)[:120], str(b)[:120])
    return 'length %d vs %d' % (len(left), len(right))


def main():
    for case in (case_no_unstable_apis, case_languages_live_in_one_file,
                 case_hash_seed_does_not_change_the_answer):
        case()
    return finish('structure determinism')


if __name__ == '__main__':
    sys.exit(main())
