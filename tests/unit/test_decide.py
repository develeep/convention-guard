#!/usr/bin/env python3
"""decide(): the verification cycle as a table -- state × observation -> decision.

Each row is one transition, with no repo, no hook and no database. The
end-to-end turns stay in tests/integration/test_hook_cycle.py; these pin the
rules the 3.2 review found broken one at a time (R3, R4, R17) and keep
decide.py pure: it imports nothing that touches the world.
"""

import ast
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish  # noqa: E402
from lib import config as configlib, decide  # noqa: E402
from lib.candidate import Candidate  # noqa: E402


def cfg(**over):
    values = copy.deepcopy(configlib.DEFAULTS)
    values['mode'] = 'fix'
    limits = over.pop('limits', {})
    values['limits'].update(limits)
    values.update(over)
    return configlib.Config(values, [], None)


def rule(rid='core/dd', severity='error', kind='line', review=None):
    return {'id': rid, 'title': rid, 'severity': severity, 'kind': kind, 'source': 'core',
            'review': review}


def cand(rid='core/dd', code='dd(1);', line=3, file='a.php'):
    return Candidate(rid, file, line, code, code=code)


class Pack:
    lines = 10

    def to_dict(self):
        return {'sections': []}


def view(*hits, **kw):
    return decide.ScanView(hits=list(hits), **kw)


def obs(scan=None, prompt='p1', continuing=False, question=False, **kw):
    kw.setdefault('batch', decide.BatchSlot('b1', '/data/cg.db', '/repo', 's', '/data/log'))
    return decide.Observation(decide.Request(prompt, continuing, question), scan=scan,
                              now=1000.0, **kw)


DD = rule()
WARN = rule('core/console', 'warn')
X = cand()
Y = cand(code='dd(2);', line=4)


def opened_by(state, c, r=DD):
    """The state right after a block on `c`."""
    out = decide.decide(state or {}, obs(view((r, [c]))), cfg())
    return out.state


def case_quiet_paths():
    print('case_quiet_paths:')
    d = decide.decide({}, obs(config_error=None, scan=None), cfg())
    check('nothing to inspect: silent, streak reset and stored',
          d.action.kind == 'silent' and d.state['consecutive_blocks'] == 0, d.state)
    d = decide.decide({'consecutive_blocks': 2}, decide.Observation(
        decide.Request('p1'), config_error='bad yaml'), cfg())
    check('a config error is said and nothing is stored',
          d.action.kind == 'config_error' and d.state is None, (d.action, d.state))
    check('a question turn is not scanned',
          not decide.needs_scan({}, decide.Request('p1', question=True), cfg()))
    check('unless skip_if_question is off',
          decide.needs_scan({}, decide.Request('p1', question=True), cfg(skip_if_question=False)))
    d = decide.decide({}, obs(view(), question=True), cfg())
    check('and decide() is silent on it', d.action.kind == 'silent')
    d = decide.decide({}, obs(decide.ScanFailure('git 레포가 아닙니다')), cfg())
    check('a failed scan is not a pass', d.action.kind == 'config_error'
          and 'git' in d.action.text, d.action)


def case_open():
    print('case_open:')
    state = {'unresolved': []}
    d = decide.decide(state, obs(view((DD, [X]))), cfg())
    check('an error blocks', d.action.kind == 'block' and d.action.form == 'open', d.action)
    check('and opens a cycle on its key', list(d.state['cycle']['opened']) == [X.key],
          d.state['cycle'])
    check('the streak counts it', d.state['consecutive_blocks'] == 1)
    check('the block is logged', [e['event'] for e in d.events][-1] == 'block', d.events)
    check('the input state is untouched', state == {'unresolved': []}, state)

    d = decide.decide({}, obs(view((WARN, [X]))), cfg())
    check('a warn alone does not block', d.action.kind == 'notice'
          and d.action.word == '기록' and d.state['cycle'] is None, d.action)

    d = decide.decide({}, obs(view((DD, [X]))), cfg(mode='report'))
    check('report mode records instead', d.action.kind == 'notice'
          and '차단 안 함: mode=report' in d.action.parts, d.action)


def case_r4_cap_is_per_request():
    print('case_r4_cap_is_per_request:')
    capped = {'consecutive_blocks': 3}
    d = decide.decide(capped, obs(view((DD, [X])), continuing=True), cfg())
    check('the cap holds within one request', d.action.kind == 'notice'
          and any('연속 차단 3회 상한' in p for p in d.action.parts), d.action)
    check('and the held-back turn still counts toward it', d.state['consecutive_blocks'] == 3)
    d = decide.decide(capped, obs(view((DD, [X])), continuing=False), cfg())
    check('a new request starts its own count (R4)', d.action.kind == 'block'
          and d.state['consecutive_blocks'] == 1, d.state)


def case_verify():
    print('case_verify:')
    state = opened_by({}, X)
    d = decide.decide(state, obs(view(), continuing=True), cfg())
    check('fixed: the re-scan passes', d.action.kind == 'notice'
          and d.action.word == '재검증 통과', d.action)
    check('the cycle closes, the rule is settled', d.state['cycle'] is None
          and d.state['fired_rules'] == ['core/dd'], d.state)
    check('and the request is marked done', d.state['closed_in_continuation'] is True)
    check('a later continuation is not scanned again',
          not decide.needs_scan(d.state, decide.Request('p1', continuing=True), cfg()))

    d = decide.decide(state, obs(view((DD, [X])), continuing=True), cfg())
    check('still there: one more block', d.action.kind == 'block'
          and d.action.form == 'verify' and d.state['cycle']['attempt'] == 1, d.action)
    again = decide.decide(d.state, obs(view((DD, [X])), continuing=True), cfg())
    check('past max_verify_attempts it closes and records',
          again.action.kind == 'notice' and again.action.word == '재검증 종료'
          and '이후 기록만' in again.action.parts and again.state['cycle'] is None,
          again.action)
    check('what was left is remembered as unresolved', again.state['unresolved'] == [X.key],
          again.state)

    d = decide.decide(state, obs(view((DD, [Y])), continuing=True), cfg())
    check('a fix that writes another error blocks on it as new', d.action.kind == 'block'
          and list(d.action.args['outcome'].new) == [Y.key], d.action)

    dismissed = decide.decide(state, obs(view(), continuing=True,
                                         is_dismissed=lambda key: key == X.key), cfg())
    out = dismissed.events
    check('a dismissed finding is counted as dismissed, not fixed',
          [e['outcome'] for e in out if e['event'] == 'verify'] == ['dismissed'], out)
    check('and its rule is not settled', dismissed.state['fired_rules'] == [], dismissed.state)


def case_r3_hidden_is_not_a_pass():
    print('case_r3_hidden_is_not_a_pass:')
    many = [cand(code='dd(%d);' % i, line=i) for i in range(1, 6)]
    tight = cfg(limits={'max_locations_per_rule': 1})
    state = decide.decide({}, obs(view((DD, many))), tight).state
    check('the block showed one of five', len(state['cycle']['opened']) == 1, state['cycle'])
    shown = list(state['cycle']['opened'])[0]
    rest = [c for c in many if c.key != shown]
    d = decide.decide(state, obs(view((DD, rest)), continuing=True), tight)
    check('fixing what was shown does not read as a pass (R3)',
          d.action.kind == 'notice' and d.action.word == '재검증 종료'
          and '미표시 4' in d.action.parts, d.action)
    check('the unshown come back next request', sorted(d.state['unresolved'])
          == sorted(c.key for c in rest), d.state['unresolved'])
    check('and the rule is not settled for once_per_session', d.state['fired_rules'] == [])


def case_r17_unfinished_linter():
    print('case_r17_unfinished_linter:')
    fail = {'cmd': 'phpstan', 'key': 'phpstan', 'output': 'boom', 'anchored': True}
    state = decide.decide({}, obs(view(lint_blocking=[fail], lint_raw=[fail])), cfg()).state
    check('a linter failure opens a cycle', 'lint:phpstan' in state['cycle']['opened'], state)
    d = decide.decide(state, obs(view(lint_unfinished={'phpstan'}), continuing=True), cfg())
    check('a linter that did not finish is not fixed (R17)',
          d.action.kind == 'notice' and '린터 미확인 1' in d.action.parts, d.action)


def case_abandoned():
    print('case_abandoned:')
    state = opened_by({}, X)
    d = decide.decide(state, obs(view((DD, [X])), prompt='p2'), cfg())
    kinds = [e['event'] for e in d.events]
    check('a new request closes the old cycle as abandoned', 'abandoned' in kinds, kinds)
    check('and checks the new turn on its own', d.action.kind == 'block'
          and d.state['cycle']['prompt_id'] == 'p2', d.state['cycle'])


def case_semantic():
    print('case_semantic:')
    reviewed = rule('core/n1', 'warn', review={'instruction': 'n+1?'})
    c = cand('core/n1', 'foreach ($a as $b) {')
    pending = [(reviewed, c, Pack())]
    d = decide.decide({}, obs(view(pending=pending)), cfg())
    check('an unjudged candidate blocks with a review request', d.action.kind == 'block'
          and d.action.args['review'] is not None, d.action)
    check('the batch is planned, not written', d.batch is not None
          and d.batch[0] == '/data/cg.db#b1', d.batch)
    check('and the state already names it', d.state['cycle']['review']['batch'] == '/data/cg.db#b1')

    skipped = decide.decide(d.state, obs(view(pending=pending), continuing=True,
                                         cycle_verdicts=None), cfg())
    check('the reviewer never ran: blocked again, said so', skipped.action.kind == 'block'
          and skipped.action.args['skipped'] is True, skipped.action)
    ran = decide.decide(d.state, obs(view(), continuing=True,
                                     cycle_verdicts={c.review_key: {'verdict': 'VALID'}}), cfg())
    check('a VALID verdict closes the cycle', ran.action.kind == 'notice'
          and ran.state['cycle'] is None, ran.action)
    flagged = decide.decide(d.state, obs(view(violations=[(reviewed, c, {})]), continuing=True,
                                         cycle_verdicts={c.review_key: {'verdict': 'VIOLATION'}}),
                            cfg())
    outcomes = [e['outcome'] for e in flagged.events
                if e['event'] == 'verify' and e['key'] == c.key]
    check('a VIOLATION becomes a tracked finding', outcomes == ['still'], flagged.events)
    d = decide.decide({}, obs(view(pending=pending)), cfg(mode='report'))
    check('report mode asks no reviewer', d.batch is None and d.action.kind == 'notice')


def case_pure():
    print('case_pure:')
    allowed = {'copy', 'batch', 'candidate'}
    for name in ('decide.py', 'batch.py', 'candidate.py'):
        with open(os.path.join(ROOT, 'scripts', 'lib', name), encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported |= ({node.module.split('.')[0]} if node.module else
                             {a.name for a in node.names})
        extra = imported - allowed - {'os', 'hashlib'}
        check('%s imports nothing that touches the world' % name, not extra, sorted(extra))


if __name__ == '__main__':
    for case in (case_quiet_paths, case_open, case_r4_cap_is_per_request, case_verify,
                 case_r3_hidden_is_not_a_pass, case_r17_unfinished_linter, case_abandoned,
                 case_semantic, case_pure):
        case()
    sys.exit(finish('decide 전이 표'))
