#!/usr/bin/env python3
"""Build output and generated code are not the agent's code to hold to a
convention.

A Bash call that runs a build or a code generator hands every file it writes
to the agent, and `.gitignore` only covers the output a repo does not commit.
`generated` in config.yaml lists what no rule reads, whatever the rule; a repo
can replace the list or empty it.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, check, commit, isolated_env, make_repo,  # noqa: E402
                     run_cases, run_script, write)

CONSOLE = 'console.log("x")\n'
# the secret rule reads `key = "value"`; a JSON key (`"password": …`) is not its shape
SECRET = 'const password = "p@ssw0rd-prod-1";\n'


def scan(repo, data):
    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--json'],
                      env=isolated_env(data), cwd=repo)
    return proc, (json.loads(proc.stdout) if proc.stdout.strip().startswith('{') else None)


def rule_ids(result):
    return sorted({f['rule_id'] for f in (result or {}).get('findings', [])})


def js_repo(tmp, config=None):
    repo = os.path.join(tmp, 'repo')
    files = {'package.json': '{"name": "x"}\n'}
    if config is not None:
        files['.claude/convention-guard/config.yaml'] = config
    make_repo(repo, files)
    return repo, os.path.join(tmp, 'data')


def case_build_output_is_not_checked(tmp):
    repo, data = js_repo(tmp)
    write(repo, 'dist/app.min.js', CONSOLE)
    _, result = scan(repo, data)
    check('an uncommitted, unignored dist/app.min.js draws nothing', rule_ids(result) == [],
          result)


def case_source_still_is(tmp):
    repo, data = js_repo(tmp)
    write(repo, 'src/app.js', CONSOLE)
    _, result = scan(repo, data)
    check('the same line in src/app.js is js-no-console',
          rule_ids(result) == ['core/js-no-console'], result)


def case_repo_can_empty_the_list(tmp):
    repo, data = js_repo(tmp, 'generated: []\n')
    write(repo, 'dist/app.min.js', CONSOLE)
    _, result = scan(repo, data)
    check('generated: [] checks build output again',
          'core/js-no-console' in rule_ids(result), result)


def case_lock_file_is_not_checked(tmp):
    repo, data = js_repo(tmp)
    write(repo, 'package-lock.json', SECRET)
    write(repo, 'src/config.js', SECRET)
    _, result = scan(repo, data)
    files = sorted({loc['file'] for f in (result or {}).get('findings', [])
                    for loc in f['locations']})
    check('package-lock.json is skipped by every rule, the secret rule included',
          files == ['src/config.js'], result)


def case_wrong_type_is_a_config_error(tmp):
    repo, data = js_repo(tmp, 'generated: "dist/**"\n')
    proc, _ = scan(repo, data)
    check('generated that is not a list is a config error (exit 2)', proc.returncode == 2,
          (proc.returncode, proc.stdout[:300], proc.stderr[:300]))


def case_gitignored_output_stays_out(tmp):
    # the list emptied, so what keeps dist/ out can only be .gitignore
    repo, data = js_repo(tmp, 'generated: []\n')
    write(repo, '.gitignore', 'dist/\n')
    write(repo, 'dist/app.js', CONSOLE)
    _, result = scan(repo, data)
    check('ignored dist/ is still not checked', rule_ids(result) == [], result)


def case_tests_still_count_as_evidence(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, 'routes/api.php': '<?php\n',
                     'tests/Feature/UserTest.php': '<?php\n'})
    data = os.path.join(tmp, 'data')
    write(repo, 'routes/api.php', "<?php\nRoute::get('/u', fn () => 1);\n")
    write(repo, 'tests/Feature/UserTest.php', '<?php\n// covers /u\n')
    _, result = scan(repo, data)
    check('a route changed with its test: laravel-route-needs-test is quiet',
          'core/laravel-route-needs-test' not in rule_ids(result), result)
    write(repo, 'tests/Feature/UserTest.php', '<?php\n')
    _, result = scan(repo, data)
    check('the route alone: laravel-route-needs-test fires',
          'core/laravel-route-needs-test' in rule_ids(result), result)


def case_bad_globs_are_config_errors(tmp):
    repo, data = js_repo(tmp)
    for body in ('generated: [1]\n', 'generated: ["[z-a]"]\n', 'exclude: [1]\n'):
        write(repo, '.claude/convention-guard/config.yaml', body)
        commit(repo, body)
        proc, _ = scan(repo, data)
        check('%s is a config error (exit 2) with no traceback' % body.strip(),
              proc.returncode == 2 and 'Traceback' not in proc.stderr,
              (proc.returncode, proc.stderr[-300:]))


def case_rule_can_read_generated_paths(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER})
    data = os.path.join(tmp, 'data')
    write(repo, 'tests/Unit/FooTest.php', '<?php\n\nclass FooTest {}\n')
    _, result = scan(repo, data)
    check('a rule that opts in (include_generated) still reads tests/: '
          'php-strict-types-required on a new test file',
          'core/php-strict-types-required' in rule_ids(result), result)


if __name__ == '__main__':
    sys.exit(run_cases([case_build_output_is_not_checked, case_source_still_is,
                        case_repo_can_empty_the_list, case_lock_file_is_not_checked,
                        case_wrong_type_is_a_config_error, case_gitignored_output_stays_out,
                        case_tests_still_count_as_evidence, case_bad_globs_are_config_errors,
                        case_rule_can_read_generated_paths],
                       '생성물 기본 제외'))
