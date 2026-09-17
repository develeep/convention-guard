"""Hook policy: what happens on PostToolUse and Stop.

scripts/collect.py and scripts/check.py only parse stdin and print what these
functions return. Checking is the pipeline's job; the verification cycle
(cycle.py) is the state machine; this module decides *when* each runs and
*what to do* with the result -- block, report, or stay quiet.

Stop, in order:
  1. config broken      -> say so and skip (never check with unchosen defaults)
  2. a cycle is open    -> the request it belongs to ended? close it (abandoned)
                           otherwise re-scan and verify
  3. no cycle           -> question turn? nothing changed? stay quiet
                           else check, apply the budget, block and open a cycle
"""

import json
import os

from . import (config as configlib, cycle as cyclelib, dismiss as dismisslib, gitdiff, log,
               pipeline, report, state as statelib)
from .candidate import parse_key
from .paths import git_toplevel, hook_project_dir
from .scope import ChangeScope, ScopeError

WATCHED_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}

# Locations per rule the re-scan collects. Far above what a block shows, so a
# flagged candidate is not read as fixed merely because others crowd it out.
VERIFY_CAP = 50


# ---------------------------------------------------------------- PostToolUse

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
    found = []
    for raw in _candidate_paths(payload.get('tool_input')):
        absolute = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(root, raw))
        try:
            rel = os.path.relpath(absolute, root)
        except ValueError:
            continue
        if not rel.startswith('..'):
            found.append(rel.replace(os.sep, '/'))
    statelib.append_touched(payload.get('session_id'), found)
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

    def save(self):
        statelib.save(self.session, self.state)

    def event(self, record):
        log.event(dict(record, session=self.session))


def on_stop(payload):
    if not isinstance(payload, dict):
        return None
    ctx = StopContext(payload)
    errors = [text for level, text in ctx.cfg.notes if level == 'error']
    if errors:
        return config_error(errors[0])

    state = ctx.state
    cycle = state.get('cycle')
    result = None
    scanned = False
    if cycle and _belongs_to_new_request(ctx, cycle):
        result, scanned = _scan(ctx), True
        if result is not None and result.errors:
            return config_error(result.errors[0])
        _close(ctx, cycle, _classify(ctx, cycle, result), abandoned=True)
        cycle = None

    if not ctx.continuing:
        state['closed_in_continuation'] = False

    if cycle:
        result = _scan(ctx)
        if result is not None and result.errors:
            return config_error(result.errors[0])
        return _verify(ctx, cycle, result)

    if ctx.continuing and state.get('closed_in_continuation'):
        # this request already had its cycle; another hook kept the agent going
        ctx.save()
        return None
    if ctx.cfg['skip_if_question'] and ends_with_question(payload.get('last_assistant_message')):
        ctx.save()
        return None

    if not scanned:
        result = _scan(ctx)
    if result is None:
        _clean_turn(ctx)
        return None
    if result.errors:
        return config_error(result.errors[0])
    return _open(ctx, result)


def _belongs_to_new_request(ctx, cycle):
    if ctx.prompt_id and cycle.get('prompt_id'):
        return ctx.prompt_id != cycle['prompt_id']
    # without prompt ids, a Stop that is not a continuation of our own block
    # means the request ended (the user interrupted and sent something new)
    return not ctx.continuing


def _scan(ctx):
    """Pipeline result for everything touched this session, or None when
    there is nothing to inspect (no edits, not a repo, all reverted)."""
    touched = statelib.read_touched(ctx.session)
    if not touched:
        return None
    try:
        scope = ChangeScope.from_touched(
            ctx.root, touched, gitdiff.resolve_base_ref(ctx.root, ctx.cfg['scope']['base_ref']))
    except ScopeError:
        return None
    if not scope:
        return None
    return pipeline.run(scope, ctx.cfg, cap=VERIFY_CAP)


def _clean_turn(ctx):
    ctx.state['consecutive_blocks'] = 0
    ctx.save()


def _quiet(ctx, rule):
    return ctx.cfg['once_per_session'] and rule['id'] in (ctx.state.get('fired_rules') or [])


def _current(ctx, result):
    """{key: entry} for every candidate and blocking lint failure right now,
    minus rules the session already settled (once_per_session)."""
    current = {}
    if result is None:
        return current
    for rule, cands in result.hits:
        if _quiet(ctx, rule):
            continue
        for cand in cands:
            current[cand.key] = cyclelib.entry(rule, cand)
    for fail in result.lint_blocking:
        current[cyclelib.lint_key(fail)] = cyclelib.lint_entry(fail)
    return current


def _dismissed_predicate(root):
    keys, _ = dismisslib.load(root)

    def is_dismissed(key):
        try:
            rule_id, relpath, digest = parse_key(key)
        except ValueError:
            return False
        return (rule_id, relpath) in keys or (rule_id, relpath, digest) in keys
    return is_dismissed


def _classify(ctx, cycle, result):
    return cyclelib.classify(cycle, _current(ctx, result), _dismissed_predicate(ctx.root))


def _log_outcome(ctx, cycle, outcome, abandoned=False):
    for label, items in ((cyclelib.FIXED, outcome.fixed), (cyclelib.DISMISSED, outcome.dismissed),
                         (cyclelib.STILL, outcome.still), (cyclelib.NEW, outcome.new)):
        for key, meta in items.items():
            ctx.event({'event': 'verify', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
                       'outcome': label, 'key': key, 'rule_id': meta['rule_id'],
                       'severity': meta['severity'], 'file': meta['file'],
                       'abandoned': abandoned})


def _close(ctx, cycle, outcome, abandoned=False):
    _log_outcome(ctx, cycle, outcome, abandoned)
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


def _verify(ctx, cycle, result):
    outcome = _classify(ctx, cycle, result)
    cfg = ctx.cfg
    streak = int(ctx.state.get('consecutive_blocks', 0))
    again = bool(outcome.blocking() and not cfg.report_only
                 and cycle['attempt'] < cfg.limit('max_verify_attempts')
                 and streak < cfg.limit('max_consecutive_blocks'))
    if not again:
        _close(ctx, cycle, outcome)
        if not outcome.remaining():
            return None
        counts = outcome.counts()
        return notice('convention-guard: 재검증 — 고쳐짐 %d / 기각 %d / 남음 %d / 새로 생김 %d. '
                      '더 차단하지 않고 기록만 남깁니다.'
                      % (counts['fixed'], counts['dismissed'], counts['still'], counts['new']))

    _log_outcome(ctx, cycle, outcome)
    cycle['attempt'] += 1
    last_chance = cycle['attempt'] >= cfg.limit('max_verify_attempts')
    cycle['opened'] = outcome.remaining()
    cycle['seen'] = sorted(set(cycle.get('seen') or ()) | set(_current(ctx, result)))
    ctx.state['cycle'] = cycle
    ctx.state['consecutive_blocks'] = streak + 1
    ctx.state['blocks'] = int(ctx.state.get('blocks', 0)) + 1
    ctx.save()
    ctx.event({'event': 'block', 'cycle': cycle['id'], 'attempt': cycle['attempt'],
               'kind': 'verify', 'keys': sorted(outcome.blocking())})
    counts = outcome.counts()
    return block(report.verify_reason(outcome, last_chance),
                 'convention-guard: 재검증 — 남음 %d / 새로 생김 %d'
                 % (counts['still'], counts['new']))


def _open(ctx, result):
    cfg, state = ctx.cfg, ctx.state
    shown_cap = cfg.limit('max_locations_per_rule')
    unresolved = set(state.get('unresolved') or [])

    lint_cmds = {f['cmd'] for f in result.lint_blocking}
    for fail in result.lint_raw:
        ctx.event({'event': 'lint', 'stack': fail.get('stack'), 'cmd': fail['cmd'],
                   'anchored': fail['anchored'], 'findings': len(fail.get('locations') or []),
                   'blocking': fail['cmd'] in lint_cmds})

    hits = [(rule, cands) for rule, cands in result.hits if not _quiet(ctx, rule)]

    def is_repeat(cands):
        return any(c.key in unresolved for c in cands)

    hits.sort(key=lambda h: (_rank(h[0]), not is_repeat(h[1]), -len(h[1])))
    errors = [(r, c[:shown_cap]) for r, c in hits if r['severity'] == 'error']
    errors = errors[:cfg.limit('max_error_rules')]
    warns = [(r, c[:shown_cap]) for r, c in hits if r['severity'] == 'warn']
    warns = warns[:cfg.limit('max_warn_rules')]
    infos = [(r, c) for r, c in hits if r['severity'] == 'info']
    repeats = {r['id'] for r, c in errors + warns if is_repeat(c)}

    streak = int(state.get('consecutive_blocks', 0))
    capped = streak >= cfg.limit('max_consecutive_blocks')
    has_blocking = bool(result.lint_blocking or errors)
    blocking = has_blocking and not cfg.report_only and not capped
    shown = (errors + warns) if blocking else []
    shown_keys = {c.key for _, cands in shown for c in cands}

    for rule, cands in hits:
        for cand in cands:
            ctx.event({'event': 'candidate', 'rule_id': rule['id'], 'key': cand.key,
                       'file': cand.file, 'line': cand.line, 'severity': rule['severity'],
                       'source': rule['source'], 'base_severity': rule.get('base_severity'),
                       'stacks': result.stacks.ids, 'shown': cand.key in shown_keys,
                       'repeat': cand.key in unresolved, 'mode': cfg['mode']})

    if not blocking:
        # the streak only resets on a turn with nothing to block: a turn the cap
        # held back is still part of the runaway loop the cap exists for
        if not has_blocking or cfg.report_only:
            state['consecutive_blocks'] = 0
        ctx.save()
        if capped and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                          '(연속 차단 %d회 상한에 걸려 차단하지 않았습니다)'
                          % (len(errors), len(result.lint_blocking), streak))
        if cfg.report_only and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                          '(mode=report 라 차단하지 않았습니다)'
                          % (len(errors), len(result.lint_blocking)))
        parts = []
        if warns:
            parts.append('warn %d건 (%s)' % (len(warns), ', '.join(r['id'] for r, _ in warns)))
        if infos:
            parts.append('info %d건' % len(infos))
        if result.lint_notes:
            parts.append('린터가 기존 코드에서 찾은 것 %d건' % len(result.lint_notes))
        if parts:
            return notice('convention-guard: %s 기록. 차단하지 않았습니다.' % ', '.join(parts))
        return None

    opened = {c.key: cyclelib.entry(r, c) for r, cands in shown for c in cands}
    for fail in result.lint_blocking:
        opened[cyclelib.lint_key(fail)] = cyclelib.lint_entry(fail)
    cycle = cyclelib.new_cycle(ctx.prompt_id, opened, _current(ctx, result))
    state['cycle'] = cycle
    state['unresolved'] = []
    state['consecutive_blocks'] = streak + 1
    state['blocks'] = int(state.get('blocks', 0)) + 1
    ctx.save()
    ctx.event({'event': 'block', 'cycle': cycle['id'], 'attempt': 0, 'kind': 'open',
               'keys': sorted(opened)})

    reason = report.hook_reason(result.lint_blocking, result.lint_notes, errors, warns, repeats)
    summary = 'convention-guard: %s%s%s' % (
        '린트 실패 %d건 ' % len(result.lint_blocking) if result.lint_blocking else '',
        'error %d건 / warn %d건' % (len(errors), len(warns)),
        ' / info %d건' % len(infos) if infos else '')
    return block(reason, summary)


def _rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)


# ---------------------------------------------------------------- semantic gate

def semantic_queue(payload):
    """Gate for the optional `type: agent` Stop hook. Returns 'EMPTY' or JSON."""
    if not isinstance(payload, dict):
        return 'EMPTY'
    root = git_toplevel(hook_project_dir(payload))
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg = configlib.load(root)
    state = statelib.load(session, 'semantic')
    if not cfg['semantic_review']['enabled']:
        return 'EMPTY'
    if prompt_id is not None and str(prompt_id) in state.get('reviewed_prompt_ids', []):
        return 'EMPTY'
    touched = statelib.read_touched(session)
    if not touched:
        return 'EMPTY'
    try:
        scope = ChangeScope.from_touched(
            root, touched, gitdiff.resolve_base_ref(root, cfg['scope']['base_ref']))
    except ScopeError:
        return 'EMPTY'
    if not scope:
        return 'EMPTY'
    result = pipeline.run(scope, cfg, run_lint=False)
    reviewed = set(state.get('reviewed_rules') or [])
    items = []
    for rule, cands in result.semantic_hits:
        if rule['id'] in reviewed:
            continue
        items.append({'rule_id': rule['id'], 'title': rule['title'],
                      'severity': rule['severity'], 'question': rule['review']['instruction'],
                      'candidates': [c.to_dict() for c in cands]})
        if len(items) >= int(cfg['semantic_review']['max_candidates']):
            break
    if not items:
        return 'EMPTY'
    if prompt_id is not None:
        state.setdefault('reviewed_prompt_ids', []).append(str(prompt_id))
    state['reviewed_rules'] = sorted(reviewed | {i['rule_id'] for i in items})
    statelib.save(session, state, 'semantic')
    return json.dumps({'repo': root, 'items': items}, ensure_ascii=False, indent=2)
