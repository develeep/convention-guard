"""Hook policy: what happens on PostToolUse and Stop.

scripts/collect.py and scripts/check.py only parse stdin and print what these
functions return. Checking itself is the pipeline's job; this module decides
*when* to check and *what to do* with the result (block, report, stay quiet).
"""

import json
import os

from . import config as configlib, log, pipeline, report, state as statelib
from .paths import git_toplevel, hook_project_dir
from .scope import ChangeScope, ScopeError

# how many locations per rule the followup compares against
PENDING_CAP = 10

WATCHED_TOOLS = {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'}


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


# ---------------------------------------------------------------- Stop

def _resolve_pending(pending, result):
    """Did the agent act on what we flagged last time? Matched per location:
    the same rule in a different file is a new finding, not the old one."""
    present = {}
    for rule, cands in result.hits:
        present.setdefault(rule['id'], set()).update((c.file, c.code_hash) for c in cands)
    keys, _ = _dismissal_keys(result.scope.root)
    resolved = []
    known = {r['id'] for r in result.rules}
    for item in pending or []:
        rid = item.get('rule_id')
        if rid not in known:
            continue
        relpath, digest = item.get('file') or '', item.get('hash') or ''
        if (rid, relpath) in keys or (rid, relpath, digest) in keys:
            resolved.append({'rule_id': rid, 'file': relpath, 'fixed': False,
                             'dismissed': True})
            continue
        hits = present.get(rid, set())
        still = (relpath, digest) in hits if digest else any(f == relpath for f, _ in hits)
        resolved.append({'rule_id': rid, 'file': relpath, 'fixed': not still})
    return resolved


def _dismissal_keys(root):
    from . import dismiss as dismisslib
    return dismisslib.load(root)


def _pending(hits):
    return [{'rule_id': rule['id'], 'file': c.file, 'line': c.line, 'hash': c.code_hash}
            for rule, cands in hits for c in cands]


def on_stop(payload):
    if not isinstance(payload, dict):
        return None
    root = git_toplevel(hook_project_dir(payload))
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg = configlib.load(root)
    state = statelib.load(session)
    pending = state.get('pending') or []

    # 1. loop guard. One block per user prompt; the turn right after our block
    # still runs, but only to measure the outcome.
    already = bool(prompt_id is not None
                   and str(prompt_id) in state.get('checked_prompt_ids', []))
    if payload.get('stop_hook_active') and pending:
        already = True
    if cfg['skip_if_question'] and not pending \
            and ends_with_question(payload.get('last_assistant_message')):
        return None

    # 2. early exit
    touched = statelib.read_touched(session)
    if not touched:
        return None
    try:
        scope = ChangeScope.from_touched(root, touched,
                                         _base_ref(root, cfg.get('base_ref')))
    except ScopeError:
        return None
    if not scope:
        # everything was reverted: the findings are gone and the turn is clean
        for item in pending:
            log.event({'event': 'followup', 'session': session,
                       'rule_id': item.get('rule_id'), 'file': item.get('file'),
                       'fixed': True})
        if pending or state.get('consecutive_blocks'):
            state.update({'pending': [], 'unresolved': [], 'consecutive_blocks': 0})
            statelib.save(session, state)
        return None

    # measured with a generous cap so an old finding is not read as fixed just
    # because newer ones pushed it out of the first few; display is capped below
    result = pipeline.run(scope, cfg, run_lint=not already, cap=PENDING_CAP)
    shown_cap = int(cfg["max_hits_per_rule"])

    # 3. measure the previous block before the per-prompt guard returns
    followups = _resolve_pending(pending, result)
    for item in followups:
        log.event(dict(item, event='followup', session=session))
    state['pending'] = []
    unresolved = set(state.get('unresolved') or [])
    unresolved |= {i['rule_id'] for i in followups if not i['fixed'] and not i.get('dismissed')}
    # a declined finding should not spend the rule's once-per-session budget
    fired = set(state.get('fired_rules') or [])
    fired -= {i['rule_id'] for i in followups if i.get('dismissed')}
    state['fired_rules'] = sorted(fired)

    if already:
        state['unresolved'] = sorted(unresolved)
        statelib.save(session, state)
        return None

    for fail in result.lint_raw:
        log.event({'event': 'lint', 'session': session, 'stack': fail.get('stack'),
                   'cmd': fail['cmd'], 'anchored': fail['anchored'],
                   'findings': len(fail.get('locations') or []),
                   'blocking': fail['cmd'] in {f['cmd'] for f in result.lint_blocking}})

    # 4. budget: a rule already raised stays quiet unless last turn's finding
    # is still there -- silence would read as "that one was fine"
    hits = [(rule, cands[:shown_cap]) for rule, cands in result.hits
            if not (cfg['once_per_session'] and rule['id'] in fired
                    and rule['id'] not in unresolved)]
    hits.sort(key=lambda h: (_rank(h[0]), h[0]['id'] not in unresolved, -len(h[1])))
    errors = [h for h in hits if h[0]['severity'] == 'error'][:int(cfg['max_rules'])]
    warns = [h for h in hits if h[0]['severity'] == 'warn'][:int(cfg['max_warns'])]
    infos = [h for h in hits if h[0]['severity'] == 'info']
    repeats = unresolved & {h[0]['id'] for h in hits}

    if prompt_id is not None:
        state.setdefault('checked_prompt_ids', []).append(str(prompt_id))
    state['unresolved'] = sorted(repeats)

    report_only = str(cfg.get('block_level', 'error')).lower() == 'report'
    streak = int(state.get('consecutive_blocks', 0))
    capped = streak >= int(cfg['max_consecutive_blocks'])
    has_blocking = bool(result.lint_blocking or errors)
    blocking = has_blocking and not report_only and not capped
    shown = (errors + warns) if blocking else []
    shown_ids = {rule['id'] for rule, _ in shown}

    for rule, cands in hits:
        log.event({'event': 'match', 'session': session, 'rule_id': rule['id'],
                   'source': rule['source'], 'severity': rule['severity'],
                   'base_severity': rule.get('base_severity'),
                   'downgraded': bool(rule.get('base_severity')
                                      and rule.get('base_severity') != rule['severity']),
                   'stacks': result.stacks.ids, 'files': [c.file for c in cands],
                   'shown': rule['id'] in shown_ids, 'blocking': blocking})

    if not blocking:
        # the streak only resets on a turn that had nothing to block: a turn the
        # cap held back is still part of the runaway loop the cap exists for
        if not has_blocking or report_only:
            state['consecutive_blocks'] = 0
        statelib.save(session, state)
        if capped and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                          '(연속 차단 %d회 상한에 걸려 차단하지 않았습니다)'
                          % (len(errors), len(result.lint_blocking), streak))
        if report_only and has_blocking:
            return notice('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                          '(block_level=report 라 차단하지 않았습니다)'
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

    state['fired_rules'] = sorted(fired | shown_ids)
    state['consecutive_blocks'] = streak + 1
    state['blocks'] = int(state.get('blocks', 0)) + 1
    state['pending'] = _pending(shown)
    statelib.save(session, state)

    reason = report.hook_reason(result.lint_blocking, result.lint_notes, errors, warns,
                                repeats)
    summary = 'convention-guard: %s%s%s' % (
        '린트 실패 %d건 ' % len(result.lint_blocking) if result.lint_blocking else '',
        'error %d건 / warn %d건' % (len(errors), len(warns)),
        ' / info %d건' % len(infos) if infos else '')
    return block(reason, summary)


def _rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)


def _base_ref(root, configured):
    from . import gitdiff
    return gitdiff.resolve_base_ref(root, configured)


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

    if not cfg.get('semantic_review'):
        return 'EMPTY'
    if prompt_id is not None and str(prompt_id) in state.get('reviewed_prompt_ids', []):
        return 'EMPTY'
    if state.get('reviews', 0) >= int(cfg['max_semantic_reviews_per_session']):
        return 'EMPTY'
    touched = statelib.read_touched(session)
    if not touched:
        return 'EMPTY'
    try:
        scope = ChangeScope.from_touched(root, touched, _base_ref(root, cfg.get('base_ref')))
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
                      'severity': rule['severity'], 'question': rule['review_prompt'],
                      'candidates': [c.to_dict() for c in cands]})
        if len(items) >= int(cfg['max_semantic_rules']):
            break
    if not items:
        return 'EMPTY'

    if prompt_id is not None:
        state.setdefault('reviewed_prompt_ids', []).append(str(prompt_id))
    state['reviews'] = state.get('reviews', 0) + 1
    state['reviewed_rules'] = sorted(reviewed | {i['rule_id'] for i in items})
    statelib.save(session, state, 'semantic')
    for item in items:
        log.event({'event': 'semantic_queued', 'session': session, 'rule_id': item['rule_id'],
                   'severity': item['severity'],
                   'files': [c['file'] for c in item['candidates']]})
    return json.dumps({'repo': root, 'items': items}, ensure_ascii=False, indent=2)

