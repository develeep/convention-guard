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


THIN = rule('local/thin', kind='unit', review={'instruction': 'thin?'})
PURE = rule('local/pure', kind='unit', review={'instruction': 'pure?'})


def unit(rid, code, file):
    return Candidate(rid, file, 5, code, code=code)


def verdicts(*pairs):
    return {c.review_key: {'verdict': v} for c, v in pairs}


def batch_rules(d):
    return sorted(item['rule_id'] for item in d.batch[1]['items']) if d.batch else []


def case_unit_pages():
    print('case_unit_pages:')
    a1, a2 = unit('local/thin', 'f1', 'F.php'), unit('local/thin', 'f2', 'F.php')
    tight = cfg(limits={'max_consecutive_blocks': 1})
    tight['semantic_review']['max_candidates'] = 1
    opened = decide.decide({}, obs(view(pending=[(THIN, a1, Pack()), (THIN, a2, Pack())])), tight)
    check('a unit rule asks one page at a time', len(opened.batch[1]['items']) == 1,
          opened.batch)
    page = decide.decide(opened.state, obs(view(pending=[(THIN, a2, Pack())]), continuing=True,
                                           cycle_verdicts=verdicts((a1, 'VALID'))), tight)
    check('the next page of open-time units is asked past the streak cap',
          page.action.kind == 'block' and batch_rules(page) == ['local/thin'], page.action)
    check('and does not count toward the streak', page.state['consecutive_blocks'] == 1,
          page.state)


def case_unit_verify_scope():
    print('case_unit_verify_scope:')
    a, b = unit('local/thin', 'f1', 'F.php'), unit('local/pure', 'g1', 'G.php')
    opened = decide.decide({}, obs(view(pending=[(THIN, a, Pack()), (PURE, b, Pack())])), cfg())
    a2, b2 = unit('local/thin', 'f1 fixed', 'F.php'), unit('local/pure', 'g1 edited', 'G.php')
    told = verdicts((a, 'VIOLATION'), (b, 'VALID'))
    d = decide.decide(opened.state, obs(view(pending=[(THIN, a2, Pack()), (PURE, b2, Pack())]),
                                        continuing=True, cycle_verdicts=told), cfg())
    check('a rule that found a violation is asked again', d.action.kind == 'block'
          and batch_rules(d) == ['local/thin'], (d.action, batch_rules(d)))
    check('a rule that found none is held, not asked',
          d.action.args.get('held') == 1, d.action.args)

    held = decide.decide(opened.state, obs(view(pending=[(PURE, b2, Pack())]), continuing=True,
                                           cycle_verdicts=verdicts((a, 'VALID'), (b, 'VALID'))),
                         cfg())
    check('held units alone end the cycle without blocking', held.action.kind == 'notice'
          and held.action.word == '재검증 종료'
          and '재검증 범위 밖 판정 보류 1' in held.action.parts, held.action)
    check('and are logged as skipped for the verify scope',
          [e['reason'] for e in held.events if e['event'] == 'review_skipped'] == ['verify_scope'],
          held.events)

    c = unit('local/thin', 'h1', 'H.php')
    asked = decide.decide(opened.state, obs(view(pending=[(THIN, a2, Pack()), (THIN, c, Pack())]),
                                            continuing=True, cycle_verdicts=told), cfg())
    check('every changed unit of the violated rule is asked', len(asked.batch[1]['items']) == 2,
          asked.batch)
    other = decide.decide(asked.state, obs(view(violations=[(THIN, c, {})]), continuing=True,
                                           cycle_verdicts=verdicts((a2, 'VALID'),
                                                                   (c, 'VIOLATION'))), cfg())
    check('a violation in another file during verification is reported, not blocked',
          other.action.kind == 'notice' and '보고만 1' in other.action.parts, other.action)
    check('and logged as reported',
          [e['outcome'] for e in other.events if e['event'] == 'verify'
           and e['key'] == c.key] == ['reported'], other.events)
    same = decide.decide(asked.state, obs(view(violations=[(THIN, a2, {})]), continuing=True,
                                          cycle_verdicts=verdicts((a2, 'VIOLATION'),
                                                                  (c, 'VALID'))), cfg())
    check('a violation again in the file being fixed blocks',
          same.action.kind == 'block' and a2.key in same.action.args['outcome'].still,
          same.action)


def case_unit_asked_twice():
    print('case_unit_asked_twice:')
    a = unit('local/thin', 'f1', 'F.php')
    opened = decide.decide({}, obs(view(pending=[(THIN, a, Pack())])), cfg())
    again = decide.decide(opened.state, obs(view(pending=[(THIN, a, Pack())]), continuing=True,
                                            cycle_verdicts={}), cfg())
    check('a question asked again in the cycle gets no free block',
          not (again.action.kind == 'block' and again.state['consecutive_blocks'] == 1),
          (again.action, again.state))

    c = unit('local/thin', 'g1', 'F.php')
    opened = decide.decide({}, obs(view(pending=[(THIN, a, Pack()), (THIN, c, Pack())])), cfg())
    told = verdicts((a, 'VIOLATION'), (c, 'VALID'))
    a2 = unit('local/thin', 'f1 fixed', 'F.php')
    c2 = unit('local/thin', 'g1', 'F.php')
    c2.review_hash = 'importschanged'       # same code, new context: asked again
    asked = decide.decide(opened.state, obs(view(pending=[(THIN, a2, Pack()),
                                                          (THIN, c2, Pack())]),
                                            continuing=True, cycle_verdicts=told), cfg())
    check('an answered unit whose context changed is a re-ask, not a page',
          [i['page'] for i in asked.state['cycle']['review']['items'].values()] == [False, False],
          asked.state['cycle']['review'])
    flip = decide.decide(asked.state, obs(view(violations=[(THIN, c2, {})]), continuing=True,
                                          cycle_verdicts=verdicts((a2, 'VALID'),
                                                                  (c2, 'VIOLATION'))), cfg())
    check('a unit judged VALID earlier in the cycle that now reads VIOLATION is reported',
          flip.action.kind == 'notice' and '보고만 1' in flip.action.parts, flip.action)


def case_unit_not_quiet():
    print('case_unit_not_quiet:')
    a = unit('local/thin', 'f1', 'F.php')
    d = decide.decide({'fired_rules': ['local/thin']}, obs(view(pending=[(THIN, a, Pack())])),
                      cfg())
    check('once_per_session does not silence a unit rule', d.action.kind == 'block'
          and d.batch is not None, d.action)


def case_classify_reports_new_units():
    print('case_classify_reports_new_units:')
    cycle = decide.new_cycle('c1', 'p1', {}, [])
    meta = decide.entry(THIN, unit('local/thin', 'f1', 'F.php'))
    out = decide.classify(cycle, {'k': meta}, lambda _k: False)
    check('a new unit finding is reported, not new', list(out.reported) == ['k']
          and not out.new and not out.blocking(), (out.new, out.reported))


def case_dropped_is_not_fixed():
    print('case_dropped_is_not_fixed:')
    state = opened_by({}, X)
    # the engine finished installing (or the rule was turned off) between the
    # block and the re-scan: the candidate is gone, the code is not
    d = decide.decide(state, obs(view(), continuing=True,
                                 still_written=lambda key: key == X.key), cfg())
    outcomes = [e['outcome'] for e in d.events if e['event'] == 'verify']
    check('gone from the scan with its code still written is dropped, not fixed',
          outcomes == ['dropped'], outcomes)
    check('nothing to fix: the re-scan passes and says what dropped out',
          d.action.kind == 'notice' and d.action.word == '재검증 통과'
          and '검사에서 빠짐 1' in d.action.parts and '고쳐짐 0' in d.action.parts, d.action)
    check('and its rule is not settled', d.state['fired_rules'] == [], d.state)

    cycle = decide.new_cycle('c1', 'p1', {X.key: decide.entry(DD, X)}, [])
    out = decide.classify(cycle, {}, lambda _k: False)
    check('without the predicate, gone is fixed', list(out.fixed) == [X.key], out.counts())
    out = decide.classify(cycle, {}, lambda _k: True, still_written=lambda _k: True)
    check('a dismissal wins over dropped', list(out.dismissed) == [X.key], out.counts())
    judged = rule('core/n1', 'warn', review={'question': 'q'})
    cycle = decide.new_cycle('c1', 'p1', {X.key: decide.entry(judged, X)}, [])
    out = decide.classify(cycle, {}, lambda _k: False, still_written=lambda _k: True)
    check('a judged rule is fixed around its line: gone is fixed', list(out.fixed) == [X.key],
          out.counts())



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
                 case_semantic, case_unit_pages, case_unit_verify_scope, case_unit_asked_twice,
                 case_unit_not_quiet,
                 case_classify_reports_new_units, case_dropped_is_not_fixed, case_pure):
        case()
    sys.exit(finish('decide 전이 표'))
