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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, finish, isolated_env,  # noqa: E402
                     make_repo, run_script, tempdir, write)
from lib.candidate import clip, fingerprint  # noqa: E402

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
        digest = re.search(r'hash: "?([0-9a-f]{10})', read(repo, DISMISSED)).group(1)
        check('--list shows the fingerprint',
              any(A in line and digest in line for line in listed.stdout.splitlines()), listed.stdout)

        by_key = dismiss(repo, data, '--key', 'core/php-no-debug-output:%s:%s'
                         % (A, 'abcdef1234'), '--reason', '키로 기록')
        check('--key records without re-scanning', by_key.returncode == 0, by_key.stderr)
        check('the team comment survived both writes', '팀 메모' in read(repo, DISMISSED))
        bad_key = dismiss(repo, data, '--key', 'nonsense', '--reason', 'x')
        check('a malformed key is refused', bad_key.returncode == 2, bad_key.stderr)


def case_audit_finding_can_be_dismissed():
    """`scan.py --all` reports findings in code this change never touched, and
    those used to be impossible to dismiss: the change scope cannot see them,
    and the `--key` form the docs point at is only ever printed by the hook.
    """
    print('case_audit_finding_can_be_dismissed:')
    with tempdir() as tmp:
        repo = os.path.join(tmp, 'repo')
        make_repo(repo, {'composer.json': LARAVEL_COMPOSER,
                         A: HDR + 'class A {\n    public function f() { dd(1); }\n}\n'})
        data = os.path.join(tmp, 'data')

        clean = run_script('scan.py', ['--cwd', repo, '--no-lint', '--fail-on', 'never',
                                       '--no-color'], env=isolated_env(data), cwd=repo)
        check('the change scope sees nothing -- it is committed, untouched code',
              '✔ 지적 없음' in clean.stdout, clean.stdout)

        out = dismiss(repo, data, '--rule', 'core/php-no-debug-output', '--file', A,
                      '--line', '8', '--reason', '레거시 디버그 유틸', '--by', 'agent')
        check('the audit finding can still be dismissed', out.returncode == 0,
              out.stdout + out.stderr)
        check('and it is pinned to the code, not the whole file',
              'hash:' in read(repo, DISMISSED), read(repo, DISMISSED))

        wrong = dismiss(repo, data, '--rule', 'core/php-no-debug-output', '--file', A,
                        '--line', '3', '--reason', 'x', '--by', 'agent')
        check('a line that holds no candidate is still refused', wrong.returncode == 1,
              wrong.stderr)


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


LONG = ('    $result = $this->repository->whereHas("orders", fn ($q) => $q->where("status", '
        '"paid"))->with(["user", "items", "items.product"])')   # 120+ before the tail
LONG_RULE = 'core/php-line-too-long'
EMPTY_RULE = ('id: empty-block\ntitle: t\nseverity: warn\n'
              'applies_to: {stacks: ["*"], files: ["**/*.php"]}\n'
              "detect: {file_regex: '\\s*\\{\\s*\\}\\s*'}\nmessage: m\n")


def locations(repo, data, rule_id):
    """[(line, key, snippet)] scan.py reports for one rule."""
    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--json', '--fail-on', 'never'],
                      env=isolated_env(data), cwd=repo)
    return sorted((loc['line'], loc['key'], loc['snippet'])
                  for f in json.loads(proc.stdout)['findings'] if f['rule_id'] == rule_id
                  for loc in f['locations'])


def case_whole_line_fingerprint():
    """R11 -- the key is the whole line, not the 120 characters shown."""
    print('case_whole_line_fingerprint:')
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        write(repo, A, HDR + 'class A {\n' + LONG + '->get();\n' + LONG + '->first();\n}\n')
        found = locations(repo, data, LONG_RULE)
        check('two lines alike for 120 characters get two keys',
              len({key for _, key, _ in found}) == 2, found)

        out = dismiss(repo, data, '--rule', LONG_RULE, '--file', A, '--line', '8',
                      '--reason', '체이닝')
        check('one of them is dismissed', out.returncode == 0, out.stdout + out.stderr)
        check('only that one', [n for n, _, _ in locations(repo, data, LONG_RULE)] == [9])
        write(repo, A, HDR + 'class A {\n' + LONG + '->evil();\n' + LONG + '->first();\n}\n')
        check('changing its tail brings it back',
              [n for n, _, _ in locations(repo, data, LONG_RULE)] == [8, 9])

        # what 3.2 left in the file: the fingerprint of the clipped snippet
        old = fingerprint(clip(LONG + '->first();'))
        write(repo, DISMISSED, 'dismissed:\n  - rule: %s\n    file: %s\n    hash: "%s"\n'
              '    reason: "3.2"\n' % (LONG_RULE, A, old))
        # and keeps 3.2's meaning: it covers every line with those 120 characters,
        # line 8 included -- only a record written from now on is exact
        check('a 3.2 record still holds (dual matching)',
              locations(repo, data, LONG_RULE) == [], locations(repo, data, LONG_RULE))


def case_bom_line_one_record():
    """R6/R11 -- 3.2 read a BOM into line 1, so its record carries the BOM."""
    print('case_bom_line_one_record:')
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        with open(os.path.join(repo, 'app/Svc/C.php'), 'w', encoding='utf-8-sig') as fh:
            fh.write('<?php dd(1);\n')
        rule = 'core/php-no-debug-output'
        lines = [n for n, _, _ in locations(repo, data, rule) if n == 1]
        check('line 1 of a BOM file is a candidate', lines == [1], lines)
        old = fingerprint(clip('﻿<?php dd(1);'))
        dismiss(repo, data, '--key', '%s:app/Svc/C.php:%s' % (rule, old), '--reason', '3.2')
        check('its 3.2 record still holds', all(n != 1 for n, _, _ in locations(repo, data, rule)))


def case_identical_lines():
    """R18 -- one dismissal covers every identical line in the file, so it has to be asked for."""
    print('case_identical_lines:')
    rule = 'core/php-no-debug-output'
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        method = '    public function %s($user)\n    {\n        dd($user);\n    }\n'
        write(repo, A, HDR + 'class A {\n' + method % 'f' + method % 'g' + '}\n')
        hits = locations(repo, data, rule)
        check('two identical lines share a key',
              len(hits) == 2 and len({k for _, k, _ in hits}) == 1, hits)

        out = dismiss(repo, data, '--rule', rule, '--file', A, '--line', '10', '--reason', 'x')
        check('--line refuses to hide both silently', out.returncode == 2
              and '2곳' in out.stderr and '--all-identical' in out.stderr, out.stderr)
        out = dismiss(repo, data, '--key', hits[0][1], '--reason', 'x', '--by', 'agent')
        check('so does --key, the form the hook prints', out.returncode == 2
              and '--all-identical' in out.stderr, out.stderr)
        check('nothing was recorded', not os.path.exists(os.path.join(repo, DISMISSED)))

        out = dismiss(repo, data, '--key', hits[0][1], '--reason', 'x', '--all-identical')
        check('--all-identical records it', out.returncode == 0, out.stdout + out.stderr)
        check('and says how many it hides', '2곳' in out.stdout, out.stdout)
        check('both are gone', locations(repo, data, rule) == [])


def case_path_is_normalised():
    """R18 -- `./a.php` is the same file as `a.php`, in the record and on the CLI."""
    print('case_path_is_normalised:')
    rule = 'core/php-no-debug-output'
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        (line, key, _), = [h for h in locations(repo, data, rule) if h[0] == 8]
        digest = key.rsplit(':', 1)[1]
        write(repo, DISMISSED, 'dismissed:\n  - rule: %s\n    file: ./%s\n    hash: "%s"\n'
              '    reason: x\n' % (rule, A, digest))
        check('a hand-written ./ path applies', [h[0] for h in locations(repo, data, rule)]
              == [9], locations(repo, data, rule))

        out = dismiss(repo, data, '--rule', rule, '--file', './' + A, '--line', '9',
                      '--reason', 'y')
        check('the CLI accepts ./ too', out.returncode == 0, out.stdout + out.stderr)
        check('and records the normal form', 'file: "%s"' % A in read(repo, DISMISSED)
              or 'file: %s\n' % A in read(repo, DISMISSED), read(repo, DISMISSED))


def case_file_match_trims_whitespace():
    """R11 -- a file match's key and line ignore the whitespace around it."""
    print('case_file_match_trims_whitespace:')
    with tempdir() as tmp:
        repo, data = laravel(tmp)
        write(repo, '.claude/convention-guard/rules/empty-block.yaml', EMPTY_RULE)
        code = 'class B {\n    public function f()\n    {\n    }\n%s    public function g() {}\n}\n'
        write(repo, 'app/Svc/B.php', HDR + code % '\n')
        one = [loc for loc in locations(repo, data, 'local/empty-block') if loc[0] < 12]
        write(repo, 'app/Svc/B.php', HDR + code % '\n\n\n')
        three = [loc for loc in locations(repo, data, 'local/empty-block') if loc[0] < 12]
        check('the match is reported on its brace, not the line before', one[:1] and
              one[0][0] == 9, one)
        check('blank lines after it do not change the key',
              one[:1] and three[:1] and one[0][1] == three[0][1], (one, three))
        check('and the snippet has no trailing ⏎', one[:1] and one[0][2] == '{ ⏎     }', one)


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
    case_audit_finding_can_be_dismissed()
    case_broken_file_is_loud()
    case_whole_line_fingerprint()
    case_bom_line_one_record()
    case_identical_lines()
    case_path_is_normalised()
    case_file_match_trims_whitespace()
    case_report()
    sys.exit(finish('기각 무결성 / 건강도 리포트'))
