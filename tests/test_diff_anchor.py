#!/usr/bin/env python3
"""Regression tests for what "this change" means.

Every case here was a real miss:

1. `git add` on a new file removed it from `ls-files --others`, so every
   absence rule (strict_types, namespace) silently stopped firing.
2. An added line whose content starts with `++` was parsed as a diff header:
   the line vanished and every line number after it in the hunk shifted by
   one, which puts the wrong line number in front of the agent.
3. `base_ref: auto` only ran when the HEAD diff was empty, so a change
   committed mid-session was invisible as soon as the same file also had an
   uncommitted edit.
4. `paired` triggers never reached applies(), so a Laravel rule fired in a Go
   repo.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from lib import engine, gitdiff, rules as rulelib, stack as stacklib  # noqa: E402

FAILED = []


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def git(tmp, *args):
    return subprocess.run(['git', '-C', tmp] + list(args), check=True,
                          capture_output=True, text=True)


def write(tmp, rel, body):
    path = os.path.join(tmp, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)


def make_repo(tmp, marker='composer.json', content='{"require":{"laravel/framework":"^11.0"}}'):
    git(tmp, 'init', '-q')
    git(tmp, 'config', 'user.email', 't@t')
    git(tmp, 'config', 'user.name', 't')
    write(tmp, marker, content)
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'init')


def rules_for(tmp, tags, changed, new_files):
    all_rules, _notes, _cfg = rulelib.load_all(tmp, root=ROOT)
    ctx = engine.Context(tmp, changed, new_files, tags, {})
    return all_rules, ctx


def hit_ids(tmp, tags, changed, new_files):
    all_rules, ctx = rules_for(tmp, tags, changed, new_files)
    return {h['rule']['id'] for h in engine.collect(all_rules, ctx, 5)}


# ---------------------------------------------------------------- cases

def case_staged_new_file(tmp):
    make_repo(tmp)
    rel = 'app/Http/Controllers/NewController.php'
    write(tmp, rel, '<?php\nclass NewController {}\n')   # no namespace, no strict_types

    changed = gitdiff.added_lines(tmp, [rel])
    ids = hit_ids(tmp, {'php', 'laravel'}, changed, gitdiff.new_files(tmp) & set(changed))
    check('untracked new file fires absence rules',
          'core/php-strict-types-required' in ids, ids)

    git(tmp, 'add', rel)
    changed = gitdiff.added_lines(tmp, [rel])
    fresh = gitdiff.new_files(tmp)
    check('staged new file is still new', rel in fresh, fresh)
    ids = hit_ids(tmp, {'php', 'laravel'}, changed, fresh & set(changed))
    check('staged new file fires absence rules',
          'core/php-strict-types-required' in ids, ids)


def case_plus_prefixed_line(tmp):
    make_repo(tmp)
    write(tmp, 'doc.md', 'a\nb\nc\n')
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'doc')
    write(tmp, 'doc.md', 'a\n+++ marker\nZZZ\nb\nc\n')

    lines = gitdiff.added_lines(tmp, ['doc.md']).get('doc.md') or []
    check('line starting with ++ is not dropped',
          (2, '+++ marker') in lines, lines)
    check('following line keeps its real number', (3, 'ZZZ') in lines, lines)


def case_base_ref_union(tmp):
    make_repo(tmp)
    rel = 'app/Svc/Legacy.php'
    write(tmp, rel, '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass L {\n'
                    '    public function a() { return 1; }\n}\n')
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'base')
    git(tmp, 'branch', '-M', 'main')
    git(tmp, 'checkout', '-q', '-b', 'feat')

    write(tmp, rel, '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass L {\n'
                    '    public function a() { dd(1); }\n}\n')
    git(tmp, 'add', rel)
    git(tmp, 'commit', '-q', '-m', 'committed mid-session')
    # an unrelated uncommitted edit, so the HEAD diff is non-empty
    write(tmp, rel, '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass L {\n'
                    '    public function a() { dd(1); }\n'
                    '    public function b() { return 2; }\n}\n')

    base = gitdiff.resolve_base_ref(tmp, 'auto')
    check('auto base ref resolves', bool(base), base)
    lines = gitdiff.added_lines(tmp, [rel], base).get(rel) or []
    texts = [text for _, text in lines]
    check('committed-mid-session line is visible',
          any('dd(1)' in t for t in texts), texts)
    check('uncommitted line is visible too',
          any('function b' in t for t in texts), texts)


def case_paired_stack_gate(tmp):
    make_repo(tmp, marker='go.mod', content='module x\n\ngo 1.22\n')
    write(tmp, 'routes/api.php', "<?php\nRoute::get('/x');\n")
    detected = stacklib.detect(ROOT, tmp)
    check('repo detected as go only', detected['stacks'] == ['go'], detected['stacks'])

    changed = gitdiff.added_lines(tmp, ['routes/api.php'])
    ids = hit_ids(tmp, detected['tags'], changed, gitdiff.new_files(tmp) & set(changed))
    check('laravel paired rule stays out of a go repo',
          'core/laravel-route-needs-test' not in ids, ids)

    # and still fires where it belongs
    other = tempfile.mkdtemp()
    try:
        make_repo(other)
        write(other, 'routes/api.php', "<?php\nRoute::get('/x');\n")
        changed = gitdiff.added_lines(other, ['routes/api.php'])
        ids = hit_ids(other, {'php', 'laravel'}, changed,
                      gitdiff.new_files(other) & set(changed))
        check('laravel paired rule fires in a laravel repo',
              'core/laravel-route-needs-test' in ids, ids)
    finally:
        shutil.rmtree(other, ignore_errors=True)


def case_batched_matches_per_file(tmp):
    """The batched diff must agree with a per-file diff, file for file."""
    make_repo(tmp)
    rels = ['src/f%d.php' % i for i in range(5)]
    for rel in rels:
        write(tmp, rel, '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass A {}\n')
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'bulk')
    for i, rel in enumerate(rels):
        with open(os.path.join(tmp, rel), 'a', encoding='utf-8') as fh:
            fh.write('// touched %d\n' % i)

    batched = gitdiff.added_lines(tmp, rels)
    one_by_one = {}
    for rel in rels:
        got = gitdiff.diff_lines(tmp, [rel], ['HEAD'])
        one_by_one.update(got)
    check('batched diff equals per-file diff', batched == one_by_one,
          '%r != %r' % (batched, one_by_one))


CASES = [case_staged_new_file, case_plus_prefixed_line, case_base_ref_union,
         case_paired_stack_gate, case_batched_matches_per_file]


def main():
    for case in CASES:
        print('%s:' % case.__name__)
        tmp = tempfile.mkdtemp()
        try:
            case(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print('\n실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('\n통과 — 변경 앵커 회귀 테스트')
    return 0


if __name__ == '__main__':
    sys.exit(main())
