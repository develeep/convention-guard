#!/usr/bin/env python3
"""The Stop hook's verification cycle, end to end through the real scripts.

    block -> fix -> re-scan -> verify

Each case drives collect.py / check.py turn by turn the way Claude Code does:
a new request arrives with stop_hook_active=false, the continuation after our
own block arrives with stop_hook_active=true.

Carried over from 0.x regressions:
- a long session must not go silent after a couple of blocks (cap is per
  consecutive block, and a clean turn resets it; a capped turn does not)
- one block must be measured once, not on every later turn
- report mode must never log a finding as shown
- a finding declined as a false positive is "dismissed", never "not fixed",
  and does not spend the rule's once-per-session budget
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, commit, finish, make_repo,  # noqa: E402
                     run_script, tempdir, write)

HDR = '<?php\ndeclare(strict_types=1);\nnamespace App;\n'
A = 'app/Svc/A.php'


def repo_files(config=''):
    files = {'composer.json': LARAVEL_COMPOSER}
    for name in ('A', 'B'):
        files['app/Svc/%s.php' % name] = \
            HDR + 'class %s { public function f() { return 1; } }\n' % name
    files['.claude/convention-guard/config.yaml'] = (
        config if 'mode:' in config else 'mode: fix\n' + config)
    return files


def body(code='dd(1);', cls='A'):
    return HDR + 'class %s { public function f() { %s } }\n' % (cls, code)


def outcomes(session):
    return sorted(e['outcome'] for e in session.events('verify'))


# ---------------------------------------------------------------- cases

def case_fixed_passes(repo, data):
    s = Session(repo, data, 'fixed')
    first = s.turn(A, body(), 'p1')
    check('a new error blocks', first['decision'] == 'block', first)
    check('the reason names the dismissal command', 'dismiss.py' in first['reason'])
    check('a cycle is open', s.state()['cycle'] is not None, s.state())

    done = s.turn(A, body('return 2;'), 'p1', stop_hook_active=True)
    check('after the fix the turn passes', done['decision'] is None, done)
    check('the outcome is logged once as fixed', outcomes(s) == ['fixed'], s.events('verify'))
    check('the cycle is closed and the streak reset',
          s.state()['cycle'] is None and s.state()['consecutive_blocks'] == 0, s.state())

    later = s.turn(A, body('dd(3);'), 'p2')
    check('once_per_session keeps a fixed rule quiet in later requests',
          later['decision'] is None, later)
    check('no further verification is logged', outcomes(s) == ['fixed'], s.events('verify'))


def case_still_blocks_once_more(repo, data):
    s = Session(repo, data, 'still')
    s.turn(A, body(), 'p1')
    s.touch(A)
    again = s.stop('p1', stop_hook_active=True)
    check('an ignored finding blocks once more', again['decision'] == 'block', again)
    check('the verify reason says it is still there', '아직 그대로' in again['reason'],
          again['reason'])
    check('and that this is the last chance', '마지막 재검증' in again['reason'])

    s.touch(A)
    last = s.stop('p1', stop_hook_active=True)
    check('after the verify attempts it stops blocking', last['decision'] is None, last)
    check('but reports what is left', '남음 1' in last['summary'], last['summary'])
    check('the cycle closed', s.state()['cycle'] is None)

    nxt = s.turn(A, body(), 'p2')
    check('an unfixed finding comes back in the next request', nxt['decision'] == 'block', nxt)
    check('marked as raised before', '지난 턴에 지적했는데' in nxt['reason'], nxt['reason'][:300])


def case_new_violation_from_fix(repo, data):
    s = Session(repo, data, 'newfix')
    s.turn(A, body('dd(1);'), 'p1')
    fixed = s.turn(A, body('var_dump(1);'), 'p1', stop_hook_active=True)
    check('a violation introduced by the fix blocks', fixed['decision'] == 'block', fixed)
    check('it is called out as new', '새로 생겼습니다' in fixed['reason'], fixed['reason'])
    check('the original is logged fixed and the replacement new',
          outcomes(s) == ['fixed', 'new'], s.events('verify'))


def case_settled_rule_can_come_back(repo, data):
    """once_per_session used to filter the re-scan itself, not just the report.

    Every other cycle case turns it off, so nothing covered what happens when
    a later fix re-introduces a rule the session had already settled: the
    verification could not see it, and reported the cycle as clean.
    """
    s = Session(repo, data, 'settled')
    s.turn(A, body('dd(1);'), 'p1')
    done = s.turn(A, body('return 1;'), 'p1', stop_hook_active=True)
    check('the first rule is settled for the session', done['decision'] is None, done)

    second = s.turn(A, body("$password = 'p@ssw0rd-prod-1'; return 1;"), 'p2')
    check('a different rule opens a new cycle', second['decision'] == 'block', second)

    back = s.turn(A, body('dd(1);'), 'p2', stop_hook_active=True)
    check('a settled rule the fix brought back is still seen',
          back['decision'] == 'block', back)
    check('and it is reported as new', '새로 생겼습니다' in back['reason'], back['reason'])


def case_over_budget_is_not_new(repo, data):
    s = Session(repo, data, 'budget')
    lines = HDR + 'class A {\n' + '\n'.join(
        '    public function f%d() { dd(%d); }' % (i, i) for i in range(6)) + '\n}\n'
    first = s.turn(A, lines, 'p1')
    check('the first block shows only the per-rule budget',
          first['reason'].count('dd(') == 3, first['reason'])
    fixed_three = HDR + 'class A {\n' + '\n'.join(
        '    public function f%d() { %s }' % (i, 'return 1;' if i < 3 else 'dd(%d);' % i)
        for i in range(6)) + '\n}\n'
    verify = s.turn(A, fixed_three, 'p1', stop_hook_active=True)
    check('candidates that existed but were not shown are not "new"',
          'new' not in outcomes(s), s.events('verify'))
    check('with the shown ones fixed the turn passes', verify['decision'] is None, verify)


def case_dismissed_in_cycle(repo, data):
    s = Session(repo, data, 'dismiss')
    first = s.turn(A, body(), 'p1')
    check('the finding blocks first', first['decision'] == 'block', first)
    proc = run_script('dismiss.py', ['--rule', 'core/php-no-debug-output', '--file', A,
                                     '--line', '4', '--reason', '일회성 디버그 도구라 예외'],
                      env=s.env, cwd=repo)
    check('dismiss.py succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    s.touch(A)
    verify = s.stop('p1', stop_hook_active=True)
    check('a dismissed finding does not block', verify['decision'] is None, verify)
    check('it is logged as dismissed, not unfixed', outcomes(s) == ['dismissed'],
          s.events('verify'))

    changed = s.turn(A, body('dd(1); dd(2);'), 'p2')
    check('changed code is judged again (the budget was not spent)',
          changed['decision'] == 'block', changed)


def case_abandoned_request(repo, data):
    s = Session(repo, data, 'abandon')
    s.turn(A, body(), 'p1')
    # the user interrupts and sends something else; the old finding is still there
    other = s.turn('app/Svc/B.php', body('return 3;', 'B'), 'p2')
    check('the old cycle is closed as abandoned',
          [e for e in s.events('abandoned')], s.events())
    check('its outcome is still measured', outcomes(s) == ['still'], s.events('verify'))
    check('the unfixed finding is raised again for the new request',
          other['decision'] == 'block', other)


def case_new_occurrence_is_not_a_repeat(repo, data):
    s = Session(repo, data, 'newloc')
    s.turn(A, body(), 'n1')
    s.turn(A, body('return 1;'), 'n1', stop_hook_active=True)
    third = s.turn('app/Svc/B.php', body('dd(2);', 'B'), 'n2')
    check('the same rule in another file is reported', third['decision'] == 'block', third)
    check('it is not labelled as a repeat', '지난 턴에 지적했는데' not in third['reason'])


def case_consecutive_cap(repo, data):
    s = Session(repo, data, 'cap')
    bodies = ['dd(1);', 'var_dump(2);', 'print_r(3);', 'dd(4);']
    results = [s.turn(A, body(b), 'q%d' % i) for i, b in enumerate(bodies)]
    blocked = [r['decision'] == 'block' for r in results]
    check('blocks up to the consecutive cap', blocked == [True, True, True, False], blocked)
    check('the held-back finding is still reported', '상한' in results[3]['summary'],
          results[3]['summary'])
    s.turn(A, body('return 1;'), 'q9')
    check('a clean turn resets the streak', s.state()['consecutive_blocks'] == 0, s.state())
    again = s.turn(A, body('dd(9);'), 'q10')
    check('the checker is alive later in the session', again['decision'] == 'block', again)


def case_report_mode(repo, data):
    s = Session(repo, data, 'report', CLAUDE_PLUGIN_OPTION_REPORT_ONLY='true')
    result = s.turn(A, body(), 'r1')
    check('report mode does not block', result['decision'] is None, result)
    check('report mode says so', 'report' in result['summary'], result['summary'])
    cands = s.events('candidate')
    check('candidates are logged', len(cands) >= 1, s.events())
    check('nothing is logged as shown', all(not c['shown'] for c in cands), cands)


def case_question_turn(repo, data):
    s = Session(repo, data, 'question')
    result = s.turn(A, body(), 'p1', message='이 방식으로 진행할까요?')
    check('a turn ending in a question is not checked', result['decision'] is None, result)
    check('and no cycle is opened', s.state()['cycle'] is None)


def case_commit_before_first_stop(repo, data):
    write(repo, '.claude/convention-guard/config.yaml',
          'mode: fix\nscope:\n  base_ref: HEAD\nonce_per_session: false\n')
    commit(repo, 'configure explicit base')
    s = Session(repo, data, 'commit-first')
    # collect the edit, then commit before the Stop hook gets its first chance
    write(repo, A, body())
    s.touch(A)
    commit(repo, 'agent commit')
    result = s.stop('p1')
    check('a change committed before Stop is still inspected',
          result['decision'] == 'block', result)


def case_commit_during_open_cycle(repo, data):
    s = Session(repo, data, 'commit-cycle')
    first = s.turn(A, body(), 'p1')
    check('the violation opens a cycle before commit', first['decision'] == 'block', first)
    commit(repo, 'commit unresolved violation')
    s.touch(A)
    verify = s.stop('p1', stop_hook_active=True)
    check('committing an unresolved violation does not classify it as fixed',
          verify['decision'] == 'block' and '아직 그대로' in verify['reason'], verify)


def case_no_prompt_ids(repo, data):
    """Claude Code does not always send prompt ids; continuation alone must work."""
    s = Session(repo, data, 'noprompt')
    first = s.turn(A, body(), None)
    check('blocks without a prompt id', first['decision'] == 'block', first)
    done = s.turn(A, body('return 1;'), None, stop_hook_active=True)
    check('verifies without a prompt id', done['decision'] is None and outcomes(s) == ['fixed'],
          (done, s.events('verify')))
    s.touch(A)
    extra = s.stop(None, stop_hook_active=True)
    check('another hook continuing the same request does not reopen a cycle',
          extra['decision'] is None and s.state()['cycle'] is None, extra)


CASES = [
    (case_fixed_passes, ''),
    (case_still_blocks_once_more, 'once_per_session: false\n'),
    (case_new_violation_from_fix, 'once_per_session: false\n'),
    (case_settled_rule_can_come_back, ''),
    (case_over_budget_is_not_new, ''),
    (case_dismissed_in_cycle, ''),
    (case_abandoned_request, 'once_per_session: false\n'),
    (case_new_occurrence_is_not_a_repeat, 'once_per_session: false\n'),
    (case_consecutive_cap, 'once_per_session: false\n'),
    (case_report_mode, 'mode: report\n'),
    (case_question_turn, ''),
    (case_commit_before_first_stop, 'once_per_session: false\n'),
    (case_commit_during_open_cycle, 'once_per_session: false\n'),
    (case_no_prompt_ids, ''),
]


def main():
    for case, config in CASES:
        print('%s:' % case.__name__)
        with tempdir() as repo, tempdir() as data:
            make_repo(repo, repo_files(config))
            case(repo, data)
    return finish('Stop 훅 검증 사이클')


if __name__ == '__main__':
    sys.exit(main())
