#!/usr/bin/env python3
"""readiness.py: the adoption check finds what is actually wrong, and nothing else.

1. A repo with a broken dismissed.yaml, a relative log_dir and a rule whose
   globs reach no file fails on exactly those items, with exit 1.
2. A clean repo has no FAIL and exits 0.
3. Enabling only in user scope warns that teammates will not get the plugin;
   project scope plus the marketplace passes.
4. Outside git it is exit 2, not a report.
5. Odd JSON in Claude Code's own files never crashes the check, and a project
   scope that says false is not reported as "teammates get it".
6. The full run (sandbox suites, scans) writes nothing under HOME's cache.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, check, isolated_env, make_repo,  # noqa: E402
                     run_cases, run_script, write)

KEY = 'convention-guard@team-market'
DEAD_RULE = '''id: no-foo
title: foo 금지
severity: warn
applies_to:
  stacks: [php]
  files: ["src/**/*.php"]
detect:
  when_line_added: '\\bfoo\\('
message: foo 대신 bar
tests:
  match: ['foo();']
  no_match: ['bar();']
'''


def readiness(repo, data, quick=True):
    proc = run_script('readiness.py', (['--quick'] if quick else []) + ['--json', '--cwd', repo],
                      env=isolated_env(data), cwd=repo)
    items = json.loads(proc.stdout)['items'] if proc.stdout.strip() else []
    return proc.returncode, {(i['id'], i['status']) for i in items}, proc


def install(data, repo, project=False, options=None):
    """Fake Claude Code state under the isolated HOME."""
    home = os.path.join(data, 'home')
    write(home, '.claude/plugins/installed_plugins.json', json.dumps(
        {'plugins': {KEY: [{'scope': 'user', 'version': '3.0.1'}]}}))
    user = {'enabledPlugins': {KEY: True}}
    if options:
        user['pluginConfigs'] = {KEY: {'options': options}}
    write(home, '.claude/settings.json', json.dumps(user))
    if project:
        write(repo, '.claude/settings.json', json.dumps({
            'enabledPlugins': {KEY: True},
            'extraKnownMarketplaces': {'team-market': {'source': {'source': 'git', 'url': 'x'}}}}))


def case_broken_repo(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, 'app/A.php': '<?php\n',
                     '.claude/convention-guard/rules/no-foo.yaml': DEAD_RULE,
                     # both parsers reject this one (miniyaml accepts an unclosed `[`)
                     '.claude/convention-guard/dismissed.yaml': '"unterminated\n'})
    install(data, repo, options={'log_dir': './logs'})
    code, seen, proc = readiness(repo, data)
    check('exit 1 when something fails', code == 1, proc.stdout + proc.stderr)
    check('a broken dismissed.yaml fails', ('C6', 'fail') in seen, seen)
    check('a relative log_dir fails', ('B5', 'fail') in seen, seen)
    check('a rule that reaches no file warns', ('D2', 'warn') in seen, seen)
    check('user-only enablement warns', ('B2', 'warn') in seen, seen)


def case_clean_repo(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, 'app/A.php': '<?php\n'})
    install(data, repo, project=True, options={'log_dir': os.path.join(tmp, 'logs')})
    code, seen, proc = readiness(repo, data)
    check('no FAIL on a clean repo', not any(s == 'fail' for _, s in seen), seen)
    check('exit 0', code == 0, proc.stdout + proc.stderr)
    check('project scope with its marketplace passes', ('B2', 'pass') in seen, seen)


def case_not_git(tmp):
    os.makedirs(os.path.join(tmp, 'plain'))
    proc = run_script('readiness.py', ['--quick', '--cwd', os.path.join(tmp, 'plain')],
                      env=isolated_env(os.path.join(tmp, 'data')))
    check('outside git is exit 2, not a report', proc.returncode == 2, proc.stdout)


def case_odd_json(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER})
    home = os.path.join(data, 'home')
    for installed, settings in [('{"plugins": []}', '[]'),
                                ('{"plugins": {"%s": ["x", 3]}}' % KEY, '{"enabledPlugins": ["%s"]}' % KEY),
                                ('{"plugins": {"convention-guard": [{}]}}',
                                 '{"pluginConfigs": {"%s": {"options": [1]}}}' % KEY)]:
        write(home, '.claude/plugins/installed_plugins.json', installed)
        write(home, '.claude/settings.json', settings)
        code, seen, proc = readiness(repo, data)
        check('odd JSON does not crash (%s)' % installed[:30], code in (0, 1)
              and 'Traceback' not in proc.stderr and seen, proc.stderr[-300:])
        check('and no check failed on its own bug', '점검 자체가 실패' not in proc.stdout,
              proc.stdout[-300:])


def case_project_false(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER})
    install(data, repo, project=True)
    write(repo, '.claude/settings.json', json.dumps({
        'enabledPlugins': {KEY: False},
        'extraKnownMarketplaces': {'team-market': {'source': {'source': 'git', 'url': 'x'}}}}))
    write(repo, '.claude/settings.local.json', json.dumps({'enabledPlugins': {KEY: True}}))
    _, seen, _ = readiness(repo, data)
    check('project false + local true warns about teammates', ('B2', 'warn') in seen, seen)


def case_full_run_is_isolated(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, 'app/A.php': '<?php\n'})
    cache = os.path.join(data, 'home', '.cache')
    code, seen, proc = readiness(repo, data, quick=False)
    check('the full run finishes', code in (0, 1) and seen, proc.stderr[-300:])
    check('sandbox suites ran', any(i == 'F' for i, _ in seen), seen)
    written = [os.path.join(d, f) for d, _, fs in os.walk(cache) for f in fs]
    check('nothing written under HOME/.cache', not written, written[:5])


if __name__ == '__main__':
    sys.exit(run_cases([case_broken_repo, case_clean_repo, case_not_git, case_odd_json,
                        case_project_false, case_full_run_is_isolated], 'readiness.py'))
