"""Hook policy: what happens on PostToolUse and Stop.

scripts/collect.py and scripts/check.py only parse stdin and print what these
functions return. Checking is the pipeline's job; the verification cycle
(cycle.py) is the state machine; semantic.py decides what needs a reviewer;
this module decides *when* each runs and *what to do* with the result --
block, report, or stay quiet.

Stop, in order:
  1. config broken      -> say so and skip (never check with unchosen defaults)
  2. a cycle is open    -> the request it belongs to ended? close it (abandoned)
                           otherwise re-scan and verify
  3. no cycle           -> question turn? nothing changed? stay quiet
                           else check, apply the budget, block and open a cycle

Semantic review never runs on its own. Only when candidates of a
semantic_review rule exist and the verdict cache has nothing for them does
the block ask the main agent to hand one batch path to the convention-reviewer
subagent. No candidates, no AI call.
"""

import os

from . import (autofix, config as configlib, cycle as cyclelib, dismiss as dismisslib, gitdiff,
               log, pipeline, report, semantic, state as statelib)
from .candidate import VIOLATION, fingerprint, parse_key
from .paths import git_toplevel, hook_project_dir
from .scope import ChangeScope, ScopeError

EDIT_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
WATCHED_TOOLS = EDIT_TOOLS | {'Bash'}

# Locations per rule the re-scan collects. Far above what a block shows, so a
# flagged candidate is not read as fixed merely because others crowd it out.
VERIFY_CAP = 50

# Seconds the whole lint phase may take inside the Stop hook. hooks.json gives
# check.py 150s; `linters.timeout` is per linter and they run one after another,
# so a laravel repo (php-cs-fixer + pint + phpstan) can ask for 270s. Going over
# gets the hook killed, and a killed hook prints nothing -- which reads exactly
# like a clean check. Leave room for the re-scan and the semantic batch.
LINT_BUDGET = 110


# ---------------------------------------------------------------- PostToolUse

def _tool_use_key(payload):
    ident = payload.get('tool_use_id')
    if ident:
        return ident
    tool_input = payload.get('tool_input')
    command = tool_input.get('command', '') if isinstance(tool_input, dict) else ''
    return 'command-%s' % fingerprint(command)


def on_pre_tool_use(payload):
    """Snapshot pre-existing dirty files before Bash so they are not claimed."""
    if not isinstance(payload, dict) or payload.get('tool_name') != 'Bash':
        return None
    root = git_toplevel(hook_project_dir(payload))
    session = payload.get('session_id')
    head = gitdiff.current_head(root)
    statelib.record_base(session, root, head)
    paths = gitdiff.changed_paths(root, head)
    fingerprints = {rel: gitdiff.file_fingerprint(root, rel) for rel in paths}
    statelib.save_bash_snapshot(session, _tool_use_key(payload), root, fingerprints)
    return None


def _candidate_paths(tool_input):
    paths = []
    if not isinstance(tool_input, dict):
        return paths
    for key in ('file_path', 'path', 'notebook_path', 'filePath'):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for edit in tool_input.get('edits') or []:
        if isinstance(edit, dict) and isinstance(edit.get('file_path'), str):
            paths.append(edit['file_path'])
    return paths


def on_post_tool_use(payload):
    """Record which files the agent touched. Injects nothing, prints nothing."""
    if not isinstance(payload, dict) or payload.get('tool_name') not in WATCHED_TOOLS:
        return None
    root = git_toplevel(hook_project_dir(payload))
    session = payload.get('session_id')
    statelib.record_base(session, root, gitdiff.current_head(root))
    if payload.get('tool_name') == 'Bash':
        tool_key = _tool_use_key(payload)
        before = statelib.read_bash_snapshot(session, tool_key, root)
        if before is None:
            return None
        base_ref = statelib.read_base(session, root)
        changed = gitdiff.changed_paths(root, base_ref)
        found = [rel for rel in changed
                 if before.get(rel) != gitdiff.file_fingerprint(root, rel)]
        statelib.append_touched(session, found)
        # A missing tool_use_id cannot distinguish identical parallel Bash
        # calls. Keep their shared snapshot until GC so every Post can consume it.
        if payload.get('tool_use_id'):
            statelib.delete_bash_snapshot(session, tool_key)
        return None
    found = []
    for raw in _candidate_paths(payload.get('tool_input')):
        absolute = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(root, raw))
        try:
            rel = os.path.relpath(absolute, root)
        except ValueError:
            continue
        if not rel.startswith('..'):
            found.append(rel.replace(os.sep, '/'))
    statelib.append_touched(session, found)
    return None


# ---------------------------------------------------------------- Stop output

def block(reason, system_message=None):
    out = {'decision': 'block', 'reason': reason}
    if system_message:
        out['systemMessage'] = system_message
    return out


def notice(system_message=None):
    return {'systemMessage': system_message} if system_message else None


def ends_with_question(message):
    text = (message or '').strip()
    return bool(text) and text.rstrip('`*_)"\'」』').endswith(('?', '？'))


def config_error(text):
    return notice('convention-guard: 설정 오류로 검사를 건너뜁니다 — %s' % text)


# ---------------------------------------------------------------- Stop

class StopContext:
    def __init__(self, payload):
        self.payload = payload
        self.root = git_toplevel(hook_project_dir(payload))
        self.session = payload.get('session_id')
        prompt_id = payload.get('prompt_id') or payload.get('turn_number')
        self.prompt_id = str(prompt_id) if prompt_id is not None else None
        self.continuing = bool(payload.get('stop_hook_active'))
        self.cfg = configlib.load(self.root)
        self.state = statelib.load(self.session)
        self.autofixed = []

    @property
    def semantic_on(self):
        return bool(self.cfg['semantic_review']['enabled'])

    def save(self):
        statelib.save(self.session, self.state)

    def event(self, record):
        log.event(dict(record, session=self.session, repo=self.root))


class Scan:
    """One re-scan: the pipeline result plus what the verdict cache says about
    its semantic candidates."""

    def __init__(self, result, triage):
        self.result, self.triage = result, triage

    @property
    def errors(self):
        return self.result.errors


class ScanFailure:
    """A failed inspection is not an empty inspection."""

    def __init__(self, message):
        self.errors = [message]


def _scan_warnings(scan):
    if scan is None or not hasattr(scan, 'result'):
        return []
    warnings = [text for level, text in scan.result.notes if level == 'warn']
    warnings.sort(key=lambda text: (0 if '검사되지 않았습니다' in text else 1, text))
    return warnings


def _warning_suffix(warnings):
    return ' / 검사 경고: %s' % warnings[0] if warnings else ''


def on_stop(payload):
    if not isinstance(payload, dict):
        return None
    ctx = StopContext(payload)
    return _with_autofix_note(ctx, _stop(ctx))


def _with_autofix_note(ctx, out):
    """Files auto-fix rewrote changed under the agent; it must hear about it."""
    if not ctx.autofixed:
        return out
    files = sorted({fix.file for fix in ctx.autofixed})
    note = ('convention-guard: 자동 수정 %d건 (%s) — 해당 파일은 편집 전에 다시 읽으세요'
            % (len(ctx.autofixed), ', '.join(files)))
    if out and out.get('decision') == 'block':
        out['reason'] = report.autofix_section(ctx.autofixed) + out['reason']
        out['systemMessage'] = note
        return out
    return notice(note if not out else '%s / %s' % (out.get('systemMessage', ''), note))


def _stop(ctx):
    payload = ctx.payload
    errors = [text for level, text in ctx.cfg.notes if level == 'error']
    if errors:
        return config_error(errors[0])

    state = ctx.state
    cycle = state.get('cycle')
    scan, scanned = None, False
    if cycle and _belongs_to_new_request(ctx, cycle):
        scan, scanned = _scan(ctx), True
        if scan is not None and scan.errors:
            return config_error(scan.errors[0])
        _close(ctx, cycle, _classify(ctx, cycle, scan), abandoned=True)
        cycle = None

    if not ctx.continuing:
        state['closed_in_continuation'] = False

    if cycle:
        scan = _scan(ctx)
        if scan is not None and scan.errors:
            return config_error(scan.errors[0])
        return _verify(ctx, cycle, scan)

    if ctx.continuing and state.get('closed_in_continuation'):
        # this request already had its cycle; another hook kept the agent going
        ctx.save()
        return None
    if ctx.cfg['skip_if_question'] and ends_with_question(payload.get('last_assistant_message')):
        ctx.save()
        return None

    if not scanned:
        scan = _scan(ctx)
    if scan is None:
        ctx.state['consecutive_blocks'] = 0
        ctx.save()
        return None
    if scan.errors:
        return config_error(scan.errors[0])
    return _open(ctx, scan)


def _belongs_to_new_request(ctx, cycle):
    if ctx.prompt_id and cycle.get('prompt_id'):
        return ctx.prompt_id != cycle['prompt_id']
    # without prompt ids, a Stop that is not a continuation of our own block
    # means the request ended (the user interrupted and sent something new)
    return not ctx.continuing


def _scan(ctx):
    """Everything touched this session, or None when there is nothing to
    inspect (no edits, not a repo, all reverted)."""
    touched = statelib.read_touched(ctx.session)
    if not touched:
        return None
    configured = ctx.cfg['scope']['base_ref']
    configured_ref = gitdiff.resolve_base_ref(ctx.root, configured)
    if configured and configured != 'auto' and not configured_ref:
        return ScanFailure('base ref 를 찾을 수 없습니다: %s' % configured)
    session_ref = statelib.read_base(ctx.session, ctx.root)
    current_head = gitdiff.current_head(ctx.root)
    if configured_ref == current_head:
        configured_ref = None
    if session_ref == current_head:
        session_ref = None       # HEAD diff already covers the same commit
    base_ref = list(dict.fromkeys(ref for ref in (configured_ref, session_ref) if ref))
    try:
        scope = ChangeScope.from_touched(ctx.root, touched, base_ref or None)
    except ScopeError as exc:
        return ScanFailure(str(exc))
    if not scope:
        return None
    result = pipeline.run(scope, ctx.cfg, cap=VERIFY_CAP, lint_budget=LINT_BUDGET)
    if ctx.cfg['mode'] == 'auto-fix' and not result.errors and not ctx.autofixed:
        applied = autofix.apply(ctx.root, autofix.plan(ctx.root, result.hits))
        if applied:
            for fix in applied:
                ctx.event(dict(fix.to_dict(), event='autofix'))
            ctx.autofixed = applied
            # the scope caches file text and diffs; the files just changed
            scope = ChangeScope.from_touched(scope.root, touched, scope.base_ref)
            result = pipeline.run(scope, ctx.cfg, cap=VERIFY_CAP, lint_budget=LINT_BUDGET)
    triage = None
    if ctx.semantic_on and not result.errors and result.semantic_hits:
        triage = semantic.triage(result, ctx.cfg)
    return Scan(result, triage)


def _quiet(ctx, rule):
    return ctx.cfg['once_per_session'] and rule['id'] in (ctx.state.get('fired_rules') or [])


def _findings(ctx, scan, respect_quiet=True):
    """[(rule, [Candidate])]: deterministic hits plus cached semantic VIOLATIONs."""
    quiet = _quiet if respect_quiet else (lambda _ctx, _rule: False)
    hits = [(rule, cands) for rule, cands in scan.result.hits if not quiet(ctx, rule)]
    if scan.triage:
        grouped = {}
        for rule, cand, _verdict in scan.triage.violations:
            if not quiet(ctx, rule):
                grouped.setdefault(rule['id'], (rule, []))[1].append(cand)
        hits += list(grouped.values())
    return hits


def _current(ctx, scan):
    """{key: entry} for every finding and blocking lint failure right now.

    once_per_session must not reach here. It decides what is worth *saying*
    again; the cycle needs what is actually *there*, or a rule settled earlier
    in the session could be re-introduced by a fix and be read as gone.
    """
    current = {}
    if scan is None:
        return current
    for rule, cands in _findings(ctx, scan, respect_quiet=False):
        for cand in cands:
            current[cand.key] = cyclelib.entry(rule, cand)
    for fail in scan.result.lint_blocking:
        current[cyclelib.lint_key(fail)] = cyclelib.lint_entry(fail)
    return current


def _dismissed_predicate(root):
    dismissals = dismisslib.load(root)

    def is_dismissed(key):
        try:
            rule_id, relpath, digest = parse_key(key)
        except ValueError:
            return False
        return dismissals.is_dismissed(rule_id, relpath, digest)
    return is_dismissed


def _classify(ctx, cycle, scan):
    review = cycle.get('review') or {}
    if review.get('batch'):
        # a candidate the reviewer called a VIOLATION is one the agent was told
        # to fix: from here on it is tracked like any other flagged finding
        recorded = semantic.read_verdicts(review['batch']) or {}
        for review_key, verdict in recorded.items():
            item = review['items'].get(review_key)
            if item and verdict.get('verdict') == VIOLATION:
                cycle['opened'].setdefault(item['key'], dict(item))
    return cyclelib.classify(cycle, _current(ctx, scan), _dismissed_predicate(ctx.root))


def _pending_review(ctx, cycle, scan):
    """(skipped, needs_review): semantic candidates without a verdict, split by
    whether the reviewer was already asked about them in this cycle."""
    if scan is None or not scan.triage:
        return [], []
    review = cycle.get('review') or {}
    asked = set(review.get('items') or {})
    ran = bool(review.get('batch')) and semantic.read_verdicts(review['batch']) is not None
    skipped, needs = [], []
    for entry in scan.triage.pending:
        cand = entry[1]
        (skipped if cand.review_key in asked and not ran else needs).append(entry)
    return skipped, needs


def _log_outcome(ctx, cycle, outcome, abandoned=False):
    for label, items in ((cyclelib.FIXED, outcome.fixed), (cyclelib.DISMISSED, outcome.dismissed),
                         (cyclelib.STILL, outcome.still), (cyclelib.NEW, outcome.new)):
        for key, meta in items.items():
            ctx.event({'event': 'verify', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
                       'outcome': label, 'key': key, 'rule_id': meta['rule_id'],
                       'severity': meta['severity'], 'file': meta['file'],
                       'abandoned': abandoned})


def _close(ctx, cycle, outcome, abandoned=False, unreviewed=()):
    _log_outcome(ctx, cycle, outcome, abandoned)
    for _rule, cand, _pack in unreviewed:
        ctx.event({'event': 'review_skipped', 'cycle': cycle['id'], 'rule_id': cand.rule_id,
                   'key': cand.key, 'file': cand.file, 'reason': 'attempts'})
    if abandoned:
        ctx.event(dict({'event': 'abandoned', 'cycle': cycle['id']}, **outcome.counts()))
    state = ctx.state
    settled = {m['rule_id'] for m in outcome.fixed.values()}
    unsettled = {m['rule_id'] for m in outcome.remaining().values()}
    unsettled |= {m['rule_id'] for m in outcome.dismissed.values()}
    state['fired_rules'] = sorted(set(state.get('fired_rules') or [])
                                  | (settled - unsettled - {'lint'}))
    state['unresolved'] = sorted(k for k in outcome.remaining() if not k.startswith('lint:'))
    state['cycle'] = None
    if not outcome.blocking():
        state['consecutive_blocks'] = 0
    if ctx.continuing and not abandoned:
        state['closed_in_continuation'] = True
    ctx.save()


def _request_review(ctx, cycle, pending, label):
    """Write a batch and remember it on the cycle. Returns the report section input."""
    path, items, deferred = semantic.build_batch(ctx.root, ctx.session, pending, ctx.cfg,
                                                 label=label)
    if not path:
        return None
    by_key = {cand.review_key: (rule, cand) for rule, cand, _ in pending}
    cycle['review'] = {'batch': path, 'items': {
        item['review_key']: dict(cyclelib.entry(*by_key[item['review_key']]),
                                 key=item['key'])
        for item in items}}
    ctx.event({'event': 'review_requested', 'cycle': cycle['id'], 'batch': path,
               'rules': sorted({i['rule_id'] for i in items}), 'candidates': len(items),
               'deferred': len(deferred)})
    return {'batch': path, 'items': items, 'deferred': len(deferred)}


def _verify(ctx, cycle, scan):
    outcome = _classify(ctx, cycle, scan)
    skipped, needs = _pending_review(ctx, cycle, scan)
    warnings = _scan_warnings(scan)
    cfg = ctx.cfg
    streak = int(ctx.state.get('consecutive_blocks', 0))
    wants = bool(outcome.blocking() or skipped or needs)
    # Pagination of an already-running semantic review is not a failed fix
    # attempt. Let deferred, previously-unasked candidates consume the loop
    # guard, not max_verify_attempts.
    review_page = bool(needs) and not outcome.blocking() and not skipped
    attempts_left = (cycle['attempt'] < cfg.limit('max_verify_attempts') or review_page)
    again = (wants and not cfg.report_only
             and attempts_left
             and streak < cfg.limit('max_consecutive_blocks'))
    if not again:
        _close(ctx, cycle, outcome, unreviewed=skipped + needs)
        if not outcome.remaining() and not (skipped or needs):
            return notice('convention-guard: 검사 경고 — %s' % warnings[0]) if warnings else None
        counts = outcome.counts()
        return notice('convention-guard: 재검증 — 고쳐짐 %d / 기각 %d / 남음 %d / 새로 생김 %d%s. '
                      '더 차단하지 않고 기록만 남깁니다.%s'
                      % (counts['fixed'], counts['dismissed'], counts['still'], counts['new'],
                         ' / 판정 못 한 후보 %d' % len(skipped + needs) if skipped or needs
                         else '',
                         ' / 검사 경고: %s' % warnings[0] if warnings else ''))

    _log_outcome(ctx, cycle, outcome)
    for _rule, cand, _pack in skipped:
        ctx.event({'event': 'review_skipped', 'cycle': cycle['id'], 'rule_id': cand.rule_id,
                   'key': cand.key, 'file': cand.file, 'reason': 'not_run'})
    cycle['attempt'] += 1
    last_chance = (not review_page
                   and cycle['attempt'] >= cfg.limit('max_verify_attempts'))
    cycle['opened'] = outcome.remaining()
    cycle['seen'] = sorted(set(cycle.get('seen') or ()) | set(_current(ctx, scan)))
    cycle['review'] = None
    review = _request_review(ctx, cycle, skipped + needs, 'verify') if (skipped or needs) \
        else None
    ctx.state['cycle'] = cycle
    ctx.state['consecutive_blocks'] = streak + 1
    ctx.state['blocks'] = int(ctx.state.get('blocks', 0)) + 1
    ctx.save()
    ctx.event({'event': 'block', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
               'kind': 'verify', 'keys': sorted(outcome.blocking()),
               'review': bool(review)})
    counts = outcome.counts()
    return block(report.verify_reason(outcome, last_chance, review, skipped=bool(skipped)),
                 'convention-guard: 재검증 — 남음 %d / 새로 생김 %d%s'
                 % (counts['still'], counts['new'],
                    (' / 심층 판정 %d건 요청' % len(review['items']) if review else '')
                    + (' / 검사 경고: %s' % warnings[0] if warnings else '')))


def _open(ctx, scan):
    cfg, state, result = ctx.cfg, ctx.state, scan.result
    scan_warnings = _scan_warnings(scan)
    shown_cap = cfg.limit('max_locations_per_rule')
    unresolved = set(state.get('unresolved') or [])

    lint_cmds = {f['cmd'] for f in result.lint_blocking}
    lint_count = len({cyclelib.lint_key(f) for f in result.lint_blocking})
    for fail in result.lint_raw:
        ctx.event({'event': 'lint', 'stack': fail.get('stack'), 'cmd': fail['cmd'],
                   'anchored': fail['anchored'], 'findings': len(fail.get('locations') or []),
                   'blocking': fail['cmd'] in lint_cmds})

    hits = _findings(ctx, scan)

    def is_repeat(cands):
        return any(c.key in unresolved for c in cands)

    hits.sort(key=lambda h: (_rank(h[0]), not is_repeat(h[1]), -len(h[1])))
    errors = [(r, c[:shown_cap]) for r, c in hits if r['severity'] == 'error']
    errors = errors[:cfg.limit('max_error_rules')]
    warns = [(r, c[:shown_cap]) for r, c in hits if r['severity'] == 'warn']
    warns = warns[:cfg.limit('max_warn_rules')]
    infos = [(r, c) for r, c in hits if r['severity'] == 'info']
    repeats = {r['id'] for r, c in errors + warns if is_repeat(c)}
    all_pending = list(scan.triage.pending) if scan.triage else []
    # a rule this session already settled is not worth an AI call again, but
    # its candidates still count as "seen" so a later re-scan cannot call them new
    pending = [entry for entry in all_pending if not _quiet(ctx, entry[0])]

    streak = int(state.get('consecutive_blocks', 0))
    capped = streak >= cfg.limit('max_consecutive_blocks')
    has_blocking = bool(result.lint_blocking or errors or pending)
    blocking = has_blocking and not cfg.report_only and not capped
    shown = (errors + warns) if blocking else []
    shown_keys = {c.key for _, cands in shown for c in cands}

    for rule, cands in hits:
        for cand in cands:
            ctx.event({'event': 'candidate', 'rule_id': rule['id'], 'key': cand.key,
                       'file': cand.file, 'line': cand.line, 'severity': rule['severity'],
                       'source': rule['source'], 'base_severity': rule.get('base_severity'),
                       'stacks': result.stacks.ids, 'shown': cand.key in shown_keys,
                       'repeat': cand.key in unresolved, 'mode': cfg['mode'],
                       'semantic': bool(rule['review'])})

    if not blocking:
        # the streak only resets on a turn with nothing to block: a turn the cap
        # held back is still part of the runaway loop the cap exists for
        if not has_blocking or cfg.report_only:
            state['consecutive_blocks'] = 0
        ctx.save()
        why = 'mode=report' if cfg.report_only else 'cap'
        for _rule, cand, _pack in pending:
            ctx.event({'event': 'review_skipped', 'rule_id': cand.rule_id, 'key': cand.key,
                       'file': cand.file, 'reason': why})
        extra = ' / 판정 대기 후보 %d건' % len(pending) if pending else ''
        if capped and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건%s 기록 '
                          '(연속 차단 %d회 상한에 걸려 차단하지 않았습니다)%s'
                          % (len(errors), lint_count, extra, streak,
                             _warning_suffix(scan_warnings)))
        if cfg.report_only and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건%s 기록 '
                          '(mode=report 라 차단하지 않았습니다)%s'
                          % (len(errors), lint_count, extra,
                             _warning_suffix(scan_warnings)))
        parts = []
        if warns:
            parts.append('warn %d건 (%s)' % (len(warns), ', '.join(r['id'] for r, _ in warns)))
        if infos:
            parts.append('info %d건' % len(infos))
        if result.lint_notes:
            parts.append('린터가 기존 코드에서 찾은 것 %d건' % len(result.lint_notes))
        if scan_warnings:
            parts.append('검사 경고: %s' % scan_warnings[0])
        if parts:
            return notice('convention-guard: %s 기록. 차단하지 않았습니다.' % ', '.join(parts))
        return None

    opened = {c.key: cyclelib.entry(r, c) for r, cands in shown for c in cands}
    for fail in result.lint_blocking:
        opened[cyclelib.lint_key(fail)] = cyclelib.lint_entry(fail)
    seen = set(_current(ctx, scan)) | {cand.key for _, cand, _ in all_pending}
    cycle = cyclelib.new_cycle(ctx.prompt_id, opened, seen)
    review = _request_review(ctx, cycle, pending, 'open') if pending else None
    if not (opened or review):
        ctx.save()
        return None
    state['cycle'] = cycle
    state['unresolved'] = []
    state['consecutive_blocks'] = streak + 1
    state['blocks'] = int(state.get('blocks', 0)) + 1
    ctx.save()
    ctx.event({'event': 'block', 'cycle': cycle['id'], 'attempt': 0, 'kind': 'open',
               'keys': sorted(opened), 'review': bool(review)})

    reason = report.hook_reason(result.lint_blocking, result.lint_notes, errors, warns, repeats,
                                review=review, warnings=scan_warnings)
    summary = 'convention-guard: %s%s%s%s' % (
        '린트 실패 %d건 ' % lint_count if result.lint_blocking else '',
        'error %d건 / warn %d건' % (len(errors), len(warns)),
        ' / info %d건' % len(infos) if infos else '',
        (' / 심층 판정 %d건 요청' % len(review['items']) if review else '')
        + (' / 검사 경고 %d건' % len(scan_warnings) if scan_warnings else ''))
    return block(reason, summary)


def _rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)
