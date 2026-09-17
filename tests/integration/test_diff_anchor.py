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
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, ROOT, check, commit, git,  # noqa: E402
                     make_repo, run_cases, tempdir, write)
from lib import config, detect, gitdiff, rules as rulelib, stack as stacklib  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402


def hit_ids(tmp, tags, changed, new_files):
    all_rules = rulelib.load(tmp, ROOT, config.DEFAULTS, tags).rules
    scope = ChangeScope(tmp, changed, new_files, 'test')
    return {rule['id'] for rule, _ in detect.run(all_rules, scope, detect.Stacks(tags), 5)}


def laravel_repo(tmp):
    return make_repo(tmp, {'composer.json': LARAVEL_COMPOSER})


def case_staged_new_file(tmp):
    laravel_repo(tmp)
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
    laravel_repo(tmp)
    write(tmp, 'doc.md', 'a\nb\nc\n')
    commit(tmp, 'doc')
    write(tmp, 'doc.md', 'a\n+++ marker\nZZZ\nb\nc\n')

    lines = gitdiff.added_lines(tmp, ['doc.md']).get('doc.md') or []
    check('line starting with ++ is not dropped', (2, '+++ marker') in lines, lines)
    check('following line keeps its real number', (3, 'ZZZ') in lines, lines)


def case_base_ref_union(tmp):
    laravel_repo(tmp)
    rel = 'app/Svc/Legacy.php'
    head = '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass L {\n'
    write(tmp, rel, head + '    public function a() { return 1; }\n}\n')
    commit(tmp, 'base')
    git(tmp, 'branch', '-M', 'main')
    git(tmp, 'checkout', '-q', '-b', 'feat')

    write(tmp, rel, head + '    public function a() { dd(1); }\n}\n')
    commit(tmp, 'committed mid-session')
    # an unrelated uncommitted edit, so the HEAD diff is non-empty
    write(tmp, rel, head + '    public function a() { dd(1); }\n'
                           '    public function b() { return 2; }\n}\n')

    base = gitdiff.resolve_base_ref(tmp, 'auto')
    check('auto base ref resolves', bool(base), base)
    texts = [text for _, text in gitdiff.added_lines(tmp, [rel], base).get(rel) or []]
    check('committed-mid-session line is visible', any('dd(1)' in t for t in texts), texts)
    check('uncommitted line is visible too', any('function b' in t for t in texts), texts)


def case_paired_stack_gate(tmp):
    make_repo(tmp, {'go.mod': 'module x\n\ngo 1.22\n'})
    write(tmp, 'routes/api.php', "<?php\nRoute::get('/x');\n")
    detected = stacklib.detect(ROOT, tmp)
    check('repo detected as go only', detected['stacks'] == ['go'], detected['stacks'])

    changed = gitdiff.added_lines(tmp, ['routes/api.php'])
    ids = hit_ids(tmp, detected['tags'], changed, gitdiff.new_files(tmp) & set(changed))
    check('laravel paired rule stays out of a go repo',
          'core/laravel-route-needs-test' not in ids, ids)

    with tempdir() as other:
        laravel_repo(other)
        write(other, 'routes/api.php', "<?php\nRoute::get('/x');\n")
        changed = gitdiff.added_lines(other, ['routes/api.php'])
        ids = hit_ids(other, {'php', 'laravel'}, changed,
                      gitdiff.new_files(other) & set(changed))
        check('laravel paired rule fires in a laravel repo',
              'core/laravel-route-needs-test' in ids, ids)


def case_batched_matches_per_file(tmp):
    """The batched diff must agree with a per-file diff, file for file."""
    laravel_repo(tmp)
    rels = ['src/f%d.php' % i for i in range(5)]
    for rel in rels:
        write(tmp, rel, '<?php\ndeclare(strict_types=1);\nnamespace App;\nclass A {}\n')
    commit(tmp, 'bulk')
    for i, rel in enumerate(rels):
        with open(os.path.join(tmp, rel), 'a', encoding='utf-8') as fh:
            fh.write('// touched %d\n' % i)

    batched = gitdiff.added_lines(tmp, rels)
    one_by_one = {}
    for rel in rels:
        one_by_one.update(gitdiff.diff_lines(tmp, [rel], ['HEAD']))
    check('batched diff equals per-file diff', batched == one_by_one,
          '%r != %r' % (batched, one_by_one))


if __name__ == '__main__':
    sys.exit(run_cases([case_staged_new_file, case_plus_prefixed_line, case_base_ref_union,
                        case_paired_stack_gate, case_batched_matches_per_file],
                       '변경 앵커 회귀 테스트'))
