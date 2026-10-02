"""The Stop hook's shell: fetch, decide, store, say.

    payload -> Request, config, state                      (read)
            -> the edit ledger settled for this Stop       (ledger.at_stop)
            -> scan (+ auto-fix) and the verdict cache     (only if decide.needs_scan)
            -> decide.decide(state, observation, cfg)       (pure, lib/decide.py)
            -> review batch, state, firing log              (write)
            -> hook output: the action plus the notices     (render)

Every judgment lives in decide.py. What is here only moves values between
the world and that function, so a manual run (scan.py) and the hook share
every decision that matters through the pipeline, and the cycle's
transitions are tested without a repo (tests/unit/test_decide.py).
"""

import time

from . import (autofix, config as configlib, decide, dismiss as dismisslib, fmt, ledger, lint,
               log, observe, pipeline, report, semantic, state as statelib, store)
from .candidate import parse_key
from .paths import hook_project_dir
from .scope import ChangeScope

# Locations per rule the re-scan collects. Far above what a block shows, so a
# flagged candidate is not read as fixed merely because others crowd it out.
VERIFY_CAP = 50

# Seconds the whole lint phase may take inside the Stop hook. hooks.json gives
# check.py 150s; `linters.timeout` is per linter and they run one after another,
# so a laravel repo (php-cs-fixer + pint + phpstan) can ask for 270s. Going over
# gets the hook killed, and a killed hook prints nothing -- which reads exactly
# like a clean check. Leave room for the re-scan and the semantic batch.
LINT_BUDGET = 110


# ---------------------------------------------------------------- output shapes

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


def render(action):
    """decide's Action -> the hook's JSON object (or None)."""
    if action.kind == 'config_error':
        return config_error(action.text)
    if action.kind == 'notice':
        return notice(report.hook_header(action.word, action.parts, action.level))
    if action.kind == 'block':
        if action.form == 'verify':
            reason = report.verify_reason(**action.args)
        else:
            reason = report.hook_reason(**action.args)
        return block(reason, reason.split('\n', 1)[0])     # the user sees the header (D11)
    return None


# ---------------------------------------------------------------- the scan

class Scan:
    """One re-scan: the pipeline result plus what the verdict cache says."""

    def __init__(self, result, triage):
        self.result, self.triage = result, triage


def scan_warnings(scan):
    if scan is None or not hasattr(scan, 'result'):
        return []
    warnings = [text for level, text in scan.result.notes if level == 'warn']
    # a linter that did not run outranks the rest: it is a hole in the check
    warnings.sort(key=lambda text: (0 if getattr(text, 'kind', None) == lint.UNCHECKED else 1,
                                    text))
    return warnings


def view_of(scan):
    """Scan | ScanFailure | None -> what decide() reads."""
    if scan is None or isinstance(scan, decide.ScanFailure):
        return scan
    result, triage = scan.result, scan.triage
    if result.errors:
        return decide.ScanFailure(result.errors[0])
    return decide.ScanView(
        hits=result.hits,
        violations=triage.violations if triage else (),
        pending=triage.pending if triage else (),
        lint_blocking=result.lint_blocking, lint_notes=result.lint_notes,
        lint_raw=result.lint_raw, lint_unfinished=result.lint_unfinished,
        warnings=scan_warnings(scan), stacks=result.stacks.ids,
        capped={rule['id'] for rule, cands in result.hits if len(cands) >= VERIFY_CAP})


class Shell:
    def __init__(self, payload):
        self.payload = payload
        self.repo = observe.toplevel(hook_project_dir(payload))      # None outside git
        self.root = self.repo or hook_project_dir(payload)
        self.session = payload.get('session_id')
        self.cfg = configlib.load(self.root)
        self.autofixed = []
        self.scan = None
        self.ledger = ledger.StopLedger()

    def event(self, record):
        log.event(dict(record, session=self.session, repo=self.root))

    def run_scan(self):
        """What the agent wrote this session, checked -- or None when there is
        nothing it answers for."""
        owned = self.ledger.owned()
        if self.repo is None or not owned:
            return None
        skip = observe.ignored(self.root, [entry.path for entry in owned])
        scope = ChangeScope.from_ledger(self.root, owned, skip)
        if not scope and not scope.too_large:
            return None         # a file we could not read still has to be named (R20)
        result = pipeline.run(scope, self.cfg, cap=VERIFY_CAP, lint_budget=LINT_BUDGET)
        # an ignored config key (a 3.x one, a typo) is said like any other
        # scan warning, or a setting the person relies on goes quietly unread
        result.notes.extend(note for note in self.cfg.notes if note[0] == 'warn')
        if self.cfg['mode'] == 'auto-fix' and not result.errors and not self.autofixed:
            applied = autofix.apply(self.root, autofix.plan(self.root, result.hits))
            if applied:
                for fix in applied:
                    self.event(dict(fix.to_dict(), event='autofix'))
                self.autofixed = applied
                # the fix is made on the agent's behalf: its lines are the agent's
                entries = ledger.refresh(self.session, self.root,
                                         sorted({fix.file for fix in applied}))
                scope = ChangeScope.from_ledger(self.root, [e for e in entries if e.owned()],
                                                skip)
                result = pipeline.run(scope, self.cfg, cap=VERIFY_CAP, lint_budget=LINT_BUDGET)
        triage = None
        if self.cfg['semantic_review']['enabled'] and not result.errors and result.semantic_hits:
            triage = semantic.triage(result, self.cfg)
        self.scan = Scan(result, triage)
        return self.scan


def _dismissed_predicate(root):
    dismissals = dismisslib.load(root)

    def is_dismissed(key):
        try:
            rule_id, relpath, digest = parse_key(key)
        except ValueError:
            return False
        return dismissals.is_dismissed(rule_id, relpath, digest)
    return is_dismissed


def on_stop(payload):
    if not isinstance(payload, dict):
        return None
    shell = Shell(payload)
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    request = decide.Request(prompt_id, payload.get('stop_hook_active'),
                             ends_with_question(payload.get('last_assistant_message')))
    errors = [text for level, text in shell.cfg.notes if level == 'error']
    config_error_text = errors[0] if errors else None
    state = statelib.load(shell.session)
    shell.ledger = ledger.at_stop(shell.session, shell.repo)

    scan = shell.run_scan() if decide.needs_scan(state, request, shell.cfg,
                                                 config_error_text) else None
    cycle = state.get('cycle') or {}
    review = cycle.get('review') or {}
    obs = decide.Observation(
        request, config_error=config_error_text, scan=view_of(scan),
        is_dismissed=_dismissed_predicate(shell.root) if cycle else None,
        cycle_verdicts=semantic.read_verdicts(review['batch']) if review.get('batch') else None,
        batch=decide.BatchSlot(semantic.new_batch_id(), store.path(), shell.root, shell.session,
                               log.log_path()),
        now=time.time())
    decision = decide.decide(state, obs, shell.cfg)
    _install_engine_if_missing(shell.scan)

    if decision.batch:          # before the state, so no state names a missing batch
        semantic.save_batch(*decision.batch)
    if decision.state is not None:
        statelib.save(shell.session, decision.state)
    for record in decision.events:
        shell.event(record)
    out = render(decision.action)
    return with_notes(with_autofix_note(out, shell.autofixed), shell.scan, shell.ledger.issues)


def _install_engine_if_missing(scan):
    """The engine was needed and is not there: start installing it in the
    background (SessionStart may not have run). This Stop does not wait."""
    unchecked = getattr(getattr(scan, 'result', None), 'unchecked', None)
    if not unchecked:
        return
    reasons = {unchecked.reason(f) for f in unchecked.files()}
    if reasons & {'engine_missing:not_installed', 'engine_missing:failed'}:
        import os
        from .engine import install
        install.kick(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  'engine.py'))


# ---------------------------------------------------------------- notices

def with_autofix_note(out, autofixed):
    """Files auto-fix rewrote changed under the agent; it must hear about it."""
    if not autofixed:
        return out
    files = sorted({fix.file for fix in autofixed})
    note = ('자동 수정 %d (%s) — 편집 전에 다시 읽으세요' % (len(autofixed), ', '.join(files)))
    if out and out.get('decision') == 'block':
        out['reason'] = report.with_section(out['reason'], report.autofix_section(autofixed))
        out['systemMessage'] = _join_messages(out.get('systemMessage'), note, 'pass')
        return out
    return notice(_join_messages(out.get('systemMessage') if out else None, note, 'pass'))


def with_notes(out, scan, issues=()):
    """Structure conditions that could not be evaluated, files too big to read,
    and every gap in what the collect hooks saw get said out loud."""
    result = getattr(scan, 'result', None)
    notes = [] if result is None else [
        n for n in (report.unchecked_note(result.unchecked, short=True),
                    report.too_large_note(result.too_large, short=True)) if n]
    notes += report.gap_notes(issues)
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
