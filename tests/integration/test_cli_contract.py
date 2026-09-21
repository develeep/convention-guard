#!/usr/bin/env python3
"""The command-line contracts CI and the agent rely on.

1. scan.py read a failed `git diff` as "no change", so a typo'd --range or a
   shallow clone made the CI gate permanently green.
2. `--severity error --fail-on warn` exited 0 while the report counted warns:
   the exit code was computed from the filtered display list.
3. `--all` only looked at files matching some rule's `files:` glob, so rules
   without one (secrets, TODOs) never ran in an audit.
4. dismiss.py fell back to *another* location when --line did not match, and
   accepted any rule id with --whole-file.
5. collect.py crashed with a traceback on a non-object JSON payload.
6. A turn the consecutive-block cap held back reset the streak, so the cap
   produced "3 blocks, 1 rest" forever instead of stopping.
7. A wrong-typed config value raised inside the engine, check.py swallowed it,
   and the hook then did nothing every turn -- indistinguishable from a pass.
8. detect_stack.py is what the skills read to explain a repo; nothing checked
   that a stock install reports no errors.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, commit, isolated_env,  # noqa: E402
                     make_repo, run_cases, run_script, write)

HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Svc;\n\n'


def scan(repo, data, *args):
    return run_script('scan.py', ['--cwd', repo, '--no-lint', '--no-color'] + list(args),
                      env=isolated_env(data), cwd=repo)


def laravel(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER,
                     'app/Svc/A.php': HDR + 'class A {}\n'})
    return repo, os.path.join(tmp, 'data')


def case_scan_exit_codes(tmp):
    repo, data = laravel(tmp)
    check('clean working tree exits 0', scan(repo, data).returncode == 0)

    bad = scan(repo, data, '--range', 'origin/nope..HEAD')
    check('an unresolvable range exits 2', bad.returncode == 2, (bad.returncode, bad.stderr))
    missing = scan(repo, data, '--files', 'does/not/exist.php')
    check('a missing --files path exits 2', missing.returncode == 2,
          (missing.returncode, missing.stderr))
    outside = scan(repo, data, '--files', os.path.join(tmp, 'elsewhere.php'))
    check('a path outside the repo exits 2', outside.returncode == 2, outside.stderr)
    notrepo = run_script('scan.py', ['--cwd', tmp, '--no-lint'], env=isolated_env(data), cwd=tmp)
    check('a non-repo exits 2', notrepo.returncode == 2, notrepo.stderr)

    write(repo, 'app/Svc/A.php', HDR + 'class A { public function f() { dd(1); } }\n')
    check('an error finding exits 1', scan(repo, data).returncode == 1)
    check('--fail-on never exits 0', scan(repo, data, '--fail-on', 'never').returncode == 0)


def case_severity_filter_does_not_hide_exit_code(tmp):
    repo, data = laravel(tmp)
    # php-no-empty-catch is a warn rule
    write(repo, 'app/Svc/A.php', HDR + 'class A { public function f() {\n'
          '    try { $this->g(); } catch (\\Throwable $e) {}\n} }\n')
    proc = scan(repo, data, '--severity', 'error', '--fail-on', 'warn', '--json')
    counts = json.loads(proc.stdout)['counts'] if proc.stdout.strip() else {}
    check('the warn is counted', counts.get('warn', 0) >= 1, proc.stdout[:300])
    check('and it fails the gate even though it is not displayed', proc.returncode == 1,
          proc.returncode)


def case_all_includes_rules_without_globs(tmp):
    repo, data = laravel(tmp)
    write(repo, 'notes.txt', 'api_key = "abcdefgh12345"\n')
    commit(repo, 'notes')
    proc = scan(repo, data, '--all', '--json', '--fail-on', 'never')
    ids = [f['rule_id'] for f in json.loads(proc.stdout)['findings']]
    check('--all runs a rule that has no files: glob', 'core/no-hardcoded-secret' in ids, ids)


def case_dismiss_is_exact(tmp):
    repo, data = laravel(tmp)
    rel = 'app/Svc/A.php'
    write(repo, rel, HDR + 'class A {\n    public function f() { dd(1); }\n'
                           '    public function g() { dd(2); }\n}\n')
    env = isolated_env(data)
    wrong = run_script('dismiss.py', ['--cwd', repo, '--rule', 'core/php-no-debug-output',
                                      '--file', rel, '--line', '99', '--reason', 'x'],
                       env=env, cwd=repo)
    check('a --line that does not match is refused', wrong.returncode == 1, wrong.stdout)
    check('and nothing is written',
          not os.path.exists(os.path.join(repo, '.claude', 'convention-guard',
                                          'dismissed.yaml')))
    unknown = run_script('dismiss.py', ['--cwd', repo, '--rule', 'core/no-such-rule',
                                        '--file', rel, '--whole-file', '--reason', 'x'],
                         env=env, cwd=repo)
    check('--whole-file with an unknown rule is refused', unknown.returncode == 2,
          unknown.stdout + unknown.stderr)


def case_collect_survives_garbage(tmp):
    data = os.path.join(tmp, 'data')
    for stdin in ('123', '[]', 'not json', '{"tool_name": "Edit", "tool_input": 5}'):
        proc = run_script('collect.py', stdin=stdin, env=isolated_env(data), cwd=tmp)
        check('collect.py exits 0 on %r' % stdin, proc.returncode == 0, proc.stderr)
        check('collect.py prints no traceback on %r' % stdin,
              'Traceback' not in proc.stderr, proc.stderr)


def case_cap_holds(tmp):
    repo, data = laravel(tmp)
    write(repo, '.claude/convention-guard/config.yaml',
          'once_per_session: false\nlimits:\n  max_consecutive_blocks: 2\n')
    commit(repo, 'config')
    session = Session(repo, data, 'cap')
    rel = 'app/Svc/A.php'
    decisions = [session.turn(rel, HDR + 'class A { public function f() { dd(%d); } }\n' % i,
                              'p%d' % i)['decision'] for i in range(5)]
    check('after the cap, the loop stays stopped while findings remain',
          decisions == ['block', 'block', None, None, None], decisions)


def case_broken_config_is_not_silence(tmp):
    repo, data = laravel(tmp)
    write(repo, '.claude/convention-guard/config.yaml', 'limits:\n  max_error_rules: "넷"\n')
    commit(repo, 'bad config')
    bad = scan(repo, data)
    check('a wrong-typed config value exits 2', bad.returncode == 2,
          (bad.returncode, bad.stderr))
    out = Session(repo, data, 'cfg').turn(
        'app/Svc/A.php', HDR + 'class A { public function f() { dd(1); } }\n', 'p1')
    check('and the Stop hook says it skipped instead of going quiet',
          '설정 오류' in out['summary'], out)
    check('the hook prints no traceback', 'Traceback' not in out['stderr'], out['stderr'])


def case_detect_stack_reports(tmp):
    repo, data = laravel(tmp)
    proc = run_script('detect_stack.py', ['--cwd', repo, '--json'],
                      env=isolated_env(data), cwd=repo)
    check('detect_stack.py exits 0 on a healthy repo', proc.returncode == 0, proc.stderr)
    info = json.loads(proc.stdout)
    check('it names the detected stack', 'laravel' in info['stacks'], info['stacks'])
    check('a stock install reports no errors',
          [n for n in info['notes'] if n['level'] == 'error'] == [], info['notes'])
    check('every rule carries a status and a source',
          all(r['status'] in ('active', 'inactive') and r['source'] for r in info['rules']),
          info['rules'][:2])


if __name__ == '__main__':
    sys.exit(run_cases([case_scan_exit_codes, case_severity_filter_does_not_hide_exit_code,
                        case_all_includes_rules_without_globs, case_dismiss_is_exact,
                        case_collect_survives_garbage, case_cap_holds,
                        case_broken_config_is_not_silence, case_detect_stack_reports],
                       'CLI 계약'))
