#!/usr/bin/env python3
"""End-to-end Stop-hook behaviour: the budget, the followup, the dismissal.

Runs the real hook scripts over a real repo, because the failures these cover
only appear across turns:

1. The old session cap turned the checker off for the rest of the session
   after two blocks. A long session got two findings and then silence.
2. `pending` was never cleared on a non-blocking turn, so one block produced a
   followup record every turn afterwards.
3. `block_level: report` logged findings as `shown: true` while showing the
   agent nothing.
4. A finding the agent declined as a false positive was logged as
   `fixed: false`, indistinguishable from one it ignored.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, finish, make_repo,  # noqa: E402
                     run_script, tempdir)

HDR = '<?php\ndeclare(strict_types=1);\nnamespace App;\n'


def repo_files(**config):
    files = {'composer.json': LARAVEL_COMPOSER}
    for name in ('A', 'B'):
        files['app/Svc/%s.php' % name] = \
            HDR + 'class %s { public function f() { return 1; } }\n' % name
    if config:
        files['.claude/convention-guard/config.yaml'] = ''.join(
            '%s: %s\n' % (key, json.dumps(value)) for key, value in config.items())
    return files


def debug(body='dd(1);'):
    return HDR + 'class A { public function f() { %s } }\n' % body


def case_followup_counted_once(repo, data):
    session = Session(repo, data, 'follow')
    rel = 'app/Svc/A.php'

    first = session.turn(rel, debug(), 'p1')
    check('a new error blocks', first['decision'] == 'block', first)
    check('the reason names the dismissal command', 'dismiss.py' in first['reason'],
          first['reason'][-300:])
    check('one block is recorded', session.state()['consecutive_blocks'] == 1,
          session.state())

    fixed = session.turn(rel, debug('return 1;'), 'p1', stop_hook_active=True)
    check('the same prompt is not blocked twice', fixed['decision'] is None, fixed)
    followups = session.events('followup')
    check('exactly one followup for one block', len(followups) == 1, followups)
    check('the fix is recorded as fixed', followups and followups[0].get('fixed') is True,
          followups)

    later = session.turn(rel, debug('dd(3);'), 'p2')
    check('once_per_session keeps a fixed rule quiet afterwards',
          later['decision'] is None, later)
    check('still exactly one followup on record',
          len(session.events('followup')) == 1, session.events('followup'))


def case_unfixed_is_raised_again(repo, data):
    session = Session(repo, data, 'again')
    rel = 'app/Svc/A.php'
    session.turn(rel, debug(), 'u1')
    session.touch(rel)
    ignored = session.stop('u1', stop_hook_active=True)      # nothing fixed
    check('the ignoring turn is not blocked', ignored['decision'] is None, ignored)
    followups = session.events('followup')
    check('it is recorded as not fixed', followups and followups[0].get('fixed') is False,
          followups)

    again = session.turn(rel, debug(), 'u2')
    check('an unfixed finding comes back', again['decision'] == 'block', again)
    check('and says it was already raised', '지난 턴에 지적했는데' in again['reason'],
          again['reason'][:200])


def case_new_occurrence_is_not_a_repeat(repo, data):
    session = Session(repo, data, 'newloc')
    session.turn('app/Svc/A.php', debug(), 'n1')
    session.turn('app/Svc/A.php', debug('return 1;'), 'n1', stop_hook_active=True)
    third = session.turn('app/Svc/B.php',
                         HDR + 'class B { public function f() { dd(2); } }\n', 'n2')
    check('the same rule in another file is reported', third['decision'] == 'block', third)
    check('it is not labelled as a repeat', '지난 턴에 지적했는데' not in third['reason'],
          third['reason'][:300])


def case_consecutive_cap(repo, data):
    session = Session(repo, data, 'cap')
    rel = 'app/Svc/A.php'
    bodies = ['dd(1);', 'var_dump(2);', 'print_r(3);', 'dd(4);']
    results = [session.turn(rel, debug(body), 'q%d' % i) for i, body in enumerate(bodies)]
    blocked = [r['decision'] == 'block' for r in results]
    check('blocks up to the consecutive cap', blocked[:3] == [True, True, True], blocked)
    check('the 4th consecutive block is held back', blocked[3] is False, results[3])
    check('the held-back finding is still reported to the user',
          '상한' in results[3]['summary'], results[3]['summary'])

    session.turn(rel, debug('return 1;'), 'q9')          # a clean turn
    check('a clean turn resets the streak', session.state()['consecutive_blocks'] == 0,
          session.state())
    again = session.turn(rel, debug('dd(9);'), 'q10')
    check('the checker is alive later in the session', again['decision'] == 'block', again)


def case_report_only(repo, data):
    session = Session(repo, data, 'report', CLAUDE_PLUGIN_OPTION_REPORT_ONLY='true')
    result = session.turn('app/Svc/A.php', debug(), 'r1')
    check('report mode does not block', result['decision'] is None, result)
    check('report mode says so', 'report' in result['summary'], result['summary'])
    check('nothing is logged as shown',
          all(not m.get('shown') for m in session.events('match')), session.events('match'))


def case_dismissal(repo, data):
    session = Session(repo, data, 'dismiss')
    rel = 'app/Svc/A.php'
    first = session.turn(rel, debug(), 'd1')
    check('the finding blocks first', first['decision'] == 'block', first)

    proc = run_script('dismiss.py', ['--rule', 'core/php-no-debug-output', '--file', rel,
                                     '--line', '4', '--reason', '일회성 디버그 도구라 예외'],
                      env=session.env, cwd=repo)
    check('dismiss.py succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    check('the record lands in the repo',
          os.path.isfile(os.path.join(repo, '.claude', 'convention-guard',
                                      'dismissed.yaml')), proc.stdout)

    session.touch(rel)
    second = session.stop('d2')
    check('the dismissed finding is not raised again', second['decision'] is None, second)
    declined = [e for e in session.events('followup') if e.get('dismissed')]
    check('the outcome is logged as declined, not unfixed', len(declined) == 1,
          session.events('followup'))

    third = session.turn(rel, debug('dd(1); dd(2);'), 'd3')
    check('changed code is judged again', third['decision'] == 'block', third)


CASES = [
    (case_followup_counted_once, {}),
    (case_unfixed_is_raised_again, {}),
    # these two need more than one block from one rule
    (case_new_occurrence_is_not_a_repeat, {'once_per_session': False}),
    (case_consecutive_cap, {'once_per_session': False}),
    (case_report_only, {}),
    (case_dismissal, {}),
]


def main():
    for case, config in CASES:
        print('%s:' % case.__name__)
        with tempdir() as repo, tempdir() as data:
            make_repo(repo, repo_files(**config))
            case(repo, data)
    return finish('세션 정책 / 후속 추적 / 기각')


if __name__ == '__main__':
    sys.exit(main())
