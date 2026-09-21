#!/usr/bin/env python3
"""Semantic review through the real hook, with the reviewer played by the test.

The reviewer subagent's whole contract is `review.py show` then
`review.py record`, so the test runs exactly those two commands in its place.

1. No candidate, no AI: without a gated candidate nothing is requested.
2. A candidate without a cached verdict blocks with one command to hand over.
3. VIOLATION -> the agent fixes -> the function changed -> judged again once.
4. VALID is cached: the same code is never sent to a reviewer twice.
5. A reviewer that never ran is asked for once more, then the cycle closes.
6. review.py refuses an incomplete record and writes nothing.
7. report mode requests nothing; scan.py --review makes a batch and counts
   cached VIOLATIONs as findings.
8. --review with no semantic candidate asks for no reviewer at all.
9. VALID, FALSE_POSITIVE and VIOLATION are recorded as three different things.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, finish, isolated_env,  # noqa: E402
                     make_repo, run_script, tempdir)

CTRL = 'app/Http/Controllers/OrderController.php'
HEAD = ('<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Http\\Controllers;\n\n'
        'use App\\Models\\Order;\n\nclass OrderController extends Controller\n{\n')
MODEL = ('<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Models;\n\n'
         'class Order extends Model\n{\n    public function items()\n    {\n'
         '        return $this->hasMany(OrderItem::class);\n    }\n}\n')


def controller(query="Order::query()->get()", loop=True):
    body = ('    public function index()\n    {\n        $orders = %s;\n' % query)
    if loop:
        body += ('        foreach ($orders as $order) {\n'
                 '            $order->items->count();\n        }\n')
    body += '        return $orders;\n    }\n'
    return HEAD + body + '}\n'


def controller_many(count):
    methods = []
    for index in range(count):
        methods.append(
            '    public function index%d()\n'
            '    {\n'
            '        $orders = Order::query()->with("items")->get();\n'
            '        foreach ($orders as $order) {\n'
            '            $order->items->count();\n'
            '        }\n'
            '        return $orders;\n'
            '    }\n' % index)
    return HEAD + ''.join(methods) + '}\n'


def repo_files(config='mode: fix\nsemantic_review:\n  enabled: true\n'):
    return {'composer.json': LARAVEL_COMPOSER, 'app/Models/Order.php': MODEL,
            CTRL: controller(loop=False),
            '.claude/convention-guard/config.yaml': config}


def batch_of(result):
    match = re.search(r'review\.py" show "([^"]+)"', result['reason'])
    return match.group(1) if match else None


def record(session, batch, verdict, reason='근거'):
    shown = run_script('review.py', ['show', batch], env=session.env, cwd=session.repo)
    ids = [int(i) for i in re.findall(r'^### 후보 (\d+)', shown.stdout, re.M)]
    answers = [{'id': i, 'verdict': verdict, 'reason': reason} for i in ids]
    return shown, run_script('review.py', ['record', batch], stdin=json.dumps(answers),
                             env=session.env, cwd=session.repo)


def reviews(session):
    base = os.path.join(session.data, 'reviews')
    return sorted(n for n in os.listdir(base) if n.endswith('.json')
                  and not n.endswith('.verdicts.json')) if os.path.isdir(base) else []


# ---------------------------------------------------------------- cases

def case_no_candidate_no_ai(repo, data):
    s = Session(repo, data, 'quiet')
    result = s.turn(CTRL, controller(query="Order::query()->count()", loop=False), 'p1')
    check('a change without a gated candidate passes', result['decision'] is None, result)
    check('and no batch is written', reviews(s) == [], reviews(s))


def case_violation_fix_rejudge(repo, data):
    s = Session(repo, data, 'violation')
    first = s.turn(CTRL, controller(), 'p1')
    check('an unreviewed candidate blocks', first['decision'] == 'block', first)
    batch = batch_of(first)
    check('the reason hands over one review command', batch and os.path.isfile(batch),
          first['reason'])
    check('the reason names the reviewer agent', 'convention-reviewer' in first['reason'])

    shown, rec = record(s, batch, 'VIOLATION', 'orders 를 with 없이 반복하며 items 접근')
    check('show prints the context pack with the eager-load-less query',
          'Order::query()->get()' in shown.stdout and '감싸는 함수' in shown.stdout, shown.stdout)
    check('show includes the related model', 'hasMany(OrderItem::class)' in shown.stdout)
    check('record succeeds', rec.returncode == 0, rec.stdout + rec.stderr)
    check('record prints the violation to hand back', '[core/laravel-n-plus-one]' in rec.stdout,
          rec.stdout)

    fixed = s.turn(CTRL, controller(query="Order::query()->with('items')->get()"), 'p1',
                   stop_hook_active=True)
    check('the changed function is sent for judgment again', fixed['decision'] == 'block', fixed)
    rebatch = batch_of(fixed)
    check('as a new batch', rebatch and rebatch != batch, fixed['reason'])
    check('the flagged violation is logged fixed',
          [e['outcome'] for e in s.events('verify')] == ['fixed'], s.events('verify'))

    _, rec = record(s, rebatch, 'VALID', 'with(items) 로 로드됨')
    check('the second record succeeds', rec.returncode == 0, rec.stderr)
    s.touch(CTRL)
    done = s.stop('p1', stop_hook_active=True)
    check('with the new verdict VALID the turn passes', done['decision'] is None, done)
    check('verdicts are logged', len(s.events('verdict')) == 2, s.events('verdict'))


def case_valid_is_cached(repo, data):
    s = Session(repo, data, 'cached')
    first = s.turn(CTRL, controller(query="Order::query()->with('items')->get()"), 'p1')
    batch = batch_of(first)
    record(s, batch, 'VALID', '이미 로드됨')
    s.touch(CTRL)
    done = s.stop('p1', stop_hook_active=True)
    check('a VALID verdict clears the cycle', done['decision'] is None, done)

    other = Session(repo, data, 'cached-2')
    again = other.turn(CTRL, controller(query="Order::query()->with('items')->get()"), 'q1')
    check('the same code in a new session is not reviewed again', again['decision'] is None,
          again)
    check('only one batch was ever written', len(reviews(s)) == 1, reviews(s))


def case_reviewer_skipped(repo, data):
    s = Session(repo, data, 'skipped')
    s.turn(CTRL, controller(), 'p1')
    s.touch(CTRL)
    again = s.stop('p1', stop_hook_active=True)
    check('a review that never ran is requested once more', again['decision'] == 'block', again)
    check('saying it was skipped', '실행되지 않았습니다' in again['reason'], again['reason'])
    s.touch(CTRL)
    last = s.stop('p1', stop_hook_active=True)
    check('then the cycle closes without blocking', last['decision'] is None, last)
    check('reporting what could not be judged', '판정 못 한 후보' in last['summary'],
          last['summary'])
    check('the skip is logged', any(e['reason'] == 'not_run' for e in s.events('review_skipped')),
          s.events('review_skipped'))


def case_record_validation(repo, data):
    s = Session(repo, data, 'validate')
    first = s.turn(CTRL, controller(), 'p1')
    batch = batch_of(first)
    for label, answers, needle in (
            ('missing ids', [], '빠진 후보'),
            ('bad verdict', [{'id': 1, 'verdict': 'MAYBE', 'reason': 'x'}], 'verdict'),
            ('empty reason', [{'id': 1, 'verdict': 'VALID', 'reason': ''}], 'reason'),
            ('unknown id', [{'id': 9, 'verdict': 'VALID', 'reason': 'x'}], '없는 후보')):
        proc = run_script('review.py', ['record', batch], stdin=json.dumps(answers),
                          env=s.env, cwd=repo)
        check('record refuses %s' % label, proc.returncode == 2 and needle in proc.stderr,
              proc.stderr)
    check('nothing was written', not os.path.exists(batch[:-5] + '.verdicts.json'))


def case_report_mode(repo, data):
    with open(os.path.join(repo, '.claude/convention-guard/config.yaml'),
              'w', encoding='utf-8') as fh:
        fh.write('mode: report\nsemantic_review:\n  enabled: true\n')
    s = Session(repo, data, 'report', CLAUDE_PLUGIN_OPTION_REPORT_ONLY='true')
    result = s.turn(CTRL, controller(), 'p1')
    check('report mode does not request a review', result['decision'] is None
          and reviews(s) == [], result)
    check('the skipped review is logged',
          any(e['reason'] == 'mode=report' for e in s.events('review_skipped')), s.events())


def case_deferred_batches_continue(repo, data):
    config = ('mode: fix\nsemantic_review:\n  enabled: true\n  max_candidates: 1\n'
              'limits:\n  max_verify_attempts: 1\n  max_consecutive_blocks: 4\n')
    with open(os.path.join(repo, '.claude/convention-guard/config.yaml'),
              'w', encoding='utf-8') as fh:
        fh.write(config)
    s = Session(repo, data, 'deferred')
    result = s.turn(CTRL, controller_many(3), 'p1')
    batches = []
    for index in range(3):
        batch = batch_of(result)
        check('deferred batch %d is requested' % (index + 1),
              batch and batch not in batches, result)
        if not batch:
            return
        batches.append(batch)
        record(s, batch, 'VALID', 'with(items) 로 로드됨')
        s.touch(CTRL)
        result = s.stop('p1', stop_hook_active=True)
    check('all deferred candidates are judged before the cycle closes',
          result['decision'] is None and len(batches) == 3, (result, batches))


def case_scan_review(repo, data):
    s = Session(repo, data, 'scan')
    with open(os.path.join(repo, CTRL), 'w', encoding='utf-8') as fh:
        fh.write(controller())
    env = isolated_env(data)
    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--review', '--json',
                                  '--fail-on', 'warn'], env=env, cwd=repo)
    report = json.loads(proc.stdout)
    batch = (report['head'].get('review') or {}).get('batch')
    check('scan --review writes a batch', batch and os.path.isfile(batch), report['head'])
    check('an unjudged candidate is not a finding', proc.returncode == 0, proc.returncode)

    record(s, batch, 'VIOLATION', '로드 안 됨')
    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--review', '--json',
                                  '--fail-on', 'warn'], env=env, cwd=repo)
    report = json.loads(proc.stdout)
    ids = [f['rule_id'] for f in report['findings']]
    check('a cached VIOLATION is a finding', 'core/laravel-n-plus-one' in ids, ids)
    check('and fails a warn gate', proc.returncode == 1, proc.returncode)


def case_scan_review_without_candidates(repo, data):
    """A run with nothing for a reviewer to judge must not summon one: no
    batch, no hand-over command, no cost."""
    with open(os.path.join(repo, CTRL), 'w', encoding='utf-8') as fh:
        fh.write(controller(query="Order::query()->count()", loop=False))
    env = isolated_env(data)
    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--review', '--json'],
                      env=env, cwd=repo)
    report = json.loads(proc.stdout)
    check('the change has no semantic candidate', report['head']['semantic'] == 0, report['head'])
    check('so --review does nothing', report['head']['review'] is None, report['head'])
    base = os.path.join(data, 'reviews')
    check('no batch is written', not os.path.isdir(base) or os.listdir(base) == [],
          base)

    proc = run_script('scan.py', ['--cwd', repo, '--no-lint', '--review', '--no-color'],
                      env=env, cwd=repo)
    check('and no reviewer command is printed', 'review.py' not in proc.stdout, proc.stdout)


def case_verdicts_stay_distinct(repo, data):
    """VALID and FALSE_POSITIVE both mean "not a violation", but they say
    different things about the rule, so they are never merged: only VIOLATION
    is handed back, and all three are counted and logged apart for rule-tune.
    """
    s = Session(repo, data, 'distinct')
    first = s.turn(CTRL, controller_many(3), 'p1')
    batch = batch_of(first)
    shown = run_script('review.py', ['show', batch], env=s.env, cwd=repo)
    ids = [int(i) for i in re.findall(r'^### 후보 (\d+)', shown.stdout, re.M)]
    check('three candidates are up for judgment', len(ids) == 3, ids)
    if len(ids) != 3:
        return
    wanted = dict(zip(ids, ('VIOLATION', 'VALID', 'FALSE_POSITIVE')))
    answers = [{'id': i, 'verdict': v, 'reason': '%s 근거' % v} for i, v in wanted.items()]
    rec = run_script('review.py', ['record', batch], stdin=json.dumps(answers),
                     env=s.env, cwd=repo)
    check('the mixed record is accepted', rec.returncode == 0, rec.stdout + rec.stderr)
    check('the summary counts all three apart',
          all(('%s 1' % v) in rec.stdout for v in ('VALID', 'FALSE_POSITIVE', 'VIOLATION')),
          rec.stdout)
    check('only the VIOLATION is handed back to the main agent',
          rec.stdout.count('[core/laravel-n-plus-one]') == 1, rec.stdout)

    logged = sorted(e['verdict'] for e in s.events('verdict'))
    check('each verdict is logged under its own name',
          logged == ['FALSE_POSITIVE', 'VALID', 'VIOLATION'], logged)
    cached = json.load(open(os.path.join(data, 'verdicts.json'), encoding='utf-8'))
    check('and cached under its own name',
          sorted(v['verdict'] for v in cached[repo].values())
          == ['FALSE_POSITIVE', 'VALID', 'VIOLATION'], cached)

    report = json.loads(run_script('log_report.py', ['--json'], env=s.env, cwd=repo).stdout)
    rule = next(r for r in report['rules'] if r['rule_id'] == 'core/laravel-n-plus-one')
    check('rule health reads gate precision and the gate false-positive rate apart',
          abs(rule['precision'] - 1 / 3) < 1e-9
          and abs(rule['false_positive_rate'] - 1 / 3) < 1e-9, rule)


CASES = [case_no_candidate_no_ai, case_violation_fix_rejudge, case_valid_is_cached,
         case_reviewer_skipped, case_record_validation, case_report_mode,
         case_deferred_batches_continue, case_scan_review,
         case_scan_review_without_candidates, case_verdicts_stay_distinct]


def main():
    for case in CASES:
        print('%s:' % case.__name__)
        with tempdir() as repo, tempdir() as data:
            make_repo(repo, repo_files())
            case(repo, data)
    return finish('의미 판정')


if __name__ == '__main__':
    sys.exit(main())
