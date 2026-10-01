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
import time

from . import (autofix, config as configlib, cycle as cyclelib, dismiss as dismisslib, fmt,
               gitdiff, lint, log, pipeline, report, semantic, state as statelib)
from .candidate import VIOLATION, fingerprint, parse_key
from .paths import git_toplevel, hook_project_dir, repo_relative
from .scope import ChangeScope, ScopeError, line_counts

EDIT_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}
WATCHED_TOOLS = EDIT_TOOLS | {'Bash'}
# hooks.json also routes MCP tools here; one counts only when the config names
# it under collect.edit_tools, so a read-only MCP call costs a config read (R23e)
MCP_MATCHER = 'mcp__.*'

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
    """Before the agent writes, remember what is not its own (R12).

    Every file it is about to touch gets a baseline -- the lines it already
    adds over the session base -- the first time. Bash also snapshots dirty
    files, so the Post can tell which of them the call actually changed.
    """
    root = _watched_root(payload)
    if root is None:
        return None
    session = payload.get('session_id')
    head = gitdiff.current_head(root)
    statelib.record_base(session, root, head or gitdiff.session_base(root))
    base = statelib.read_base(session, root)
    if payload.get('tool_name') != 'Bash':
        _record_baseline(session, root, base, _repo_paths(root, payload.get('tool_input')))
        return None
    # the same baseline the Post compares against, or a file committed
    # mid-session would be missing here and read as changed by this call
    paths = gitdiff.changed_paths(root, base)
    # ponytail: every dirty file is read once per session; a huge untracked
    # tree can eat the 10s budget, and then the call is not collected at all
    _record_baseline(session, root, base, paths)
    fingerprints = {rel: gitdiff.file_fingerprint(root, rel) for rel in paths}
    statelib.save_bash_snapshot(session, _tool_use_key(payload), root, fingerprints,
                                head=head, started=time.time())
    return None


def _watched_root(payload):
    """The work tree root when this tool call is one we collect, else None."""
    if not isinstance(payload, dict):
        return None
    name = str(payload.get('tool_name') or '')
    if name not in WATCHED_TOOLS and not name.startswith('mcp__'):
        return None
    root = git_toplevel(hook_project_dir(payload))
    if name in WATCHED_TOOLS:
        return root
    try:
        named = configlib.load(root).get('collect', {}).get('edit_tools') or ()
    except Exception:       # noqa: BLE001 -- a bad config must not break a tool call
        return None
    return root if name in named else None


def _record_baseline(session, root, base, rels):
    baselined, _ = statelib.read_foreign(session, root)
    todo = [rel for rel in dict.fromkeys(rels) if rel not in baselined]
    if not todo:
        return
    added = gitdiff.added_lines(root, todo, base)
    # a clean file is recorded too: empty, so no later Pre can baseline it
    # after the agent has written to it
    statelib.append_foreign(session, root, {rel: line_counts(added.get(rel, ())) for rel in todo})


def _claim(session, root, rels):
    """A file changed without a baseline (its Pre never ran) keeps every line
    -- as before baselines existed -- and no later Pre may baseline the agent's lines."""
    baselined, _ = statelib.read_foreign(session, root)
    missing = [rel for rel in dict.fromkeys(rels) if rel not in baselined]
    statelib.append_foreign(session, root, {rel: {} for rel in missing})


def _record_arrived(session, root, snapshot, rels):
    """Lines other people's commits brought in during this Bash call are theirs."""
    old, new = snapshot.get('head'), gitdiff.current_head(root)
    if old == new:
        return
    arrived = gitdiff.arrived_lines(root, old, new, snapshot.get('started'), rels)
    statelib.append_foreign(session, root,
                            {rel: line_counts(lines) for rel, lines in arrived.items()},
                            kind='arrived')


def _repo_paths(root, tool_input):
    """The tool's file paths, relative to the work tree; outside it is dropped."""
    found = []
    for raw in _candidate_paths(tool_input):
        rel = repo_relative(raw if os.path.isabs(raw) else os.path.join(root, raw), root)
        if rel is not None:
            found.append(rel)
    return found


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
    root = _watched_root(payload)
    if root is None:
        return None
    session = payload.get('session_id')
    statelib.record_base(session, root, gitdiff.session_base(root))
    if payload.get('tool_name') == 'Bash':
        tool_key = _tool_use_key(payload)
        snapshot = statelib.read_bash_snapshot(session, tool_key, root)
        if snapshot is None:
            statelib.append_bash_miss(session)      # said at Stop (R23d)
            return None
        before = snapshot['fingerprints']
        base_ref = statelib.read_base(session, root)
        changed = gitdiff.changed_paths(root, base_ref)
        found = [rel for rel in changed
                 if before.get(rel) != gitdiff.file_fingerprint(root, rel)]
        _record_arrived(session, root, snapshot, found)
        _claim(session, root, found)
        statelib.append_touched(session, found)
        # A missing tool_use_id cannot distinguish identical parallel Bash
        # calls. Keep their shared snapshot until GC so every Post can consume it.
        if payload.get('tool_use_id'):
            statelib.delete_bash_snapshot(session, tool_key)
        return None
    found = _repo_paths(root, payload.get('tool_input'))
    _claim(session, root, found)
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
    first, _, rest = str(text).strip().partition('\n')
    if rest:
        first += ' … — 전체: %s' % fmt.command('detect_stack.py')
    return notice(report.hook_header('건너뜀', ['설정 오류: %s' % first]))


def _entry(rule, cand):
    """cycle.entry, with no line for a file- or change-level candidate (F4)."""
    return dict(cyclelib.entry(rule, cand), line=report.cand_line(rule, cand))


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
        self.last_scan = None

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
    # a linter that did not run outranks the rest: it is a hole in the check
    warnings.sort(key=lambda text: (0 if getattr(text, 'kind', None) == lint.UNCHECKED else 1,
                                    text))
    return warnings


def _warning_part(warnings):
    return '검사 경고 %d: %s' % (len(warnings), warnings[0]) if warnings else ''


def unchecked_note(unchecked, limit=None, short=False):
    """'구조 미확인 2개 파일 — a.php, b.php (...)', or None when there is none.
    short: the systemMessage form, '구조 미확인 2개 파일 (a.php, b.php)'.

    A file whose structure could not be read had its conditions skipped, so
    its candidates came through unfiltered. Saying nothing would let that read
    as a clean pass (NFR-02.2, US-06).
    """
    if not unchecked:
        return None
    shown, folded = unchecked.summary(limit)
    listed = ', '.join(shown) + (' 외 %d개' % folded if folded else '')
    if short:
        return '구조 미확인 %d개 파일 (%s)' % (len(unchecked), listed)
    return ('구조 미확인 %d개 파일 — %s (구조 조건을 적용하지 못해 후보를 그대로 올렸습니다)'
            % (len(unchecked), listed))


def too_large_note(paths, limit=None, short=False):
    """'큰 파일 미검사 1개 파일 — big.php (…)', or None when there is none.

    A file past the size cap was not read at all, so no rule saw it. That is
    not a pass and must not read like one (R20).
    """
    if not paths:
        return None
    listed = _listed(paths, limit)
    if short:
        return '큰 파일 미검사 %d개 파일 (%s)' % (len(paths), listed)
    return ('큰 파일 미검사 %d개 파일 — %s (%dKB 를 넘어 규칙을 적용하지 않았습니다)'
            % (len(paths), listed, gitdiff.MAX_BYTES // 1000))


def unknown_note(paths):
    """'검사되지 않음 1개 파일 (sub/x.php)': touched, but in a place git cannot
    see from this repo (a nested repo or worktree), so nothing checked it (R23b)."""
    if not paths:
        return None
    return '검사되지 않음 %d개 파일 (%s)' % (len(paths), _listed(paths, None))


def _listed(paths, limit):
    shown = list(paths[:limit]) if limit else list(paths)
    folded = len(paths) - len(shown)
    return ', '.join(shown) + (' 외 %d개' % folded if folded else '')


def on_stop(payload):
    if not isinstance(payload, dict):
        return None
    ctx = StopContext(payload)
    return _with_unchecked_note(ctx, _with_autofix_note(ctx, _stop(ctx)))


def _with_autofix_note(ctx, out):
    """Files auto-fix rewrote changed under the agent; it must hear about it."""
    if not ctx.autofixed:
        return out
    files = sorted({fix.file for fix in ctx.autofixed})
    note = ('자동 수정 %d (%s) — 편집 전에 다시 읽으세요' % (len(ctx.autofixed), ', '.join(files)))
    if out and out.get('decision') == 'block':
        out['reason'] = report.with_section(out['reason'], report.autofix_section(ctx.autofixed))
        out['systemMessage'] = _join_messages(out.get('systemMessage'), note, 'pass')
        return out
    return notice(_join_messages(out.get('systemMessage') if out else None, note, 'pass'))


def _with_unchecked_note(ctx, out):
    """Structure conditions that could not be evaluated, and files too big to
    read, get said out loud."""
    scan = getattr(ctx, 'last_scan', None)
    notes = [] if scan is None else [
        n for n in (unchecked_note(scan.result.unchecked, short=True),
                    too_large_note(scan.result.too_large, short=True),
                    unknown_note(scan.result.unknown)) if n]
    session = getattr(ctx, 'session', None)
    misses = statelib.take_bash_misses(session) if session else 0
    if misses:
        notes.append('Bash 변경 미수집 %d회 (실행 전 기록이 없어 바뀐 파일을 모름)' % misses)
    if not notes:
        return out
    note = ' · '.join(notes)
    if out and out.get('decision') == 'block':
        out['systemMessage'] = _join_messages(out.get('systemMessage'), note)
        return out
    return notice(_join_messages(out.get('systemMessage') if out else None, note))


def _join_messages(existing, note, kind='warn'):
    """One line, one `convention-guard`: notes follow the header after ` · `."""
    return '%s · %s' % (existing, note) if existing else report.hook_header('기록', [note], kind)


def _stop(ctx):
    payload = ctx.payload
    errors = [text for level, text in ctx.cfg.notes if level == 'error']
    if errors:
        return config_error(errors[0])

    state = ctx.state
    cycle = state.get('cycle')
    if not ctx.continuing or (cycle and _belongs_to_new_request(ctx, cycle)):
        # the cap guards one request's loop; a new request starts its own (R4)
        state['consecutive_blocks'] = 0
    scan, scanned = None, False
    if cycle and _belongs_to_new_request(ctx, cycle):
        scan, scanned = _scan(ctx), True
        if scan is not None and scan.errors:
            return config_error(scan.errors[0])
        current = _current(ctx, scan)
        _close(ctx, cycle, _classify(ctx, cycle, scan, current), abandoned=True,
               current=current)
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
    """Scan, remembering the outcome so the notices can look at it."""
    outcome = _run_scan(ctx)
    if outcome is not None and hasattr(outcome, 'result'):
        ctx.last_scan = outcome
    return outcome


def _run_scan(ctx):
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
    _, foreign = statelib.read_foreign(ctx.session, ctx.root)
    try:
        scope = ChangeScope.from_touched(ctx.root, touched, base_ref or None, foreign)
    except ScopeError as exc:
        return ScanFailure(str(exc))
    if not scope and not (scope.too_large or scope.unknown):
        return None         # a file we could not read still has to be named (R20, R23b)
    result = pipeline.run(scope, ctx.cfg, cap=VERIFY_CAP, lint_budget=LINT_BUDGET)
    if ctx.cfg['mode'] == 'auto-fix' and not result.errors and not ctx.autofixed:
        applied = autofix.apply(ctx.root, autofix.plan(ctx.root, result.hits))
        if applied:
            for fix in applied:
                ctx.event(dict(fix.to_dict(), event='autofix'))
            ctx.autofixed = applied
            # the scope caches file text and diffs; the files just changed
            scope = ChangeScope.from_touched(scope.root, touched, scope.base_ref, foreign)
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
            current[cand.key] = _entry(rule, cand)
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


def _classify(ctx, cycle, scan, current=None):
    review = cycle.get('review') or {}
    if review.get('batch'):
        # a candidate the reviewer called a VIOLATION is one the agent was told
        # to fix: from here on it is tracked like any other flagged finding
        recorded = semantic.read_verdicts(review['batch']) or {}
        for review_key, verdict in recorded.items():
            item = review['items'].get(review_key)
            if item and verdict.get('verdict') == VIOLATION:
                cycle['opened'].setdefault(item['key'], dict(item))
    if current is None:
        current = _current(ctx, scan)
    unfinished = scan.result.lint_unfinished if scan is not None else ()
    unconfirmed = {cyclelib.lint_key({'key': key, 'cmd': ''}) for key in unfinished}
    return cyclelib.classify(cycle, current, _dismissed_predicate(ctx.root), unconfirmed)


def _hidden(outcome, current):
    """Blocking findings still there that the cycle never showed -- past the
    display budget. Not a failed fix, but not a pass either (R3)."""
    shown = set(outcome.remaining())
    return sorted(k for k, m in current.items()
                  if k not in shown and not k.startswith('lint:')
                  and m['severity'] in cyclelib.BLOCKING)


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


def _close(ctx, cycle, outcome, abandoned=False, unreviewed=(), current=None):
    _log_outcome(ctx, cycle, outcome, abandoned)
    for _rule, cand, _pack in unreviewed:
        ctx.event({'event': 'review_skipped', 'cycle': cycle['id'], 'rule_id': cand.rule_id,
                   'key': cand.key, 'file': cand.file, 'reason': 'attempts'})
    if abandoned:
        ctx.event(dict({'event': 'abandoned', 'cycle': cycle['id']}, **outcome.counts()))
    state = ctx.state
    current = current or {}
    settled = {m['rule_id'] for m in outcome.fixed.values()}
    unsettled = {m['rule_id'] for m in outcome.remaining().values()}
    unsettled |= {m['rule_id'] for m in outcome.dismissed.values()}
    # a rule with anything left -- shown or not -- is not settled (R3)
    unsettled |= {m['rule_id'] for m in current.values()}
    state['fired_rules'] = sorted(set(state.get('fired_rules') or [])
                                  | (settled - unsettled - {'lint'}))
    # what was never shown comes back next request, marked as raised before
    state['unresolved'] = sorted(set(k for k in outcome.remaining() if not k.startswith('lint:'))
                                 | set(_hidden(outcome, current)))
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
    by_key = {}
    for rule, cand, _ in pending:       # the first candidate, as the batch item (R7)
        by_key.setdefault(cand.review_key, (rule, cand))
    cycle['review'] = {'batch': path, 'items': {
        item['review_key']: dict(_entry(*by_key[item['review_key']]),
                                 key=item['key'])
        for item in items}}
    ctx.event({'event': 'review_requested', 'cycle': cycle['id'], 'batch': path,
               'rules': sorted({i['rule_id'] for i in items}), 'candidates': len(items),
               'deferred': len(deferred)})
    return {'batch': path, 'items': items, 'deferred': len(deferred)}


def _verify(ctx, cycle, scan):
    current = _current(ctx, scan)
    outcome = _classify(ctx, cycle, scan, current)
    # a rule cut at VERIFY_CAP brings older candidates into view once some
    # are fixed: they were there all along, not new (C6)
    capped = {rule['id'] for rule, cands in scan.result.hits
              if len(cands) >= VERIFY_CAP} if scan is not None else set()
    for key in [k for k, m in outcome.new.items() if m['rule_id'] in capped]:
        del outcome.new[key]
    hidden = _hidden(outcome, current)
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
        _close(ctx, cycle, outcome, unreviewed=skipped + needs, current=current)
        counts = outcome.counts()
        unshown = '미표시 %d' % len(hidden) if hidden else ''
        unsure = outcome.unconfirmed()
        if unsure:          # a linter that timed out has not confirmed anything (R17)
            return notice(report.hook_header('재검증 종료', [
                '고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'],
                '남음 %d' % (counts['still'] - len(unsure)), '새로 생김 %d' % counts['new'],
                '린터 미확인 %d' % len(unsure), unshown, _warning_part(warnings),
                '이후 기록만'], 'warn'))
        if not outcome.remaining() and not (skipped or needs):
            if hidden:      # what was shown is fixed; the rest is not a pass (R3)
                return notice(report.hook_header('재검증 종료', [
                    '고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'], unshown,
                    _warning_part(warnings), '다음 요청에서 다시 알림'], 'warn'))
            return notice(report.hook_header('재검증 통과', [
                '고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'],
                _warning_part(warnings)], 'pass'))
        return notice(report.hook_header('재검증 종료', [
            '고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'],
            '남음 %d' % counts['still'], '새로 생김 %d' % counts['new'], unshown,
            '판정 대기 %d' % len(skipped + needs) if skipped or needs else '',
            _warning_part(warnings), '이후 기록만'], 'warn'))

    _log_outcome(ctx, cycle, outcome)
    for _rule, cand, _pack in skipped:
        ctx.event({'event': 'review_skipped', 'cycle': cycle['id'], 'rule_id': cand.rule_id,
                   'key': cand.key, 'file': cand.file, 'reason': 'not_run'})
    cycle['attempt'] += 1
    last_chance = (not review_page
                   and cycle['attempt'] >= cfg.limit('max_verify_attempts'))
    cycle['opened'] = outcome.remaining()
    cycle['seen'] = sorted(set(cycle.get('seen') or ()) | set(current))
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
    return _block(report.verify_reason(outcome, last_chance, review, skipped=bool(skipped),
                                       warnings=warnings))


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
        return any(c.key in unresolved or unresolved.intersection(c.legacy_keys)
                   for c in cands)

    hits.sort(key=lambda h: (_rank(h[0]), not is_repeat(h[1]), -len(h[1])))
    all_errors = [(r, c) for r, c in hits if r['severity'] == 'error']
    all_warns = [(r, c) for r, c in hits if r['severity'] == 'warn']
    errors = [(r, c[:shown_cap]) for r, c in all_errors][:cfg.limit('max_error_rules')]
    warns = [(r, c[:shown_cap]) for r, c in all_warns][:cfg.limit('max_warn_rules')]
    # what the budget left out is counted in the block, never just dropped (R3)
    more = {r['id']: len(c) - shown_cap for r, c in all_errors + all_warns if len(c) > shown_cap}
    hidden_rules = (len(all_errors) - len(errors), len(all_warns) - len(warns))
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
        if has_blocking:
            held = '연속 차단 %d회 상한' % streak if capped else 'mode=report'
            return notice(report.hook_header('기록', [
                '린터 실패 %d' % lint_count if lint_count else '',
                'error %d' % len(errors) if errors else '',
                '판정 대기 %d' % len(pending) if pending else '',
                _warning_part(scan_warnings), '차단 안 함: %s' % held],
                'error' if errors or lint_count else 'warn'))
        parts = ['warn %d (%s)' % (len(warns), ', '.join(r['id'] for r, _ in warns))
                 if warns else '',
                 'info %d' % len(infos) if infos else '',
                 '린터 참고 %d' % len(result.lint_notes) if result.lint_notes else '',
                 _warning_part(scan_warnings)]
        if any(parts):
            only_info = infos and not (warns or result.lint_notes or scan_warnings)
            return notice(report.hook_header('기록', parts, 'info' if only_info else 'warn'))
        return None

    opened = {c.key: _entry(r, c) for r, cands in shown for c in cands}
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

    return _block(report.hook_reason(result.lint_blocking, result.lint_notes, errors, warns,
                                     repeats, review=review, warnings=scan_warnings,
                                     lint_count=lint_count, info_count=len(infos),
                                     more=more, hidden_rules=hidden_rules))


def _block(reason):
    """The user sees the reason's header line (D11)."""
    return block(reason, reason.split('\n', 1)[0])


def _rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)
