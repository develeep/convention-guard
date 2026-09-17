#!/usr/bin/env python3
"""Dismissals are team records; the health report is what tuning reads.

Dismissal integrity (each of these silently lost a team's decisions before):
1. an empty dismissed.yaml got entries without the `dismissed:` key -> invalid
2. the same finding could be dismissed twice
3. a dismissed.yaml that fails to parse was treated as empty: every declined
   finding came back. Now every entry point reports it and the hook skips
4. writing rewrote the file and dropped the team's comments

Report:
5. a flagged candidate verified twice (still, then fixed) counts once, as fixed
6. dismissals, reviewer verdicts and fix-introduced violations reach the verdict
7. rows from another repo, older than --since, or from 0.x are left out
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, finish, isolated_env,  # noqa: E402
                     make_repo, run_script, tempdir, write)

HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Svc;\n\n'
A = 'app/Svc/A.php'
DISMISSED = '.claude/convention-guard/dismissed.yaml'


def laravel(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, A: HDR + 'class A {}\n'})
    write(repo, A, HDR + 'class A {\n    public function f() { dd(1); }\n'
                         '    public function g() { dd(2); }\n}\n')
    return repo, os.path.join(tmp, 'data')


def dismiss(repo, data, *args):
    return run_script('dismiss.py', ['--cwd', repo] + list(args), env=isolated_env(data), cwd=repo)


def read(repo, rel):
    with open(os.path.join(repo, rel), encoding='utf-8', newline='') as fh:
        return fh.read()


def case_integrity():
    print('case_integrity:')
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        write(repo, DISMISSED, '')
        first = dismiss(repo, data, '--rule', 'core/php-no-debug-output', '--file', A,
                        '--line', '8', '--reason', '디버그 도구', '--by', 'agent')
        check('dismissing into an empty file works', first.returncode == 0, first.stderr)
        text = read(repo, DISMISSED)
        check('the file gets its dismissed: key', 'dismissed:\n' in text, text)
        check('who judged it is recorded', 'by: "agent"' in text, text)

        again = dismiss(repo, data, '--rule', 'core/php-no-debug-output', '--file', A,
                        '--line', '8', '--reason', '다시')
        check('the same finding is not recorded twice',
              again.returncode == 0 and '이미 기록' in again.stdout
              and read(repo, DISMISSED).count('rule:') == 1, again.stdout)

        ambiguous = dismiss(repo, data, '--rule', 'core/php-no-debug-output', '--file', A,
                            '--reason', 'x')
        check('two locations without --line is refused', ambiguous.returncode == 2,
              ambiguous.stderr)

        with open(os.path.join(repo, DISMISSED), 'a', encoding='utf-8') as fh:
            fh.write('  # 팀 메모: 이 항목들은 분기마다 다시 본다\n')
        listed = dismiss(repo, data, '--list')
        check('--list shows the fingerprint',
              any('app/Svc/A.php:' in line for line in listed.stdout.splitlines()), listed.stdout)

        by_key = dismiss(repo, data, '--key', 'core/php-no-debug-output:%s:%s'
                         % (A, 'abcdef1234'), '--reason', '키로 기록')
        check('--key records without re-scanning', by_key.returncode == 0, by_key.stderr)
        check('the team comment survived both writes', '팀 메모' in read(repo, DISMISSED))
        bad_key = dismiss(repo, data, '--key', 'nonsense', '--reason', 'x')
        check('a malformed key is refused', bad_key.returncode == 2, bad_key.stderr)


def case_broken_file_is_loud():
    print('case_broken_file_is_loud:')
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        # invalid for PyYAML and the bundled parser alike
        write(repo, DISMISSED, 'dismissed:\n  - rule: core/x\n    this line has no colon\n')
        scan = run_script('scan.py', ['--cwd', repo, '--no-lint'], env=isolated_env(data),
                          cwd=repo)
        check('scan cannot inspect with a broken dismissed.yaml', scan.returncode == 2,
              scan.stderr)
        session = Session(repo, data, 'broken')
        result = session.turn(A, read(repo, A), 'p1')
        check('the hook skips and says why', result['decision'] is None
              and 'dismissed.yaml' in result['summary'], result)
        refused = dismiss(repo, data, '--key', 'core/php-no-debug-output:%s:abcdef1234' % A,
                          '--reason', 'x')
        check('dismiss.py refuses to append to it', refused.returncode == 2, refused.stderr)


def event(**fields):
    fields.setdefault('schema', 2)
    fields.setdefault('ts', '2026-09-17T10:00:00+0900')
    return fields


def case_report():
    print('case_report:')
    with tempdir() as tmp:
        repo = os.path.join(tmp, 'repo')
        make_repo(repo, {'README.md': 'x\n'})
        rows = [
            {'event': 'match', 'rule_id': 'core/old'},                     # 0.x row
            event(event='candidate', repo=repo, rule_id='core/a', key='k1', severity='error',
                  shown=True, file='app/A.php'),
            event(event='verify', repo=repo, rule_id='core/a', cycle='c1', key='k1',
                  outcome='still'),
            event(event='verify', repo=repo, rule_id='core/a', cycle='c1', key='k1',
                  outcome='fixed'),
        ]
        for i in range(3):
            rows += [event(event='verify', repo=repo, rule_id='core/a', cycle='c%d' % (i + 2),
                           key='k%d' % i, outcome='fixed')]
        rows += [event(event='dismissed', repo=repo, rule_id='core/b', reason='체이닝'),
                 event(event='dismissed', repo=repo, rule_id='core/b', reason='체이닝 2'),
                 event(event='verify', repo=repo, rule_id='core/b', cycle='c9', key='kb',
                       outcome='still')]
        rows += [event(event='verdict', repo=repo, rule_id='core/sem', verdict='VALID')
                 for _ in range(4)]
        rows += [event(event='candidate', repo='/elsewhere', rule_id='core/other', key='z')]
        rows += [event(event='candidate', repo=repo, rule_id='core/stale', key='s',
                       ts='2020-01-01T00:00:00+0900')]
        log = os.path.join(tmp, 'firings.jsonl')
        with open(log, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')

        proc = run_script('log_report.py', ['--log', log, '--repo', repo, '--since', '3650',
                                            '--json'], env=isolated_env(os.path.join(tmp, 'd')))
        report = json.loads(proc.stdout)
        rules = {r['rule_id']: r for r in report['rules']}
        check('0.x rows are skipped and counted', report['legacy_skipped'] == 1, report)
        check('another repo is excluded', 'core/other' not in rules, sorted(rules))
        a = rules.get('core/a', {})
        check('still-then-fixed counts once as fixed', a.get('fixed') == 4 and a.get('still') == 0,
              a)
        check('a healthy rule is called healthy', a.get('verdict') == '건강함', a)
        b = rules.get('core/b', {})
        check('mostly dismissed means false positive', b.get('verdict', '').startswith('오탐 확정'),
              b)
        sem = rules.get('core/sem', {})
        check('a gate the reviewer keeps clearing is flagged as too wide',
              sem.get('verdict', '').startswith('게이트가 넓음') and sem.get('precision') == 0, sem)

        recent = run_script('log_report.py', ['--log', log, '--since', '30', '--json'],
                            env=isolated_env(os.path.join(tmp, 'd')))
        recent_rules = {r['rule_id'] for r in json.loads(recent.stdout)['rules']}
        check('--since leaves out old rows', 'core/stale' not in recent_rules, recent_rules)


if __name__ == '__main__':
    case_integrity()
    case_broken_file_is_loud()
    case_report()
    sys.exit(finish('기각 무결성 / 건강도 리포트'))
