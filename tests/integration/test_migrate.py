#!/usr/bin/env python3
"""A 0.x repo migrated to 1.0 must check exactly what it checked before.

The fixture is a 0.6 layout written by hand in the old format: repo config
with flat keys and explanatory comments, a local rule, an override, and a
dismissal. After `migrate.py --write` the same change must produce the same
findings, the comments must survive, and the hook must stop refusing to run.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, commit, isolated_env,  # noqa: E402
                     make_repo, run_cases, run_script, write)

OLD_CONFIG = """# 팀 설정 — 이 주석은 마이그레이션 뒤에도 남아야 합니다
disable:
  - core/no-orphan-todo    # 레거시 TODO 가 너무 많음

severity:
  core/php-line-too-long: warn

# 연속 차단은 두 번까지만
max_consecutive_blocks: 2
max_rules: 2
block_level: error
semantic_review: false
"""

OLD_LOCAL_RULE = """# 레포 전용 규칙
id: no-sleep
title: sleep 금지
severity: error
applies_to:
  stack: [php]
  files: ["app/**/*.php"]
triggers:
  code_regex: '\\bsleep\\s*\\('
context_injection: |
  sleep 대신 큐를 쓰세요.
tests:
  should_match:
    - 'sleep(1);'
  should_not_match:
    - 'usleep_mock();'
"""

OLD_OVERRIDE = """override: core/php-no-debug-output
severity: warn
"""

HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Svc;\n\n'


def findings(repo, data):
    proc = run_script('scan.py', ['--cwd', repo, '--json', '--no-lint', '--fail-on', 'never'],
                      env=isolated_env(data), cwd=repo)
    if proc.returncode != 0:
        return proc.returncode, proc.stderr
    report = json.loads(proc.stdout)
    return 0, sorted((f['rule_id'], f['severity'], loc['file'], loc['line'])
                     for f in report['findings'] for loc in f['locations'])


def case_round_trip(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {
        'composer.json': LARAVEL_COMPOSER,
        '.claude/convention-rules/config.yaml': OLD_CONFIG,
        '.claude/convention-rules/rules/no-sleep.yaml': OLD_LOCAL_RULE,
        '.claude/convention-rules/rules/debug-warn.yaml': OLD_OVERRIDE,
        'app/Svc/A.php': HDR + 'class A {}\n',
    })
    write(repo, 'app/Svc/A.php', HDR + 'class A { public function f() {\n'
                                       '    sleep(1); dd(2); // TODO later\n} }\n')

    code, before = findings(repo, data)
    check('an unmigrated repo cannot be inspected (exit 2)', code == 2, before)

    dry = run_script('migrate.py', ['--cwd', repo, '--quiet'], env=isolated_env(data), cwd=repo)
    check('the dry run reports pending changes (exit 1)', dry.returncode == 1,
          dry.stdout + dry.stderr)
    check('the dry run writes nothing',
          not os.path.exists(os.path.join(repo, '.claude', 'convention-guard')))

    done = run_script('migrate.py', ['--cwd', repo, '--write', '--quiet'],
                      env=isolated_env(data), cwd=repo)
    check('--write succeeds', done.returncode == 0, done.stdout + done.stderr)
    check('the old directory is gone',
          not os.path.exists(os.path.join(repo, '.claude', 'convention-rules')), done.stdout)

    with open(os.path.join(repo, '.claude', 'convention-guard', 'config.yaml'),
              encoding='utf-8') as fh:
        cfg_text = fh.read()
    check('config comments survive', '이 주석은 마이그레이션 뒤에도' in cfg_text
          and '레거시 TODO 가 너무 많음' in cfg_text, cfg_text)
    check('flat keys became groups', 'limits:' in cfg_text and 'max_error_rules: 2' in cfg_text
          and 'mode: fix' in cfg_text, cfg_text)

    code, after = findings(repo, data)
    check('the migrated repo can be inspected', code == 0, after)
    ids = {f[0]: f for f in after} if code == 0 else {}
    check('the local rule still fires', 'local/no-sleep' in ids, after)
    check('the override still lowers severity',
          ids.get('core/php-no-debug-output', (None, None))[1] == 'warn', after)
    check('the disabled rule stays off', 'core/no-orphan-todo' not in ids, after)

    commit(repo, 'migrated')
    session = Session(repo, data, 'after-migrate')
    result = session.turn('app/Svc/A.php', HDR + 'class A { public function f() {\n'
                                                 '    sleep(3);\n} }\n', 'p1')
    check('the hook runs again after migration', result['decision'] == 'block', result)


if __name__ == '__main__':
    sys.exit(run_cases([case_round_trip], '0.x → 1.0 마이그레이션'))
