#!/usr/bin/env python3
"""A migrated repo must check exactly what it checked before.

Two conversions live here. 0.x -> 1.0 moves the layout and the rule format;
1.x -> 3.0 gives each rule the structure conditions it can safely hold. The
second one changes what the checker reports, so it earns much less trust: it
is proved against the fixtures the rule's author wrote, and against a false
positive built from them.

The fixture is a 0.6 layout written by hand in the old format: repo config
with flat keys and explanatory comments, a local rule, an override, and a
dismissal. After `migrate.py --write` the same change must produce the same
findings, the comments must survive, and the hook must stop refusing to run.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, ROOT, Session, check, commit,  # noqa: E402
                     isolated_env, make_repo, run_cases, run_script, write)

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


RULES = '.claude/convention-guard/rules'

# A rule the tool can convert: the regex names neither a comment nor a quote.
V1_SLEEP = """id: no-sleep
title: sleep 금지
severity: error
applies_to:
  stacks: [php]
  files: ["app/**/*.php"]
detect:
  when_line_added: 'sleep\\s*\\('
message: sleep 대신 큐를 쓰세요.
tests:
  match:
    - 'sleep(1);'
"""

# A rule it must refuse: it hunts for a quoted call inside a comment, so both
# masks would delete the rule rather than sharpen it (TR-03, TR-04).
V1_DEBUG_COMMENT = """id: debug-in-comment
title: 주석에 남은 디버그 호출
severity: warn
applies_to:
  stacks: [php]
  files: ["app/**/*.php"]
detect:
  when_line_added: '//\\s*(dd|dump)\\s*\\("'
message: 주석에 남은 디버그 호출을 지우세요.
tests:
  match:
    - '// dd("here");'
"""

SLEEPY = (HDR + 'class B { public function f() {\n'
                '    sleep(1);\n'
                '    // sleep(2);\n'
                '} }\n')


def migrated_repo(tmp, rules):
    """A 1.x repo (already on the 1.0 layout) with the given local rules."""
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    files = {'composer.json': LARAVEL_COMPOSER, 'app/Svc/B.php': HDR + 'class B {}\n'}
    files.update({'%s/%s' % (RULES, name): body for name, body in rules.items()})
    make_repo(repo, files)
    return repo, data


def migrate_cli(repo, data, *args):
    return run_script('migrate.py', ['--cwd', repo] + list(args),
                      env=isolated_env(data), cwd=repo)


def case_conditions_added(tmp):
    """1·2·6 — preview, write, and the run after that."""
    repo, data = migrated_repo(tmp, {'no-sleep.yaml': V1_SLEEP})
    path = os.path.join(repo, RULES, 'no-sleep.yaml')
    with open(path, encoding='utf-8') as fh:
        before = fh.read()

    dry = migrate_cli(repo, data)
    check('미리보기는 변경을 알린다 (종료 코드 1)', dry.returncode == 1, dry.stdout + dry.stderr)
    check('미리보기는 조건을 보여준다', 'not_in: [comment, string]' in dry.stdout, dry.stdout)
    with open(path, encoding='utf-8') as fh:
        check('미리보기는 파일을 건드리지 않는다', fh.read() == before)
    check('실행 시간이 출력된다', '규칙 1개 검사' in dry.stdout, dry.stdout)

    done = migrate_cli(repo, data, '--write')
    check('--write 는 성공한다 (종료 코드 0)', done.returncode == 0, done.stdout + done.stderr)
    with open(path, encoding='utf-8') as fh:
        after = fh.read()
    check('미리보기에서 본 것과 같게 바뀐다', 'not_in: [comment, string]' in after, after)
    check('사용자가 쓴 줄은 그대로', "when_line_added: 'sleep\\s*\\('" in after, after)
    check('오탐 픽스처가 생겼다', '// sleep(1);' in after, after)
    check('수동 영역을 알린다', 'in_scope' in done.stdout and 'block_empty' in done.stdout,
          done.stdout)
    check('판정 캐시 만료를 알린다', '만료' in done.stdout, done.stdout)

    again = migrate_cli(repo, data, '--write')
    check('두 번째 실행은 할 일이 없다 (종료 코드 0)', again.returncode == 0,
          again.stdout + again.stderr)
    check('두 번째 실행은 변경 0건', '옮길 것이 없습니다' in again.stdout, again.stdout)
    with open(path, encoding='utf-8') as fh:
        check('두 번째 실행 뒤 파일이 같다', fh.read() == after)


def case_converted_rule_holds(tmp):
    """3 — the converted rule passes its own fixtures, and means what it says."""
    repo, data = migrated_repo(tmp, {'no-sleep.yaml': V1_SLEEP})
    migrate_cli(repo, data, '--write')
    commit(repo, 'conditions')

    suite = run_script(os.path.join(ROOT, 'tests', 'rules', 'test_rule_fixtures.py'),
                       ['--repo', repo], env=isolated_env(data), cwd=ROOT)
    check('변환된 규칙이 픽스처 실행기를 통과한다', suite.returncode == 0,
          suite.stdout + suite.stderr)

    write(repo, 'app/Svc/B.php', SLEEPY)
    code, found = findings(repo, data)
    check('검사가 돈다', code == 0, found)
    hits = [f for f in found if f[0] == 'local/no-sleep']
    check('코드 안의 sleep 은 여전히 걸린다', len(hits) == 1, found)
    check('주석 안의 sleep 은 걸리지 않는다', all(loc[3] != 10 for loc in hits), found)

    unchecked = [f for f in found if 'no_scope' in str(f)]
    check('구조 미확인 고지가 쏟아지지 않는다', not unchecked, unchecked)


def case_dismissal_survives(tmp):
    """4 — a candidate declined before the conversion stays declined after."""
    repo, data = migrated_repo(tmp, {'no-sleep.yaml': V1_SLEEP})
    write(repo, 'app/Svc/B.php', SLEEPY)     # 작업 트리에 둔다 — 커밋하면 변경분이 사라진다

    code, before = findings(repo, data)
    check('변환 전에 후보가 있다', code == 0 and any(f[0] == 'local/no-sleep' for f in before),
          before)
    line = [f[3] for f in before if f[0] == 'local/no-sleep'][0]
    out = run_script('dismiss.py', ['--cwd', repo, '--rule', 'local/no-sleep',
                                    '--file', 'app/Svc/B.php', '--line', str(line),
                                    '--reason', '의도된 지연', '--by', 'agent'],
                     env=isolated_env(data), cwd=repo)
    check('기각이 기록된다', out.returncode == 0, out.stdout + out.stderr)

    migrate_cli(repo, data, '--write')
    code, after = findings(repo, data)
    check('변환 뒤에도 기각이 살아 있다',
          code == 0 and not any(f[0] == 'local/no-sleep' for f in after), after)


def case_blocked_rule_reported(tmp):
    """5 — a rule that cannot be converted is named, with a reason to act on."""
    repo, data = migrated_repo(tmp, {'debug-in-comment.yaml': V1_DEBUG_COMMENT})
    path = os.path.join(repo, RULES, 'debug-in-comment.yaml')
    with open(path, encoding='utf-8') as fh:
        before = fh.read()

    dry = migrate_cli(repo, data)
    check('불가 사유 코드가 나온다', 'would_break' in dry.stdout, dry.stdout)
    check('다음에 무엇을 할지 알려준다', '탐지가 사라집니다' in dry.stdout, dry.stdout)
    with open(path, encoding='utf-8') as fh:
        check('불가 규칙은 손대지 않는다', fh.read() == before)
    check('불가는 검증 실패가 아니다 (종료 코드 0)', dry.returncode == 0,
          (dry.returncode, dry.stdout))

    again = migrate_cli(repo, data, '--write')
    check('여러 번 돌려도 같은 답', again.returncode == 0 and 'would_break' in again.stdout,
          again.stdout)

    # a rule file nobody can read must be named, not crash the run
    write(repo, '%s/broken.yaml' % RULES, 'id: x\n  bad indent: [\n')
    broken = migrate_cli(repo, data)
    check('읽을 수 없는 규칙은 보고되고 죽지 않는다',
          broken.returncode == 2 and 'broken.yaml' in broken.stdout,
          (broken.returncode, broken.stdout + broken.stderr))


if __name__ == '__main__':
    sys.exit(run_cases([case_round_trip, case_conditions_added, case_converted_rule_holds,
                        case_dismissal_survives, case_blocked_rule_reported],
                       '마이그레이션 (0.x → 1.0, 1.x → 3.0)'))
