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
                     isolated_env, make_repo, run_cases, run_script, tempdir, write)
from lib import config, detect, gitdiff, rules as rulelib, stack as stacklib  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402


def hit_ids(tmp, tags, changed, new_files):
    all_rules = rulelib.load(tmp, ROOT, config.DEFAULTS, tags).rules
    scope = ChangeScope(tmp, changed, new_files, 'test')
    return {rule['id'] for rule, _ in detect.run(all_rules, scope, rulelib.Reach(detect.Stacks(tags)), 5)}


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
    make_repo(tmp, {'package.json': '{"name": "x"}\n'})
    write(tmp, 'routes/api.php', "<?php\nRoute::get('/x');\n")
    detected = stacklib.detect(ROOT, tmp)
    check('repo detected as js only', detected['stacks'] == ['js'], detected['stacks'])

    changed = gitdiff.added_lines(tmp, ['routes/api.php'])
    ids = hit_ids(tmp, detected['tags'], changed, gitdiff.new_files(tmp) & set(changed))
    check('laravel paired rule stays out of a js repo',
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


def _write_bom(tmp, rel, body):
    path = os.path.join(tmp, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
        fh.write(body)


def case_bom_first_line(tmp):
    """R6 -- a UTF-8 BOM is not part of the first line, so `^` still anchors."""
    laravel_repo(tmp)
    rel = 'app/counter/page.tsx'
    page = "'use client';\n\nimport { useState } from 'react';\nconst [n] = useState(0);\n"
    _write_bom(tmp, rel, page)
    check('read_text drops the BOM', gitdiff.read_text(tmp, rel) == page,
          repr(gitdiff.read_text(tmp, rel)[:20]))
    changed = gitdiff.added_lines(tmp, [rel])
    check('so do the lines of a new file', changed[rel][0] == (1, "'use client';"),
          changed.get(rel))
    ids = hit_ids(tmp, {'js', 'react', 'next', 'next-app'}, changed,
                  gitdiff.new_files(tmp) & set(changed))
    check('a directive after a BOM is found',
          'core/next-client-hook-needs-directive' not in ids, ids)

    commit(tmp, 'page')
    _write_bom(tmp, rel, page.replace("'use client';", '"use client";'))
    lines = gitdiff.added_lines(tmp, [rel]).get(rel) or []
    check('and a diff of the first line', lines[:1] == [(1, '"use client";')], lines)


def case_deletion_only(tmp):
    """R19 -- a change that only removes lines is still a change."""
    laravel_repo(tmp)
    rel = 'app/Svc/Doc.php'
    write(tmp, rel, '<?php\n$a = 1;\n$b = 2;\n$c = 3;\n')
    commit(tmp, 'doc')
    write(tmp, rel, '<?php\n$a = 1;\n$c = 3;\n')

    seams = {}
    changed = gitdiff.added_lines(tmp, [rel], seams=seams)
    check('the file stays in the change, with no added lines', changed.get(rel) == [], changed)
    check('and a seam where line 2 now meets line 3', seams.get(rel) == {2}, seams)
    check('without the collector nothing changes for old callers',
          rel not in gitdiff.added_lines(tmp, [rel]))

    scope = ChangeScope.working_tree(tmp)
    check('the scope keeps it', rel in scope.paths() and scope.seams_of(rel) == {2},
          (scope.paths(), scope.seams_of(rel)))
    check('but linters only get files with added lines', rel not in scope.lint_paths(),
          scope.lint_paths())


def case_diff_algorithm_is_fixed(tmp):
    """R13 -- the user's diff.algorithm must not decide which lines are ours."""
    laravel_repo(tmp)
    rel = 'app/a.js'
    old = ['}', '}', 'return;', 'a();', 'return;', '{', 'b();', '}']
    new = ['}', '}', 'return;', 'a();', 'return;', 'return;', 'a();', '{', '{', '}', '{',
           'a();', 'b();', '}']
    write(tmp, rel, '\n'.join(old) + '\n')
    commit(tmp, 'a')
    write(tmp, rel, '\n'.join(new) + '\n')
    seen = {}
    for algorithm in ('myers', 'patience', 'histogram'):
        git(tmp, 'config', 'diff.algorithm', algorithm)
        seen[algorithm] = [n for n, _ in gitdiff.added_lines(tmp, [rel]).get(rel) or []]
    check('every setting gets the histogram answer',
          all(lines == [6, 7, 9, 10, 11, 12] for lines in seen.values()), seen)


def case_unreadable_files(tmp):
    """R20 -- binaries are found by content, big files are named, not skipped silently."""
    import json
    import time
    laravel_repo(tmp)
    blob = 'app/blob.php'
    os.makedirs(os.path.join(tmp, 'app'), exist_ok=True)
    with open(os.path.join(tmp, blob), 'wb') as fh:
        fh.write(b'SQLite format 3\x00\x00dd(1);\n')
    check('a NUL in the first 8KB is a binary', gitdiff.read_text(tmp, blob) == '')
    big = 'app/big.php'
    write(tmp, big, '<?php\ndd(1);\n' + '// pad\n' * 60000)
    scope = ChangeScope.working_tree(tmp)
    check('neither is scanned', blob not in scope.paths() and big not in scope.paths(),
          scope.paths())
    check('the big one is named', scope.too_large == (big,), scope.too_large)

    proc = run_script('scan.py', ['--cwd', tmp, '--no-lint', '--json', '--fail-on', 'never'],
                      env=isolated_env(os.path.join(tmp, '..', 'data')), cwd=tmp)
    body = json.loads(proc.stdout)
    check('scan --json lists it', body.get('too_large') == [big], body.get('too_large'))
    text = run_script('scan.py', ['--cwd', tmp, '--no-lint', '--fail-on', 'never',
                                  '--no-color'], env=isolated_env(os.path.join(tmp, '..', 'd2')),
                      cwd=tmp).stdout
    check('and the text says it was not checked', '큰 파일 미검사 1개 파일' in text, text[-600:])

    for raw, want in (('a\nb\n', [(1, 'a'), (2, 'b')]), ('a\nb', [(1, 'a'), (2, 'b')]),
                      ('a\n\n', [(1, 'a'), (2, '')]), ('a\r\nb\x0cc\n', [(1, 'a'), (2, 'b\x0cc')])):
        write(tmp, 'lines.txt', raw)
        check('read_lines %r' % raw, gitdiff.read_lines(tmp, 'lines.txt') == want,
              gitdiff.read_lines(tmp, 'lines.txt'))
    write(tmp, 'long.txt', 'x\n' * 100000)
    began = time.perf_counter()
    count = len(gitdiff.read_lines(tmp, 'long.txt'))
    took = time.perf_counter() - began
    check('read_lines is linear (100k lines)', count == 100000 and took < 1.0, (count, took))


LEGACY = '<?php\nclass Old\n{\n    public function f($x)\n    {\n        dd($x);\n    }\n}\n'


def lines_of(scope, rel):
    return [n for n, _ in scope.lines(rel)]


def case_moves(tmp):
    """R14 -- moving a file is not writing it."""
    laravel_repo(tmp)
    write(tmp, 'app/Old.php', LEGACY)
    commit(tmp, 'legacy')
    git(tmp, 'mv', 'app/Old.php', 'app/Moved.php')
    for scope in (ChangeScope.working_tree(tmp),):
        check('git mv adds no lines (%s)' % scope.label, lines_of(scope, 'app/Moved.php') == [],
              scope.lines('app/Moved.php'))
        check('and is not a new file (%s)' % scope.label, not scope.is_new('app/Moved.php'))
    staged = ChangeScope.staged(tmp)
    check('nor in --staged', lines_of(staged, 'app/Moved.php') == []
          and not staged.is_new('app/Moved.php'), staged.lines('app/Moved.php'))
    write(tmp, 'app/Moved.php', LEGACY.replace('    }\n}', '    }\n    public $y;\n}'))
    check('a moved file keeps only its edit',
          lines_of(ChangeScope.working_tree(tmp), 'app/Moved.php') == [8])
    git(tmp, 'mv', 'app/Moved.php', 'app/Old.php')
    write(tmp, 'app/Old.php', LEGACY)

    os.rename(os.path.join(tmp, 'app/Old.php'), os.path.join(tmp, 'app/Plain.php'))
    for scope in (ChangeScope.working_tree(tmp),):
        check('a plain mv adds no lines (%s)' % scope.label,
              lines_of(scope, 'app/Plain.php') == [], scope.lines('app/Plain.php'))
        check('and is not new either (%s)' % scope.label, not scope.is_new('app/Plain.php'))


def case_committed_new_file(tmp):
    """R14 -- a file created and committed during the session is still new."""
    laravel_repo(tmp)
    base = gitdiff.current_head(tmp)
    rel = 'app/Svc/Fresh.php'
    write(tmp, rel, '<?php\nclass Fresh {}\n')
    commit(tmp, 'fresh')
    ranged = ChangeScope.git_range(tmp, '%s..HEAD' % base)
    check('as --range does', ranged.is_new(rel), ranged.new_files)


def case_gates_read_what_they_gate(tmp):
    """R15 -- --staged reads the index and --range its right side, not the working tree."""
    laravel_repo(tmp)
    rel = 'app/Svc/Catch.php'
    code = ('<?php\nclass C {\n    public function f() {\n'
            '        try { a(); } catch (\\Exception $e) {\n        }\n'
            '        try { b(); } catch (\\Exception $e) {\n        }\n    }\n}\n')
    later = code.replace('<?php\n', '<?php\n// 1\n// 2\n// 3\n// 4\n')
    rules = [r for r in rulelib.load(tmp, ROOT, config.DEFAULTS, {'php'}).rules
             if r['id'] == 'core/php-no-empty-catch']

    def found(scope):
        return [c.line for c in detect.scan(rules[0], scope, rulelib.Reach(detect.Stacks({'php'})), 10)]

    write(tmp, rel, code)
    git(tmp, 'add', rel)
    write(tmp, rel, later)                              # not staged
    staged = ChangeScope.staged(tmp)
    check('--staged reads the index', staged.text(rel) == code, staged.text(rel)[:40])
    check('so both catches are found where the index has them', found(staged) == [4, 6],
          found(staged))

    base = gitdiff.current_head(tmp)
    write(tmp, rel, code)
    commit(tmp, 'catch')                                # commit() stages everything
    write(tmp, rel, later)
    ranged = ChangeScope.git_range(tmp, '%s..HEAD' % base)
    check('--range reads its right side', ranged.text(rel) == code, ranged.text(rel)[:40])
    check('and finds the same', found(ranged) == [4, 6], found(ranged))

    big = 'app/Svc/Big.php'
    write(tmp, big, '<?php\n' + '// pad\n' * 60000)
    git(tmp, 'add', big)
    write(tmp, big, '<?php\n')
    check('size is judged on the blob', ChangeScope.staged(tmp).too_large == (big,),
          ChangeScope.staged(tmp).too_large)


def case_path_robustness(tmp):
    """R23b -- odd paths are checked like any other, or said to be unchecked."""
    from lib import paths
    laravel_repo(tmp)
    quoted = 'app/a"b.php'
    write(tmp, quoted, '<?php\n$a = 1;\n')
    commit(tmp, 'quoted')
    write(tmp, quoted, '<?php\n$a = 1;\ndd(1);\n')
    check('a path git quotes still has its lines',
          gitdiff.added_lines(tmp, [quoted]).get(quoted) == [(3, 'dd(1);')],
          gitdiff.added_lines(tmp, [quoted]))
    fresh = 'app/c"d.php'
    write(tmp, fresh, '<?php\n')
    check('and an untracked one is untracked', fresh in gitdiff.untracked(tmp),
          gitdiff.untracked(tmp))

    check('..foo is inside the repo',
          paths.repo_relative(os.path.join(tmp, '..foo.php'), tmp) == '..foo.php')
    check('.. itself is not', paths.repo_relative(os.path.dirname(tmp), tmp) is None)
    link = tmp.rstrip('/') + '-link'
    os.symlink(tmp, link)
    try:
        check('a path through a symlink is the same file',
              paths.repo_relative(os.path.join(link, 'app/x.php'), tmp) == 'app/x.php')
    finally:
        os.remove(link)

    write(tmp, 'cr.txt', 'a\rb\nc\r\nd\n')
    check('a lone CR is not a line break, CRLF is',
          gitdiff.read_lines(tmp, 'cr.txt') == [(1, 'a\rb'), (2, 'c'), (3, 'd')],
          gitdiff.read_lines(tmp, 'cr.txt'))



if __name__ == '__main__':
    sys.exit(run_cases([case_staged_new_file, case_plus_prefixed_line, case_base_ref_union,
                        case_paired_stack_gate, case_batched_matches_per_file,
                        case_bom_first_line, case_deletion_only,
                        case_diff_algorithm_is_fixed, case_unreadable_files, case_moves,
                        case_committed_new_file,
                        case_gates_read_what_they_gate, case_path_robustness],
                       '변경 앵커 회귀 테스트'))
