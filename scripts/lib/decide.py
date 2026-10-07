"""What a Stop does, as one pure function.

    decision = decide(state, observation, cfg)
    decision.state    the session state to store, or None (store nothing)
    decision.action   Silent | Notice | ConfigError | Block -- what to say
    decision.events   firing-log records (session and repo are added by the shell)
    decision.batch    (reference, body) of a review batch to store, or None

Everything the Stop hook knows -- the state, the request, what the scan
found, what a reviewer recorded, which keys the team dismissed -- comes in as
values. Nothing here reads a file, the clock or the database, so every
transition can be tested as a table row (tests/unit/test_decide.py), and the
shell (stop.py) is left with fetching, storing, logging and rendering.

The verification cycle, in order:

  1. config broken      -> say so and skip (never check with unchosen defaults)
  2. a cycle is open    -> the request it belongs to ended? close it (abandoned)
                           otherwise re-scan and verify:
       FIXED       a flagged candidate is gone (a reformat or a move pairs up as STILL)
       DISMISSED   a flagged candidate was recorded as a false positive
       DROPPED     a flagged candidate is gone but its code is still written (the
                   engine arrived, the rule was turned off) -- not a fix
       STILL       a flagged candidate is still there
       NEW         a blocking candidate that did not exist when the cycle opened
     STILL or NEW at blocking severity earns one more block, up to
     `limits.max_verify_attempts`; then the cycle closes and whatever is left
     is reported without blocking.
  3. no cycle           -> question turn? nothing changed? stay quiet
                           else check, apply the budget, block and open a cycle

`limits.max_consecutive_blocks` bounds all of it per request, so
Detect -> Fix -> Verify cannot become a loop. Identity is the candidate key
(rule:file:code hash): a line moving because code was added above it is the
same candidate, a rewritten line is a different one.

Semantic review never runs on its own. Only when candidates of a
semantic_review rule exist and the verdict cache has nothing for them does
the block ask the main agent to hand one batch reference to the
convention-reviewer subagent. No candidates, no AI call.

A when_code_added rule (kind `unit`) has no regex to make it deterministic,
and a model asked again finds again. So once a cycle is open its reviewer
is held to what the cycle is about:
  - a unit present when the cycle opened and not asked yet is asked (a page)
  - any other unit -- changed or written by the fix, or asked before and
    now in a new context -- is asked only if its rule found a violation in
    this cycle; otherwise it is held for the next request
  - a VIOLATION blocks only in a file where that rule already found one,
    and never on a unit this cycle already judged VALID; otherwise it is
    reported, not blocked
Asking is part of judging, not a failed fix: a block that only asks units
it has not asked before spends neither max_verify_attempts nor the streak.
A question asked twice in one cycle is not free.
"""

import copy

from . import batch as batchlib
from .candidate import VIOLATION

FIXED, DISMISSED, STILL, NEW = 'fixed', 'dismissed', 'still', 'new'
DROPPED = 'dropped'        # gone from the scan, not from the code: neither fixed nor still
REPORTED = 'reported'      # a unit rule's violation found while verifying: said, not blocked
BLOCKING = ('error',)

DEFAULT_STATE = {
    'consecutive_blocks': 0,   # blocks in a row without a clean turn (loop guard)
    'blocks': 0,
    'fired_rules': [],         # rules whose findings were fixed this session (once_per_session)
    'cycle': None,             # the open verification cycle, if any
    'unresolved': [],          # candidate keys a closed cycle left unfixed
    'closed_in_continuation': False,
}


# ---------------------------------------------------------------- inputs

class Request:
    """The Stop as Claude Code described it."""

    __slots__ = ('prompt_id', 'continuing', 'question')

    def __init__(self, prompt_id=None, continuing=False, question=False):
        self.prompt_id = str(prompt_id) if prompt_id is not None else None
        self.continuing = bool(continuing)     # stop_hook_active: our own block kept it going
        self.question = bool(question)         # the agent ended its turn with a question


class ScanFailure:
    """A failed inspection is not an empty inspection."""

    __slots__ = ('message',)

    def __init__(self, message):
        self.message = str(message)


class ScanView:
    """What one scan found, in the shape decide() reads.

    hits        [(rule, [Candidate])] deterministic findings
    violations  [(rule, Candidate, verdict)] semantic candidates the cache calls VIOLATION
    pending     [(rule, Candidate, pack)] semantic candidates with no verdict yet
    capped      rule ids whose hits reached the re-scan cap
    """

    __slots__ = ('hits', 'violations', 'pending', 'lint_blocking', 'lint_notes', 'lint_raw',
                 'lint_unfinished', 'warnings', 'stacks', 'capped')

    def __init__(self, hits=(), violations=(), pending=(), lint_blocking=(), lint_notes=(),
                 lint_raw=(), lint_unfinished=(), warnings=(), stacks=(), capped=()):
        self.hits = list(hits)
        self.violations = list(violations)
        self.pending = list(pending)
        self.lint_blocking = list(lint_blocking)
        self.lint_notes = list(lint_notes)
        self.lint_raw = list(lint_raw)
        self.lint_unfinished = frozenset(lint_unfinished)
        self.warnings = list(warnings)
        self.stacks = list(stacks)
        self.capped = frozenset(capped)


class BatchSlot:
    """Where a review batch would go, decided by the shell up front -- so the
    state decide() returns can already name the batch it asks for."""

    __slots__ = ('ident', 'db', 'root', 'session', 'log')

    def __init__(self, ident, db, root, session, log):
        self.ident, self.db, self.root, self.session, self.log = ident, db, root, session, log


class Observation:
    __slots__ = ('request', 'config_error', 'scan', 'is_dismissed', 'still_written',
                 'cycle_verdicts', 'batch', 'now')

    def __init__(self, request, config_error=None, scan=None, is_dismissed=None,
                 still_written=None, cycle_verdicts=None, batch=None, now=0.0):
        self.request = request
        self.config_error = config_error       # first config error, or None
        self.scan = scan                       # ScanView | ScanFailure | None (nothing to inspect)
        self.is_dismissed = is_dismissed or (lambda _key: False)
        # still_written(key): an agent line with this key's code is still in the file
        self.still_written = still_written or (lambda _key: False)
        self.cycle_verdicts = cycle_verdicts   # what the open cycle's reviewer recorded, or None
        self.batch = batch                     # BatchSlot
        self.now = float(now)


# ---------------------------------------------------------------- outputs

class Silent:
    kind = 'silent'

    def __repr__(self):
        return 'Silent()'


class Notice:
    """`convention-guard <icon> <word> — parts` as a systemMessage."""

    kind = 'notice'

    def __init__(self, word, parts, level):
        self.word, self.parts, self.level = word, [p for p in parts if p], level

    def __repr__(self):
        return 'Notice(%r, %r, %r)' % (self.word, self.parts, self.level)


class ConfigError:
    kind = 'config_error'

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return 'ConfigError(%r)' % self.text


class Block:
    """A block. `form` is 'open' or 'verify'; `args` go to report.hook_reason
    or report.verify_reason unchanged."""

    kind = 'block'

    def __init__(self, form, args):
        self.form, self.args = form, args

    def __repr__(self):
        return 'Block(%r)' % self.form


class Decision:
    __slots__ = ('state', 'action', 'events', 'batch')

    def __init__(self, state, action, events, batch):
        self.state, self.action, self.events, self.batch = state, action, events, batch


# ---------------------------------------------------------------- the cycle record

def new_cycle(ident, prompt_id, opened, seen):
    return {
        'id': ident,
        'prompt_id': str(prompt_id) if prompt_id is not None else None,
        'attempt': 0,
        'opened': opened,          # {key: meta} flagged to the agent, still being tracked
        'seen': sorted(seen),      # every candidate key present when flagged
        'review': None,
        'violated': [],            # [rule_id, file] where a unit rule found a violation
        'asked': [],               # unit candidate keys put to a reviewer in this cycle
        'asked_reviews': [],       # their review keys
        'cleared': [],             # unit candidate keys judged VALID in this cycle
    }


def is_unit(rule):
    return rule.get('kind') == 'unit'


def entry(rule, cand):
    out = {'rule_id': rule['id'], 'title': rule['title'], 'severity': rule['severity'],
           'file': cand.file, 'line': cand_line(rule, cand), 'snippet': cand.snippet}
    if is_unit(rule):
        out['unit'] = True
    if rule.get('review'):
        out['semantic'] = True
    return out


def cand_line(rule, cand):
    """None for a file- or change-level candidate, whose detector line (1) is
    a placeholder (F4). Keys and fingerprints never use it."""
    return None if rule.get('kind') in ('absent', 'paired') else cand.line


def lint_key(fail):
    return 'lint:%s' % fail.get('key', fail['cmd'])


def lint_entry(fail):
    return {'rule_id': 'lint', 'title': fail['cmd'], 'severity': 'error',
            'file': '', 'line': 0, 'snippet': fail['output'].split('\n')[0][:120]}


class Outcome:
    def __init__(self):
        self.fixed, self.dismissed, self.still, self.new = {}, {}, {}, {}
        self.reported, self.dropped = {}, {}

    def counts(self):
        return {FIXED: len(self.fixed), DISMISSED: len(self.dismissed), DROPPED: len(self.dropped),
                STILL: len(self.still), NEW: len(self.new), REPORTED: len(self.reported)}

    def blocking(self):
        """STILL and NEW entries that are worth another block -- not one whose
        linter could not say (blocking on it again could only time out again)."""
        return {k: v for k, v in list(self.still.items()) + list(self.new.items())
                if v['severity'] in BLOCKING and not v.get('unconfirmed')}

    def unconfirmed(self):
        return [k for k, v in self.still.items() if v.get('unconfirmed')]

    def remaining(self):
        return dict(self.still, **self.new)


def classify(cycle, current, is_dismissed, unconfirmed=(), still_written=lambda _key: False):
    """current: {key: entry} for every candidate (and blocking lint failure)
    the re-scan found. is_dismissed(key) -> bool. unconfirmed: lint keys whose
    linter did not finish -- gone from `current` is not fixed for them (R17).
    still_written(key) -> bool: the code is still there, so a key gone from
    `current` left the scan, not the file -- dropped, not fixed. Not for a
    judged rule: its fix is in the context around the line (an eager load
    above the loop). A match that spans lines never matches one line's code,
    so it counts as fixed as before."""
    out = Outcome()
    for key, meta in cycle['opened'].items():
        if key in current:
            out.still[key] = current[key]
        elif key in unconfirmed:
            out.still[key] = dict(meta, unconfirmed=True)
        elif not key.startswith('lint:') and is_dismissed(key):
            out.dismissed[key] = meta
        elif not (key.startswith('lint:') or meta.get('semantic')) and still_written(key):
            out.dropped[key] = meta
        else:
            out.fixed[key] = meta
    seen = set(cycle.get('seen') or ()) | set(cycle['opened'])
    for key, meta in current.items():
        if key not in seen:
            out.new[key] = meta
    _pair_moves(out)
    for key in [k for k, m in out.new.items() if m.get('unit')]:
        out.reported[key] = out.new.pop(key)
    return out


def _squeezed(meta):
    return ''.join(str(meta.get('snippet') or '').split())


def _pair_moves(out):
    """A violation reformatted in place (same rule and file, same code once
    every space is gone) or moved whole (same code, another file) is the same
    one: a fixed and a new become one still. A different violation the fix
    wrote (`dd(1)` -> `var_dump(1)`) stays fixed plus new. Blocking is
    unchanged -- still blocks like new -- only the tuning numbers are (R23f)."""
    for fixed_key in sorted(out.fixed):
        if fixed_key.startswith('lint:'):
            continue
        meta = out.fixed[fixed_key]
        digest = fixed_key.rpartition(':')[2]
        reformat = [k for k in sorted(out.new)
                    if out.new[k]['rule_id'] == meta['rule_id']
                    and out.new[k]['file'] == meta['file']
                    and _squeezed(out.new[k]) == _squeezed(meta)]
        moved = [k for k in sorted(out.new)
                 if out.new[k]['rule_id'] == meta['rule_id'] and k.rpartition(':')[2] == digest]
        partner = (reformat or moved or [None])[0]
        if partner is not None:
            out.still[partner] = dict(out.new.pop(partner), was=fixed_key)
            del out.fixed[fixed_key]


# ---------------------------------------------------------------- the decision

def normalized(state):
    """A copy of `state` with every key present."""
    out = copy.deepcopy(state) if isinstance(state, dict) else {}
    for key, value in DEFAULT_STATE.items():
        out.setdefault(key, copy.deepcopy(value))
    return out


def belongs_to_new_request(request, cycle):
    if request.prompt_id and cycle.get('prompt_id'):
        return request.prompt_id != cycle['prompt_id']
    # without prompt ids, a Stop that is not a continuation of our own block
    # means the request ended (the user interrupted and sent something new)
    return not request.continuing


def needs_scan(state, request, cfg, config_error=None):
    """Would decide() look at a scan? Asked first, so a question turn or a
    Stop after the cycle closed does not pay for one."""
    if config_error:
        return False
    if (state or {}).get('cycle'):
        return True
    if request.continuing and (state or {}).get('closed_in_continuation'):
        return False
    if cfg['skip_if_question'] and request.question:
        return False
    return True


def decide(state, obs, cfg):
    return _Run(state, obs, cfg).run()


class _Run:
    """One decision. Works on its own copy of the state; `_save()` marks the
    points at which the state is final enough to store -- the last mark is
    what the Decision carries."""

    def __init__(self, state, obs, cfg):
        self.state = normalized(state)
        self.obs = obs
        self.cfg = cfg
        self.request = obs.request
        self.events = []
        self.batch = None
        self.saved = None

    # -- bookkeeping

    def _save(self):
        self.saved = copy.deepcopy(self.state)

    def _event(self, record):
        self.events.append(record)

    def _done(self, action):
        return Decision(self.saved, action, self.events, self.batch)

    def _quiet(self, rule):
        # a unit rule judges all new code; the verdict cache, not the session,
        # is what keeps it from asking about the same code twice
        return (self.cfg['once_per_session'] and not is_unit(rule)
                and rule['id'] in (self.state.get('fired_rules') or []))

    # -- the order of things

    def run(self):
        if self.obs.config_error:
            return self._done(ConfigError(self.obs.config_error))
        state, request = self.state, self.request
        cycle = state.get('cycle')
        abandon = bool(cycle) and belongs_to_new_request(request, cycle)
        if not request.continuing or abandon:
            # the cap guards one request's loop; a new request starts its own (R4)
            state['consecutive_blocks'] = 0
        scan = self.obs.scan
        if abandon:
            if isinstance(scan, ScanFailure):
                return self._done(ConfigError(scan.message))
            current = self._current(scan)
            self._close(cycle, self._classify(cycle, scan, current), abandoned=True,
                        current=current)
            cycle = None

        if not request.continuing:
            state['closed_in_continuation'] = False

        if cycle:
            if isinstance(scan, ScanFailure):
                return self._done(ConfigError(scan.message))
            return self._verify(cycle, scan)

        if request.continuing and state.get('closed_in_continuation'):
            # this request already had its cycle; another hook kept the agent going
            self._save()
            return self._done(Silent())
        if self.cfg['skip_if_question'] and request.question:
            self._save()
            return self._done(Silent())

        if scan is None:
            state['consecutive_blocks'] = 0
            self._save()
            return self._done(Silent())
        if isinstance(scan, ScanFailure):
            return self._done(ConfigError(scan.message))
        return self._open(scan)

    # -- what is there

    def _findings(self, scan, respect_quiet=True):
        """[(rule, [Candidate])]: deterministic hits plus cached semantic VIOLATIONs."""
        quiet = self._quiet if respect_quiet else (lambda _rule: False)
        hits = [(rule, cands) for rule, cands in scan.hits if not quiet(rule)]
        grouped = {}
        for rule, cand, _verdict in scan.violations:
            if not quiet(rule):
                grouped.setdefault(rule['id'], (rule, []))[1].append(cand)
        return hits + list(grouped.values())

    def _current(self, scan):
        """{key: entry} for every finding and blocking lint failure right now.

        once_per_session must not reach here. It decides what is worth *saying*
        again; the cycle needs what is actually *there*, or a rule settled earlier
        in the session could be re-introduced by a fix and be read as gone.
        """
        current = {}
        if scan is None:
            return current
        for rule, cands in self._findings(scan, respect_quiet=False):
            for cand in cands:
                current[cand.key] = entry(rule, cand)
        for fail in scan.lint_blocking:
            current[lint_key(fail)] = lint_entry(fail)
        return current

    def _classify(self, cycle, scan, current=None):
        review = cycle.get('review') or {}
        if review.get('batch'):
            # a candidate the reviewer called a VIOLATION is one the agent was told
            # to fix: from here on it is tracked like any other flagged finding
            answered = [(review['items'][k], v) for k, v in (self.obs.cycle_verdicts or {}).items()
                        if k in review['items']]
            # pages first: a violation they find widens what a re-ask may block on
            answered.sort(key=lambda pair: not pair[0].get('page'))
            for item, verdict in answered:
                if verdict.get('verdict') != VIOLATION:
                    if item.get('unit'):
                        _add(cycle, 'cleared', [item['key']])
                    continue
                if item.get('unit') and not item.get('page') and (
                        (item['rule_id'], item['file']) not in _violated(cycle)
                        or item['key'] in (cycle.get('cleared') or ())):
                    continue    # found while verifying: reported (classify)
                cycle['opened'].setdefault(item['key'], dict(item))
                if item.get('unit'):
                    _mark_violated(cycle, item)
        if current is None:
            current = self._current(scan)
        unfinished = scan.lint_unfinished if scan is not None else ()
        unconfirmed = {lint_key({'key': key, 'cmd': ''}) for key in unfinished}
        out = classify(cycle, current, self.obs.is_dismissed, unconfirmed, self.obs.still_written)
        # the same unit, VALID earlier in this cycle and VIOLATION now: the
        # model changed its mind, not the code -- said, not blocked
        cleared = set(cycle.get('cleared') or ())
        for key, meta in current.items():
            if meta.get('unit') and key in cleared and key not in out.remaining():
                out.reported[key] = meta
        return out

    @staticmethod
    def _hidden(outcome, current):
        """Blocking findings still there that the cycle never showed -- past the
        display budget. Not a failed fix, but not a pass either (R3)."""
        shown = set(outcome.remaining()) | set(outcome.reported)
        return sorted(k for k, m in current.items()
                      if k not in shown and not k.startswith('lint:')
                      and m['severity'] in BLOCKING)

    def _pending_review(self, cycle, scan):
        """(skipped, needs_review, held): semantic candidates without a verdict,
        split by whether the reviewer was already asked about them in this cycle
        -- and, for unit rules, whether the cycle is about them at all."""
        if scan is None or not scan.pending:
            return [], [], []
        review = cycle.get('review') or {}
        asked = set(review.get('items') or {})
        ran = bool(review.get('batch')) and self.obs.cycle_verdicts is not None
        violated_rules = {rule_id for rule_id, _ in _violated(cycle)}
        skipped, needs, held = [], [], []
        for item in scan.pending:
            rule, cand = item[0], item[1]
            if cand.review_key in asked and not ran:
                skipped.append(item)
            elif is_unit(rule) and not _page(cycle, cand) and rule['id'] not in violated_rules:
                held.append(item)
            else:
                needs.append(item)
        return skipped, needs, held

    # -- closing and asking

    def _log_outcome(self, cycle, outcome, abandoned=False):
        for label, items in ((FIXED, outcome.fixed), (DISMISSED, outcome.dismissed),
                             (DROPPED, outcome.dropped),
                             (STILL, outcome.still), (NEW, outcome.new),
                             (REPORTED, outcome.reported)):
            for key, meta in items.items():
                self._event({'event': 'verify', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
                             'outcome': label, 'key': key, 'rule_id': meta['rule_id'],
                             'severity': meta['severity'], 'file': meta['file'],
                             'abandoned': abandoned})

    def _close(self, cycle, outcome, abandoned=False, unreviewed=(), current=None, held=()):
        self._log_outcome(cycle, outcome, abandoned)
        for reason, items in (('attempts', unreviewed), ('verify_scope', held)):
            for _rule, cand, _pack in items:
                self._event({'event': 'review_skipped', 'cycle': cycle['id'],
                             'rule_id': cand.rule_id, 'key': cand.key, 'file': cand.file,
                             'reason': reason})
        if abandoned:
            self._event(dict({'event': 'abandoned', 'cycle': cycle['id']}, **outcome.counts()))
        state = self.state
        current = current or {}
        settled = {m['rule_id'] for m in outcome.fixed.values()}
        unsettled = {m['rule_id'] for m in outcome.remaining().values()}
        unsettled |= {m['rule_id'] for m in outcome.dismissed.values()}
        # a rule with anything left -- shown or not -- is not settled (R3)
        unsettled |= {m['rule_id'] for m in current.values()}
        state['fired_rules'] = sorted(set(state.get('fired_rules') or [])
                                      | (settled - unsettled - {'lint'}))
        # what was never shown comes back next request, marked as raised before
        state['unresolved'] = sorted(set(k for k in outcome.remaining()
                                         if not k.startswith('lint:'))
                                     | set(self._hidden(outcome, current)))
        state['cycle'] = None
        if not outcome.blocking():
            state['consecutive_blocks'] = 0
        if self.request.continuing and not abandoned:
            state['closed_in_continuation'] = True
        self._save()

    def _request_review(self, cycle, pending, label):
        """Plan a batch and remember it on the cycle. Returns the report section input."""
        slot = self.obs.batch
        if slot is None:
            return None
        ref, body, items, deferred = batchlib.plan_batch(
            slot.root, slot.session, pending, self.cfg, label=label, db=slot.db, log=slot.log,
            ident=slot.ident, now=self.obs.now)
        if not ref:
            return None
        by_key = {}
        for rule, cand, _ in pending:       # the first candidate, as the batch item (R7)
            by_key.setdefault(cand.review_key, (rule, cand))
        cycle['review'] = {'batch': ref, 'items': {
            item['review_key']: dict(entry(*by_key[item['review_key']]), key=item['key'],
                                     page=_page(cycle, by_key[item['review_key']][1]))
            for item in items}}
        units = [item for item in items if is_unit(by_key[item['review_key']][0])]
        _add(cycle, 'asked', [item['key'] for item in units])
        _add(cycle, 'asked_reviews', [item['review_key'] for item in units])
        self.batch = (ref, body)
        self._event({'event': 'review_requested', 'cycle': cycle['id'], 'batch': ref,
                     'rules': sorted({i['rule_id'] for i in items}), 'candidates': len(items),
                     'deferred': len(deferred)})
        return {'batch': ref, 'items': items, 'deferred': len(deferred)}

    # -- verify an open cycle

    def _verify(self, cycle, scan):
        current = self._current(scan)
        outcome = self._classify(cycle, scan, current)
        # a rule cut at the re-scan cap brings older candidates into view once
        # some are fixed: they were there all along, not new (C6)
        capped = scan.capped if scan is not None else frozenset()
        for key in [k for k, m in outcome.new.items() if m['rule_id'] in capped]:
            del outcome.new[key]
        hidden = self._hidden(outcome, current)
        skipped, needs, held = self._pending_review(cycle, scan)
        warnings = scan.warnings if scan is not None else []
        cfg = self.cfg
        streak = int(self.state.get('consecutive_blocks', 0))
        wants = bool(outcome.blocking() or skipped or needs)
        # Pagination of an already-running semantic review is not a failed fix
        # attempt. Let deferred, previously-unasked candidates consume the loop
        # guard, not max_verify_attempts.
        review_page = bool(needs) and not outcome.blocking() and not skipped
        # asking about units is judging, not fixing: each is asked once, so it
        # needs neither guard (see the module docstring)
        asked_before = set(cycle.get('asked_reviews') or ())
        free = review_page and all(is_unit(rule) and cand.review_key not in asked_before
                                   for rule, cand, _ in needs)
        attempts_left = (cycle['attempt'] < cfg.limit('max_verify_attempts') or review_page)
        again = (wants and not cfg.report_only and attempts_left
                 and (free or streak < cfg.limit('max_consecutive_blocks')))
        if not again:
            self._close(cycle, outcome, unreviewed=skipped + needs, current=current, held=held)
            counts = outcome.counts()
            settled = ['고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'],
                       dropped_part(counts)]
            unshown = '미표시 %d' % len(hidden) if hidden else ''
            warning = _warning_part(warnings)
            unsure = outcome.unconfirmed()
            if unsure:          # a linter that timed out has not confirmed anything (R17)
                return self._done(Notice('재검증 종료', [
                    *settled,
                    '남음 %d' % (counts['still'] - len(unsure)), '새로 생김 %d' % counts['new'],
                    '린터 미확인 %d' % len(unsure), unshown, warning, '이후 기록만'], 'warn'))
            if not outcome.remaining() and not (skipped or needs or held or outcome.reported):
                if hidden:      # what was shown is fixed; the rest is not a pass (R3)
                    return self._done(Notice('재검증 종료', [
                        *settled, unshown,
                        warning, '다음 요청에서 다시 알림'], 'warn'))
                return self._done(Notice('재검증 통과', [*settled, warning], 'pass'))
            return self._done(Notice('재검증 종료', [
                *settled,
                '남음 %d' % counts['still'], '새로 생김 %d' % counts['new'], unshown,
                '판정 대기 %d' % len(skipped + needs) if skipped or needs else '',
                '보고만 %d' % counts[REPORTED] if outcome.reported else '',
                '재검증 범위 밖 판정 보류 %d' % len(held) if held else '',
                warning, '이후 기록만'], 'warn'))

        self._log_outcome(cycle, outcome)
        for _rule, cand, _pack in skipped:
            self._event({'event': 'review_skipped', 'cycle': cycle['id'], 'rule_id': cand.rule_id,
                         'key': cand.key, 'file': cand.file, 'reason': 'not_run'})
        if not free:
            cycle['attempt'] += 1
        last_chance = (not review_page
                       and cycle['attempt'] >= cfg.limit('max_verify_attempts'))
        cycle['opened'] = outcome.remaining()
        cycle['seen'] = sorted(set(cycle.get('seen') or ()) | set(current))
        cycle['review'] = None
        review = self._request_review(cycle, skipped + needs, 'verify') \
            if (skipped or needs) else None
        self.state['cycle'] = cycle
        self.state['consecutive_blocks'] = streak + (0 if free else 1)
        self.state['blocks'] = int(self.state.get('blocks', 0)) + 1
        self._save()
        self._event({'event': 'block', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
                     'kind': 'verify', 'keys': sorted(outcome.blocking()),
                     'review': bool(review)})
        return self._done(Block('verify', {'outcome': outcome, 'last_chance': last_chance,
                                           'review': review, 'skipped': bool(skipped),
                                           'warnings': warnings, 'held': len(held)}))

    # -- open a cycle

    def _open(self, scan):
        cfg, state = self.cfg, self.state
        scan_warnings = scan.warnings
        shown_cap = cfg.limit('max_locations_per_rule')
        unresolved = set(state.get('unresolved') or [])

        lint_cmds = {f['cmd'] for f in scan.lint_blocking}
        lint_count = len({lint_key(f) for f in scan.lint_blocking})
        for fail in scan.lint_raw:
            self._event({'event': 'lint', 'stack': fail.get('stack'), 'cmd': fail['cmd'],
                         'anchored': fail['anchored'],
                         'findings': len(fail.get('locations') or []),
                         'blocking': fail['cmd'] in lint_cmds})

        hits = self._findings(scan)

        def is_repeat(cands):
            return any(c.key in unresolved for c in cands)

        hits.sort(key=lambda h: (_rank(h[0]), not is_repeat(h[1]), -len(h[1])))
        all_errors = [(r, c) for r, c in hits if r['severity'] == 'error']
        all_warns = [(r, c) for r, c in hits if r['severity'] == 'warn']
        errors = [(r, c[:shown_cap]) for r, c in all_errors][:cfg.limit('max_error_rules')]
        warns = [(r, c[:shown_cap]) for r, c in all_warns][:cfg.limit('max_warn_rules')]
        # what the budget left out is counted in the block, never just dropped (R3)
        more = {r['id']: len(c) - shown_cap for r, c in all_errors + all_warns
                if len(c) > shown_cap}
        hidden_rules = (len(all_errors) - len(errors), len(all_warns) - len(warns))
        infos = [(r, c) for r, c in hits if r['severity'] == 'info']
        repeats = {r['id'] for r, c in errors + warns if is_repeat(c)}
        all_pending = list(scan.pending)
        # a rule this session already settled is not worth an AI call again, but
        # its candidates still count as "seen" so a later re-scan cannot call them new
        pending = [item for item in all_pending if not self._quiet(item[0])]

        streak = int(state.get('consecutive_blocks', 0))
        capped = streak >= cfg.limit('max_consecutive_blocks')
        has_blocking = bool(scan.lint_blocking or errors or pending)
        blocking = has_blocking and not cfg.report_only and not capped
        shown = (errors + warns) if blocking else []
        shown_keys = {c.key for _, cands in shown for c in cands}

        for rule, cands in hits:
            for cand in cands:
                self._event({'event': 'candidate', 'rule_id': rule['id'], 'key': cand.key,
                             'file': cand.file, 'line': cand.line, 'severity': rule['severity'],
                             'source': rule['source'], 'base_severity': rule.get('base_severity'),
                             'stacks': scan.stacks, 'shown': cand.key in shown_keys,
                             'repeat': cand.key in unresolved, 'mode': cfg['mode'],
                             'semantic': bool(rule['review'])})

        if not blocking:
            # the streak only resets on a turn with nothing to block: a turn the cap
            # held back is still part of the runaway loop the cap exists for
            if not has_blocking or cfg.report_only:
                state['consecutive_blocks'] = 0
            self._save()
            why = 'mode=report' if cfg.report_only else 'cap'
            for _rule, cand, _pack in pending:
                self._event({'event': 'review_skipped', 'rule_id': cand.rule_id, 'key': cand.key,
                             'file': cand.file, 'reason': why})
            if has_blocking:
                held = '연속 차단 %d회 상한' % streak if capped else 'mode=report'
                return self._done(Notice('기록', [
                    '린터 실패 %d' % lint_count if lint_count else '',
                    'error %d' % len(errors) if errors else '',
                    '판정 대기 %d' % len(pending) if pending else '',
                    _warning_part(scan_warnings), '차단 안 함: %s' % held],
                    'error' if errors or lint_count else 'warn'))
            parts = ['warn %d (%s)' % (len(warns), ', '.join(r['id'] for r, _ in warns))
                     if warns else '',
                     'info %d' % len(infos) if infos else '',
                     '린터 참고 %d' % len(scan.lint_notes) if scan.lint_notes else '',
                     _warning_part(scan_warnings)]
            if any(parts):
                only_info = infos and not (warns or scan.lint_notes or scan_warnings)
                return self._done(Notice('기록', parts, 'info' if only_info else 'warn'))
            return self._done(Silent())

        opened = {c.key: entry(r, c) for r, cands in shown for c in cands}
        for fail in scan.lint_blocking:
            opened[lint_key(fail)] = lint_entry(fail)
        seen = set(self._current(scan)) | {cand.key for _, cand, _ in all_pending}
        cycle = new_cycle('c%d' % int(self.obs.now * 1000), self.request.prompt_id, opened, seen)
        for meta in opened.values():
            if meta.get('unit'):
                _mark_violated(cycle, meta)
        review = self._request_review(cycle, pending, 'open') if pending else None
        if not (opened or review):
            self._save()
            return self._done(Silent())
        state['cycle'] = cycle
        state['unresolved'] = []
        state['consecutive_blocks'] = streak + 1
        state['blocks'] = int(state.get('blocks', 0)) + 1
        self._save()
        self._event({'event': 'block', 'cycle': cycle['id'], 'attempt': 0, 'kind': 'open',
                     'keys': sorted(opened), 'review': bool(review)})
        return self._done(Block('open', {
            'lint_failures': scan.lint_blocking, 'lint_notes': scan.lint_notes,
            'errors': errors, 'warns': warns, 'repeats': repeats, 'review': review,
            'warnings': scan_warnings, 'lint_count': lint_count, 'info_count': len(infos),
            'more': more, 'hidden_rules': hidden_rules}))


def _violated(cycle):
    return {(rule_id, path) for rule_id, path in cycle.get('violated') or ()}


def _page(cycle, cand):
    """A unit there when the cycle opened that no reviewer was asked about yet."""
    return cand.key in (cycle.get('seen') or ()) and cand.key not in (cycle.get('asked') or ())


def _add(cycle, field, keys):
    cycle[field] = sorted(set(cycle.get(field) or ()) | set(keys))


def _mark_violated(cycle, meta):
    pairs = _violated(cycle) | {(meta['rule_id'], meta['file'])}
    cycle['violated'] = sorted([rule_id, path] for rule_id, path in pairs)


def dropped_part(counts):
    """Said only when it happened: a count of findings the scan stopped
    reporting while their code stayed -- not to be read as fixes."""
    return '검사에서 빠짐 %d' % counts[DROPPED] if counts[DROPPED] else ''


def _warning_part(warnings):
    return '검사 경고 %d: %s' % (len(warnings), warnings[0]) if warnings else ''


def _rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)
