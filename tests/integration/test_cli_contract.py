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

from helpers import (LARAVEL_COMPOSER, Session, check, commit, git, isolated_env,  # noqa: E402
                     make_repo, run_cases, run_script, write)
from lib import state as statelib  # noqa: E402

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
    counts = json.loads(proc.stdout)['summary'] if proc.stdout.strip() else {}
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


def case_bash_changes_are_collected_precisely(tmp):
    repo, data = laravel(tmp)
    write(repo, '.claude/convention-guard/config.yaml', 'mode: fix\n')
    commit(repo, 'enable blocking')
    # This is a pre-existing human change. A Bash hook must not claim it.
    write(repo, 'notes.txt', 'api_key = "human-change-12345"\n')
    session = Session(repo, data, 'bash')
    session.bash_hook('PreToolUse')
    write(repo, 'app/Svc/A.php', HDR + 'class A { public function f() { dd(1); } }\n')
    session.bash_hook('PostToolUse')
    out = session.stop('p1')
    check('a file changed through Bash is inspected',
          out['decision'] == 'block' and 'app/Svc/A.php' in out['reason'], out)
    check('an unchanged dirty file from before Bash is not claimed',
          'notes.txt' not in out['reason'], out['reason'])


def case_cap_holds(tmp):
    repo, data = laravel(tmp)
    write(repo, '.claude/convention-guard/config.yaml',
          'mode: fix\nonce_per_session: false\nlimits:\n  max_consecutive_blocks: 2\n'
          '  max_verify_attempts: 9\n')
    commit(repo, 'config')
    session = Session(repo, data, 'cap')
    rel = 'app/Svc/A.php'
    # one request: the agent keeps answering our block without fixing (R4 --
    # the cap is the loop guard inside a request, not across requests)
    decisions = [session.turn(rel, HDR + 'class A { public function f() { dd(0); } }\n',
                              'p0')['decision']]
    for _ in range(4):
        session.touch(rel)
        decisions.append(session.stop('p0', stop_hook_active=True)['decision'])
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


def case_hook_scope_errors_are_visible(tmp):
    repo, data = laravel(tmp)
    # 4.0 has no hook base ref (design D6): a config that still names one is
    # told so, and the hook checks what the agent wrote as always
    write(repo, '.claude/convention-guard/config.yaml',
          'mode: fix\nscope:\n  base_ref: auto\n')
    commit(repo, 'a 3.x key')
    out = Session(repo, data, 'old-key').turn(
        'app/Svc/A.php', HDR + 'class A { public function f() { dd(1); } }\n', 'p1')
    check('a leftover scope.base_ref does not change what is checked',
          out['decision'] == 'block', out)

    outside = os.path.join(tmp, 'not-a-repo')
    os.makedirs(outside)
    nonrepo = Session(outside, os.path.join(tmp, 'nonrepo-data'), 'nonrepo')
    out = nonrepo.turn('src/a.py', 'print("changed")\n', 'p1')
    check('a non-repo Stop reports that inspection was impossible',
          'git 레포' in out['summary'], out)


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


def path_report(repo, data, *paths):
    proc = run_script('detect_stack.py', ['--cwd', repo, '--json']
                      + [arg for p in paths for arg in ('--path', p)],
                      env=isolated_env(data), cwd=repo)
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        return proc, {}
    return proc, {entry['path']: {r['id']: r for r in entry['rules']}
                  for entry in info.get('paths', [])}


def case_detect_stack_explains_a_path(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'package.json': '{"name": "x"}\n',
                     '.claude/convention-guard/config.yaml': 'exclude: ["legacy/**"]\n'})
    data = os.path.join(tmp, 'data')
    proc, by_path = path_report(repo, data, 'src/a.js', 'dist/app.min.js', 'tests/x.test.js',
                                'app/Foo.php', 'legacy/a.js')
    check('detect_stack.py --path exits 0', proc.returncode == 0, proc.stderr)

    def row(path, rule):
        return by_path.get(path, {}).get(rule) or {}

    check('src/a.js: js-no-console applies', row('src/a.js', 'core/js-no-console').get('applies')
          is True, row('src/a.js', 'core/js-no-console'))
    got = row('dist/app.min.js', 'core/js-no-console')
    check('dist/app.min.js: js-no-console is out, as generated',
          got.get('applies') is False and got.get('reason') == 'generated', got)
    got = row('tests/x.test.js', 'core/no-hardcoded-secret')
    check('tests/x.test.js: no-hardcoded-secret is out by its own exclude',
          got.get('applies') is False and got.get('reason') == 'rule_exclude', got)
    got = row('app/Foo.php', 'core/php-no-debug-output')
    check('app/Foo.php in a js repo: a php rule is out, preset inactive',
          got.get('applies') is False and got.get('reason') == 'preset', got)
    got = row('legacy/a.js', 'core/js-no-console')
    check('legacy/a.js: out by the repo config exclude',
          got.get('applies') is False and got.get('reason') == 'config_exclude', got)
    proc, dotted = path_report(repo, data, './legacy/a.js')
    check('./legacy/a.js reads as legacy/a.js',
          (dotted.get('legacy/a.js', {}).get('core/js-no-console') or {}).get('reason')
          == 'config_exclude', dotted)
    proc, _ = path_report(repo, data, '../x.js')
    check('a path outside the repo exits 2', proc.returncode == 2, (proc.returncode, proc.stderr))
    os.makedirs(os.path.join(repo, 'src'), exist_ok=True)
    inside = run_script('detect_stack.py', ['--json', '--path', 'a.js'],
                        env=isolated_env(data), cwd=os.path.join(repo, 'src'))
    seen = [p['path'] for p in json.loads(inside.stdout).get('paths', [])] if inside.stdout else []
    check('from src/, --path a.js is src/a.js', seen == ['src/a.js'], (seen, inside.stderr))
    _, own = path_report(repo, data, '.claude/convention-guard/config.yaml')
    got = own.get('.claude/convention-guard/config.yaml', {}).get('core/no-hardcoded-secret') or {}
    check("convention-guard's own config is out as self", got.get('reason') == 'self', got)
    check('every rule row carries applies and a reason when it does not apply',
          by_path and all(isinstance(r.get('applies'), bool) and (r['applies'] or r.get('reason'))
                          for rules in by_path.values() for r in rules.values()), by_path)


if __name__ == '__main__':
    sys.exit(run_cases([case_scan_exit_codes, case_severity_filter_does_not_hide_exit_code,
                        case_all_includes_rules_without_globs, case_dismiss_is_exact,
                        case_collect_survives_garbage,
                        case_bash_changes_are_collected_precisely, case_cap_holds,
                        case_broken_config_is_not_silence, case_hook_scope_errors_are_visible,
                        case_detect_stack_reports, case_detect_stack_explains_a_path],
                       'CLI 계약'))
