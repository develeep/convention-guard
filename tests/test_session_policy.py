#!/usr/bin/env python3
"""End-to-end Stop-hook behaviour: the budget, the followup, the dismissal.

Runs the real hook scripts over a real repo, because the failures these cover
only appear across turns:

1. The old session cap turned the checker off for the rest of the session
   after two blocks. A long session got two findings and then silence.
2. `pending` was never cleared on a non-blocking turn, so one block produced a
   followup record every turn afterwards -- the fix-rate number the whole
   tuning cycle reads was double-counted, and a brand-new finding in another
   file was labelled "지난 턴에 지적했는데 그대로입니다".
3. `block_level: report` logged findings as `shown: true` while showing the
   agent nothing.
4. A finding the agent declined as a false positive was logged as
   `fixed: false`, indistinguishable from one it ignored.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []
HDR = '<?php\ndeclare(strict_types=1);\nnamespace App;\n'


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


class Session:
    def __init__(self, repo, data, name='s1', **env):
        self.repo, self.data, self.name = repo, data, name
        self.env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT,
                        CLAUDE_PLUGIN_DATA=data, CLAUDE_PROJECT_DIR=repo, **env)

    def _run(self, script, payload):
        return subprocess.run(['python3', os.path.join(ROOT, 'scripts', script)],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=self.env, cwd=self.repo)

    def touch(self, rel):
        self._run('collect.py', {'session_id': self.name, 'cwd': self.repo,
                                 'tool_name': 'Edit',
                                 'tool_input': {'file_path': rel}})

    def stop(self, prompt_id, message='done.', stop_hook_active=False):
        proc = self._run('check.py', {
            'session_id': self.name, 'cwd': self.repo, 'prompt_id': prompt_id,
            'hook_event_name': 'Stop', 'stop_hook_active': stop_hook_active,
            'last_assistant_message': message})
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return {'decision': out.get('decision'), 'reason': out.get('reason') or '',
                'summary': out.get('systemMessage') or '', 'stderr': proc.stderr}

    def turn(self, rel, body, prompt_id, **kwargs):
        with open(os.path.join(self.repo, rel), 'w', encoding='utf-8') as fh:
            fh.write(body)
        self.touch(rel)
        return self.stop(prompt_id, **kwargs)

    def state(self):
        with open(os.path.join(self.data, 'session-%s.json' % self.name)) as fh:
            return json.load(fh)

    def events(self, kind=None):
        path = os.path.join(self.data, 'firings.jsonl')
        if not os.path.isfile(path):
            return []
        with open(path, encoding='utf-8') as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return [r for r in rows if kind is None or r.get('event') == kind]


def make_repo(tmp, **config):
    subprocess.run(['git', 'init', '-q', tmp], check=True)
    for key, value in (('user.email', 't@t'), ('user.name', 't')):
        subprocess.run(['git', '-C', tmp, 'config', key, value], check=True)
    with open(os.path.join(tmp, 'composer.json'), 'w') as fh:
        fh.write('{"require":{"laravel/framework":"^11.0"}}')
    os.makedirs(os.path.join(tmp, 'app', 'Svc'), exist_ok=True)
    for name in ('A', 'B'):
        with open(os.path.join(tmp, 'app', 'Svc', '%s.php' % name), 'w') as fh:
            fh.write(HDR + 'class %s { public function f() { return 1; } }\n' % name)
    if config:
        cfg_dir = os.path.join(tmp, '.claude', 'convention-rules')
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, 'config.yaml'), 'w') as fh:
            for key, value in config.items():
                fh.write('%s: %s\n' % (key, json.dumps(value)))
    subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', tmp, 'commit', '-q', '-m', 'init'], check=True)


def debug(body='dd(1);'):
    return HDR + 'class A { public function f() { %s } }\n' % body


# ---------------------------------------------------------------- cases

def case_followup_counted_once(tmp, data):
    print('case_followup_counted_once:')
    session = Session(tmp, data, 'follow')
    rel = 'app/Svc/A.php'

    first = session.turn(rel, debug(), 'p1')
    check('a new error blocks', first['decision'] == 'block', first)
    check('the reason names the dismissal command',
          'dismiss.py' in first['reason'], first['reason'][-300:])
    check('one block is recorded', session.state()['consecutive_blocks'] == 1,
          session.state())

    # the agent goes back, fixes it and stops again inside the same prompt --
    # the moment the outcome has to be measured, and the moment the old code
    # skipped without measuring anything
    fixed = session.turn(rel, debug('return 1;'), 'p1', stop_hook_active=True)
    check('the same prompt is not blocked twice', fixed['decision'] is None, fixed)
    followups = session.events('followup')
    check('exactly one followup for one block', len(followups) == 1, followups)
    check('the fix is recorded as fixed', followups[0].get('fixed') is True,
          followups[0])

    later = session.turn(rel, debug('dd(3);'), 'p2')
    check('once_per_session keeps a fixed rule quiet afterwards',
          later['decision'] is None, later)
    check('still exactly one followup on record',
          len(session.events('followup')) == 1, session.events('followup'))


def case_unfixed_is_raised_again(tmp, data):
    print('case_unfixed_is_raised_again:')
    session = Session(tmp, data, 'again')
    rel = 'app/Svc/A.php'
    session.turn(rel, debug(), 'u1')
    session.touch(rel)
    ignored = session.stop('u1', stop_hook_active=True)      # nothing fixed
    check('the ignoring turn is not blocked', ignored['decision'] is None, ignored)
    followups = session.events('followup')
    check('it is recorded as not fixed', followups[0].get('fixed') is False,
          followups)

    again = session.turn(rel, debug(), 'u2')
    check('an unfixed finding comes back', again['decision'] == 'block', again)
    check('and says it was already raised',
          '지난 턴에 지적했는데' in again['reason'], again['reason'][:200])


def case_new_occurrence_is_not_a_repeat(tmp, data):
    print('case_new_occurrence_is_not_a_repeat:')
    session = Session(tmp, data, 'newloc')
    session.turn('app/Svc/A.php', debug(), 'n1')
    session.turn('app/Svc/A.php', debug('return 1;'), 'n1', stop_hook_active=True)
    third = session.turn('app/Svc/B.php',
                         HDR + 'class B { public function f() { dd(2); } }\n', 'n2')
    check('the same rule in another file is reported',
          third['decision'] == 'block', third)
    check('it is not labelled as a repeat',
          '지난 턴에 지적했는데' not in third['reason'], third['reason'][:300])


def case_consecutive_cap(tmp, data):
    print('case_consecutive_cap:')
    session = Session(tmp, data, 'cap')
    rel = 'app/Svc/A.php'
    bodies = ['dd(1);', 'var_dump(2);', 'print_r(3);', 'dd(4);']
    results = [session.turn(rel, debug(body), 'q%d' % i)
               for i, body in enumerate(bodies)]
    blocked = [r['decision'] == 'block' for r in results]
    check('blocks up to the consecutive cap', blocked[:3] == [True, True, True], blocked)
    check('the 4th consecutive block is held back', blocked[3] is False, results[3])
    check('the held-back finding is still reported to the user',
          '상한' in results[3]['summary'], results[3]['summary'])
    check('it is still in the log',
          len([e for e in session.events('match')
               if e['rule_id'] == 'core/php-no-debug-output']) >= 4,
          len(session.events('match')))

    session.turn(rel, debug('return 1;'), 'q9')          # a clean turn
    check('a clean turn resets the streak',
          session.state()['consecutive_blocks'] == 0, session.state())
    again = session.turn(rel, debug('dd(9);'), 'q10')
    check('the checker is alive later in the session',
          again['decision'] == 'block', again)


def case_report_only(tmp, data):
    print('case_report_only:')
    session = Session(tmp, data, 'report', CLAUDE_PLUGIN_OPTION_REPORT_ONLY='true')
    result = session.turn('app/Svc/A.php', debug(), 'r1')
    check('report mode does not block', result['decision'] is None, result)
    check('report mode says so', 'report' in result['summary'], result['summary'])
    matches = session.events('match')
    check('nothing is logged as shown',
          all(not m.get('shown') for m in matches), matches)


def case_dismissal(tmp, data):
    print('case_dismissal:')
    session = Session(tmp, data, 'dismiss')
    rel = 'app/Svc/A.php'
    first = session.turn(rel, debug(), 'd1')
    check('the finding blocks first', first['decision'] == 'block', first)

    proc = subprocess.run(
        ['python3', os.path.join(ROOT, 'scripts', 'dismiss.py'),
         '--rule', 'core/php-no-debug-output', '--file', rel, '--line', '4',
         '--reason', '이 파일은 일회성 디버그 도구라 예외'],
        capture_output=True, text=True, env=session.env, cwd=tmp)
    check('dismiss.py succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    check('the record lands in the repo',
          os.path.isfile(os.path.join(tmp, '.claude', 'convention-rules',
                                      'dismissed.yaml')), proc.stdout)

    session.touch(rel)
    second = session.stop('d2')
    check('the dismissed finding is not raised again',
          second['decision'] is None, second)
    followups = [e for e in session.events('followup') if e.get('dismissed')]
    check('the outcome is logged as declined, not unfixed', len(followups) == 1,
          session.events('followup'))

    # rewriting the dismissed line is a new decision, and the declined finding
    # must not have spent the rule's once-per-session budget
    third = session.turn(rel, debug('dd(1); dd(2);'), 'd3')
    check('changed code is judged again', third['decision'] == 'block', third)


CASES = [case_followup_counted_once, case_unfixed_is_raised_again,
         case_new_occurrence_is_not_a_repeat, case_consecutive_cap,
         case_report_only, case_dismissal]


CONFIG = {
    # these two need more than one block from one rule, which is exactly what
    # once_per_session exists to prevent
    'case_new_occurrence_is_not_a_repeat': {'once_per_session': False},
    'case_consecutive_cap': {'once_per_session': False},
}


def main():
    for case in CASES:
        repo, data = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            make_repo(repo, **CONFIG.get(case.__name__, {}))
            case(repo, data)
        finally:
            shutil.rmtree(repo, ignore_errors=True)
            shutil.rmtree(data, ignore_errors=True)
    if FAILED:
        print('\n실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('\n통과 — 세션 정책 / 후속 추적 / 기각')
    return 0



if __name__ == '__main__':
    sys.exit(main())
