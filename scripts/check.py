#!/usr/bin/env python3
"""Stop hook: one convention pass over everything the agent changed.

Order of business:
  1. loop guard   -- one check per user prompt, bounded consecutive blocks
  2. followup     -- did the previous block actually get acted on?
  3. early exit   -- nothing changed / not a repo / the turn ended in a question
  4. linters      -- deterministic failures block first, on changed lines only
  5. rules        -- regex narrows candidates, the agent makes the call
  6. budget       -- at most N rules, each at most once per session

`error` blocks. `warn` never blocks on its own but rides along with a block,
so warnings reach the agent exactly when it is already going back into the code.

Two things the caller never sees but that decide whether this is trusted: the
budget is per *consecutive* block rather than per session, so the check is
still alive in a long session; and every block is measured on the next Stop,
so the firing log can tell "fixed" from "ignored" from "declined as a false
positive".
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import (dismiss as dismisslib, gitdiff, lint,  # noqa: E402
                 rules as rulelib, stack as stacklib)
from lib.engine import Context, scan  # noqa: E402
from lib.paths import (gc_old_sessions, load_state, log_event,  # noqa: E402
                       plugin_root, project_dir, remember_plugin_root,
                       save_state, user_option)

DEFAULTS = {
    'max_rules': 4,
    'max_warns': 3,
    'max_consecutive_blocks': 3,
    'once_per_session': True,
    'run_linters': True,
    'lint_timeout': 90,
    'base_ref': '',
    'skip_if_question': True,
    'max_hits_per_rule': 3,
    'respect_supersede': True,
    'max_semantic_rules': 2,
    'max_semantic_reviews_per_session': 1,
    'block_level': 'error',
    'semantic_review': False,
}

# keys that existed and no longer do -- silently ignoring them would leave a
# repo believing it had configured something
RETIRED = {'max_blocks_per_session': 'max_consecutive_blocks'}

# hook output past 10k characters is spilled to a file and replaced by a
# preview, which would hide the actual findings
REASON_LIMIT = 8000


def merged_config(cwd):
    """plugin defaults < userConfig (this install) < repo config (the team).

    The team's committed config wins, so one person cannot quietly relax a
    standard for everyone; where the repo is silent, the install preference
    applies.

    userConfig only exposes booleans/strings the plugin manifest schema
    actually supports (no enum/options field exists there), so the installer
    sets `report_only` (boolean) and it maps onto the internal `block_level`
    string that the repo's own config.yaml also uses.
    """
    cfg = dict(DEFAULTS)
    notes = []
    plugin_cfg = rulelib.load_plugin_config() or {}
    repo_cfg = rulelib.load_repo_config(cwd) or {}
    for label, source in (('플러그인 config.yaml', plugin_cfg),
                          ('레포 config.yaml', repo_cfg)):
        for key in source:
            if key in RETIRED:
                notes.append(('warn', '%s: %s 는 사라진 설정입니다 — %s 를 쓰세요'
                              % (label, key, RETIRED[key])))
    cfg.update({k: v for k, v in plugin_cfg.items() if k in DEFAULTS})
    report_only = user_option('report_only')
    if report_only is not None:
        cfg['block_level'] = 'report' if report_only else 'error'
    semantic_review = user_option('semantic_review')
    if semantic_review is not None:
        cfg['semantic_review'] = semantic_review
    cfg.update({k: v for k, v in repo_cfg.items() if k in DEFAULTS})
    return cfg, notes


def ends_with_question(message):
    text = (message or '').strip()
    if not text:
        return False
    return text.rstrip('`*_)"\'」』') .endswith(('?', '？'))


# ---------------------------------------------------------------- reporting

def dismiss_hint(rule_id=None, location=None):
    script = os.path.join(plugin_root(), 'scripts', 'dismiss.py')
    rid = rule_id or '<규칙id>'
    relpath = (location or {}).get('file', '<파일>')
    line = (location or {}).get('line', '<줄>')
    return ('python3 "%s" --rule %s --file %s --line %s --reason "<한 줄 이유>"'
            % (script, rid, relpath, line))


def build_reason(lint_failures, lint_notes, errors, warns):
    out = []
    if lint_failures:
        out.append('■ 린터 실패 — 확정 위반입니다. 먼저 고치세요.')
        for fail in lint_failures:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:20]:
                out.append('    %s' % line)
            if fail.get('carried'):
                out.append('    (같은 파일의 기존 코드에 %d건 더 있지만 이번 변경이 '
                           '아니라 차단하지 않았습니다)' % fail['carried'])
        out.append('')

    def render(title, hits):
        out.append(title)
        for hit in hits:
            rule = hit['rule']
            mark = ' ← 지난 턴에 지적했는데 그대로입니다' if hit.get('repeat') else ''
            out.append('  [%s] %s%s' % (rule['id'], rule['title'], mark))
            for loc in hit['locations']:
                out.append('    %s:%d  %s' % (loc['file'], loc['line'], loc['snippet']))
            if rule['injection']:
                for line in rule['injection'].strip().split('\n'):
                    out.append('    > %s' % line)
            out.append('')

    if errors:
        render('■ 규칙 후보 (error)', errors)
    if warns:
        render('■ 참고 (warn — 이것만으로는 차단하지 않습니다)', warns)

    if lint_notes:
        out.append('■ 참고 — 린터가 이번 변경 밖에서 찾은 것 (차단하지 않습니다)')
        for fail in lint_notes:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:5]:
                out.append('    %s' % line)
        out.append('')

    first = (errors or warns or [None])[0]
    out.append('위 규칙 후보는 정규식으로 좁힌 것이라 오탐이 있을 수 있습니다.')
    out.append('각 항목이 실제 위반인지 코드를 보고 판단하세요. 위반이면 고치세요.')
    out.append('오탐이면 고치지 말고 아래 명령으로 남기세요. 그 코드가 그대로인 동안')
    out.append('다시 지적하지 않고, 로그에는 "기각"으로 기록됩니다.')
    out.append('  %s' % dismiss_hint(first['rule']['id'] if first else None,
                                     first['locations'][0] if first else None))
    out.append('처리 후 다시 완료를 선언하면 이번 요청에 대해서는 재검사하지 않습니다.')
    text = '\n'.join(out)
    if len(text) > REASON_LIMIT:
        text = text[:REASON_LIMIT] + '\n… (이하 생략 — 위 항목부터 처리하세요)'
    return text


def emit(decision, reason=None, system_message=None):
    payload = {'hookSpecificOutput': {'hookEventName': 'Stop', 'decision': decision}}
    if reason:
        payload['hookSpecificOutput']['reason'] = reason
        payload['decision'] = decision
        payload['reason'] = reason
    if system_message:
        payload['hookSpecificOutput']['systemMessage'] = system_message
        payload['systemMessage'] = system_message
    print(json.dumps(payload, ensure_ascii=False))


def ok(system_message=None):
    if system_message:
        print(json.dumps({'systemMessage': system_message,
                          'hookSpecificOutput': {'hookEventName': 'Stop',
                                                 'systemMessage': system_message}},
                         ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- matching

def resolve_pending(pending, ctx, all_rules, cap=10):
    """Did the agent actually act on what we flagged last time?

    Matched per *location*, not per rule: the same rule hitting a different
    file is a new finding, not the old one left unfixed. A finding the agent
    declined through dismiss.py is recorded as declined, which is the whole
    point of separating it from "ignored".
    """
    by_id = {r['id']: r for r in all_rules}
    scans, resolved = {}, []
    for item in pending or []:
        rule = by_id.get(item.get('rule_id'))
        if not rule:
            continue
        rid = rule['id']
        relpath = item.get('file') or ''
        digest = item.get('hash') or ''
        if rid not in scans:
            scans[rid] = {(loc['file'], dismisslib.fingerprint(loc['snippet']))
                          for loc in scan(rule, ctx, cap)}
        if ctx.dismissed_hash(rid, relpath, digest):
            resolved.append({'rule_id': rid, 'file': relpath,
                             'fixed': False, 'dismissed': True})
            continue
        if digest:
            present = (relpath, digest) in scans[rid]
        else:
            present = any(f == relpath for f, _ in scans[rid])
        resolved.append({'rule_id': rid, 'file': relpath, 'fixed': not present})
    return resolved


def fingerprint_pending(hits):
    out = []
    for hit in hits:
        for loc in hit['locations']:
            out.append({'rule_id': hit['rule']['id'], 'file': loc['file'],
                        'line': loc['line'],
                        'hash': dismisslib.fingerprint(loc['snippet'])})
    return out


# ---------------------------------------------------------------- main

def run(payload):
    cwd = payload.get('cwd')
    root = project_dir(cwd)
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg, cfg_notes = merged_config(cwd)
    for _level, text in cfg_notes:
        print('[convention-guard] %s' % text, file=sys.stderr)

    state = load_state(session)
    pending = state.get('pending') or []

    # 1. loop guard. One block per user prompt; the turn right after our block
    # still runs, but only to measure the outcome (see `already` below).
    already = bool(prompt_id is not None
                   and str(prompt_id) in state.get('checked_prompt_ids', []))
    if payload.get('stop_hook_active') and pending:
        already = True          # works even when prompt_id is unavailable
    if cfg['skip_if_question'] and not pending \
            and ends_with_question(payload.get('last_assistant_message')):
        return ok()

    # 2. early exit
    touched = state.get('touched') or []
    if not touched or not gitdiff.is_repo(root):
        return ok()

    base_ref = gitdiff.resolve_base_ref(root, cfg.get('base_ref'))
    changed = gitdiff.added_lines(root, touched, base_ref)
    if not changed:
        if pending:             # everything was reverted: the findings are gone
            for item in pending:
                log_event({'event': 'followup', 'session': session,
                           'rule_id': item.get('rule_id'),
                           'file': item.get('file'), 'fixed': True})
            state.update({'pending': [], 'unresolved': [], 'consecutive_blocks': 0})
            save_state(session, state)
        return ok()
    new_files = gitdiff.new_files(root) & set(changed)

    detected = stacklib.detect(plugin_root(), cwd,
                               forced=(rulelib.load_repo_config(cwd) or {}).get('stacks'))
    tags, versions = detected['tags'], detected['versions']

    all_rules, notes, _repo_cfg = rulelib.load_all(cwd)
    for level, text in notes:
        if level == 'error':
            print('[convention-guard] %s' % text, file=sys.stderr)

    dismissed, _entries = dismisslib.load(root)
    ctx = Context(root, changed, new_files, tags, versions, dismissed)

    # 3. did the previous block get acted on? Measured here, on the first Stop
    # after it, which is also the turn the per-prompt guard would skip -- so
    # this has to come before that guard returns.
    followups = resolve_pending(pending, ctx, all_rules)
    for item in followups:
        log_event({'event': 'followup', 'session': session, **item})
    state['pending'] = []
    unresolved = set(state.get('unresolved') or [])
    unresolved |= {item['rule_id'] for item in followups
                   if not item['fixed'] and not item.get('dismissed')}
    # a finding the team declined should not have spent the rule's
    # once-per-session budget: a real occurrence elsewhere still deserves to
    # be reported
    fired = set(state.get('fired_rules') or [])
    fired -= {item['rule_id'] for item in followups if item.get('dismissed')}
    state['fired_rules'] = sorted(fired)

    if already:
        state['unresolved'] = sorted(unresolved)
        state['touched'] = touched
        save_state(session, state)
        return ok()

    # 4. linters first -- deterministic beats heuristic, but only on the lines
    # this change added; the rest of the file is the repo's history
    lint_failures, lint_notes = [], []
    if cfg['run_linters'] and detected['lint']:
        raw = lint.run(root, detected['lint'], list(changed.keys()),
                       timeout=int(cfg['lint_timeout']))
        lint_failures, lint_notes = lint.split_by_change(raw, ctx)
        # split_by_change rewrites an anchored failure into a narrowed copy, so
        # the command line is what identifies it here
        blocked_cmds = {fail['cmd'] for fail in lint_failures}
        for fail in raw:
            log_event({'event': 'lint', 'session': session,
                       'stack': fail.get('stack'), 'cmd': fail['cmd'],
                       'anchored': fail['anchored'],
                       'findings': len(fail.get('locations') or []),
                       'blocking': fail['cmd'] in blocked_cmds})

    # 5. rules
    hits = []
    for rule in all_rules:
        # a rule already raised is normally not raised again -- except when it was
        # raised last turn and the finding is still there. Silence would read as
        # "that one was fine". The consecutive-block cap still bounds the nagging.
        repeat = rule['id'] in unresolved
        if cfg['once_per_session'] and rule['id'] in fired and not repeat:
            continue
        if cfg['respect_supersede'] and rulelib.superseded(rule, root):
            continue
        locations = scan(rule, ctx, int(cfg['max_hits_per_rule']))
        if locations:
            hits.append({'rule': rule, 'locations': locations, 'repeat': repeat})

    # semantic rules are judged by a subagent, not here -- they never reach the
    # main agent through this path, only through the agent hook's verdict
    hits = [h for h in hits if h['rule'].get('kind') != 'semantic']
    hits.sort(key=lambda h: (rulelib.severity_rank(h['rule']),
                             not h.get('repeat'), -len(h['locations'])))
    errors = [h for h in hits if h['rule']['severity'] == 'error'][:int(cfg['max_rules'])]
    warns = [h for h in hits if h['rule']['severity'] == 'warn'][:int(cfg['max_warns'])]
    infos = [h for h in hits if h['rule']['severity'] == 'info']
    unresolved &= {h['rule']['id'] for h in hits}

    if prompt_id is not None:
        state.setdefault('checked_prompt_ids', []).append(str(prompt_id))
    state['unresolved'] = sorted(unresolved)

    # 6. budget
    report_only = str(cfg.get('block_level', 'error')).lower() == 'report'
    streak = int(state.get('consecutive_blocks', 0))
    capped = streak >= int(cfg['max_consecutive_blocks'])
    blocking = bool(lint_failures or errors) and not report_only and not capped
    shown = (errors + warns) if blocking else []

    for hit in hits:
        rule = hit['rule']
        log_event({
            'event': 'match',
            'session': session,
            'rule_id': rule['id'],
            'source': rule['source'],
            'severity': rule['severity'],
            'base_severity': rule.get('base_severity'),
            'downgraded': bool(rule.get('base_severity')
                               and rule.get('base_severity') != rule['severity']),
            'stacks': detected['stacks'],
            'files': [loc['file'] for loc in hit['locations']],
            'shown': hit in shown,
            'blocking': blocking,
        })

    if not blocking:
        # a turn that does not block breaks the streak; the cap is about
        # runaway loops, not about going quiet for the rest of the session
        state['consecutive_blocks'] = 0
        state['touched'] = touched
        save_state(session, state)
        if capped and (errors or lint_failures):
            return ok('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                      '(연속 차단 %d회 상한에 걸려 차단하지 않았습니다)'
                      % (len(errors), len(lint_failures), streak))
        if report_only and (errors or lint_failures):
            return ok('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                      '(block_level=report 라 차단하지 않았습니다)'
                      % (len(errors), len(lint_failures)))
        parts = []
        if warns:
            parts.append('warn %d건 (%s)'
                         % (len(warns), ', '.join(h['rule']['id'] for h in warns)))
        if infos:
            parts.append('info %d건' % len(infos))
        if lint_notes:
            parts.append('린터가 기존 코드에서 찾은 것 %d건' % len(lint_notes))
        if parts:
            return ok('convention-guard: %s 기록. 차단하지 않았습니다.' % ', '.join(parts))
        return ok()

    for hit in shown:
        fired.add(hit['rule']['id'])
    state['fired_rules'] = sorted(fired)
    state['consecutive_blocks'] = streak + 1
    state['blocks'] = int(state.get('blocks', 0)) + 1
    state['pending'] = fingerprint_pending(shown)
    state['touched'] = touched
    save_state(session, state)

    reason = build_reason(lint_failures, lint_notes, errors, warns)
    summary = 'convention-guard: %s%s%s' % (
        '린트 실패 %d건 ' % len(lint_failures) if lint_failures else '',
        'error %d건 / warn %d건' % (len(errors), len(warns)),
        ' / info %d건' % len(infos) if infos else '',
    )
    emit('block', reason, summary)
    return 0


def semantic_queue(payload):
    """Gate for the optional `type: agent` Stop hook.

    Prints EMPTY -- the common case -- so the subagent can bail out after one
    cheap Bash call, or a compact JSON payload naming only the candidates worth
    an LLM's attention. The point of the gate is that a judgment costs tokens
    and wall-clock on every single turn otherwise.

    Its state lives in its own file: this runs in parallel with the
    deterministic check, and sharing one JSON blob means whichever writes last
    erases the other's counters.
    """
    cwd = payload.get('cwd')
    root = project_dir(cwd)
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg, _notes = merged_config(cwd)
    state = load_state(session, 'semantic')

    if not cfg.get('semantic_review'):
        print('EMPTY')          # 사용자가 켜지 않았으면 여기서 끝
        return 0
    if prompt_id is not None and str(prompt_id) in state.get('reviewed_prompt_ids', []):
        print('EMPTY')
        return 0
    if state.get('reviews', 0) >= int(cfg['max_semantic_reviews_per_session']):
        print('EMPTY')
        return 0
    touched = load_state(session).get('touched') or []
    if not touched or not gitdiff.is_repo(root):
        print('EMPTY')
        return 0

    base_ref = gitdiff.resolve_base_ref(root, cfg.get('base_ref'))
    changed = gitdiff.added_lines(root, touched, base_ref)
    if not changed:
        print('EMPTY')
        return 0

    detected = stacklib.detect(plugin_root(), cwd,
                               forced=(rulelib.load_repo_config(cwd) or {}).get('stacks'))
    all_rules, _notes, _cfg = rulelib.load_all(cwd)
    dismissed, _entries = dismisslib.load(root)
    ctx = Context(root, changed, gitdiff.new_files(root) & set(changed),
                  detected['tags'], detected['versions'], dismissed)

    reviewed = set(state.get('reviewed_rules') or [])
    items = []
    for rule in all_rules:
        if rule.get('kind') != 'semantic' or rule['id'] in reviewed:
            continue
        locations = scan(rule, ctx, int(cfg['max_hits_per_rule']))
        if locations:
            items.append({
                'rule_id': rule['id'],
                'title': rule['title'],
                'severity': rule['severity'],
                'question': rule['review_prompt'],
                'candidates': locations,
            })
        if len(items) >= int(cfg['max_semantic_rules']):
            break

    if not items:
        print('EMPTY')
        return 0

    if prompt_id is not None:
        state.setdefault('reviewed_prompt_ids', []).append(str(prompt_id))
    state['reviews'] = state.get('reviews', 0) + 1
    state['reviewed_rules'] = sorted(reviewed | {i['rule_id'] for i in items})
    save_state(session, state, 'semantic')

    for item in items:
        log_event({'event': 'semantic_queued', 'session': session,
                   'rule_id': item['rule_id'], 'severity': item['severity'],
                   'files': [c['file'] for c in item['candidates']]})

    print(json.dumps({'repo': root, 'items': items}, ensure_ascii=False, indent=2))
    return 0


def explain(cwd=None):
    root = project_dir(cwd)
    detected = stacklib.detect(plugin_root(), cwd,
                               forced=(rulelib.load_repo_config(cwd) or {}).get('stacks'))
    all_rules, notes, cfg = rulelib.load_all(cwd, include_disabled=True)
    _merged, cfg_notes = merged_config(cwd)
    notes = list(notes) + list(cfg_notes)
    _keys, dismissals = dismisslib.load(root)
    print('repo          : %s' % root)
    print('stacks        : %s' % (', '.join(detected['stacks']) or '(감지 실패)'))
    print('tags          : %s' % (', '.join(sorted(detected['tags'])) or '-'))
    print('versions      : %s' % (detected['versions'] or '-'))
    print('local rules   : %s' % rulelib.local_dir(cwd))
    print('repo config   : %s' % (cfg.get('_path') or '(없음)'))
    print('기각 기록     : %s (%d건)'
          % (dismisslib.path(root) if dismissals else '(없음)', len(dismissals)))
    for entry in detected['lint']:
        cmd = entry['cmd'] if isinstance(entry['cmd'], str) else ' '.join(entry['cmd'])
        print('linter        : %-58s %s' % (
            cmd, '[parse: %s → 변경 줄만 차단]' % entry['parse'] if entry.get('parse')
            else '[출력 파싱 불가 → 전체 출력으로 차단]'))
    if not detected['lint']:
        print('linter        : -')
    print()
    active = [r for r in all_rules
              if not r.get('disabled') and (not r.get('stack') or '*' in r['stack']
                                            or set(r['stack']) & set(detected['tags']))]
    active_ids = {id(r) for r in active}
    print('로드된 규칙 %d개 중 이 레포에 적용 %d개' % (len(all_rules), len(active)))
    for rule in sorted(all_rules, key=lambda r: (rulelib.severity_rank(r), r['id'])):
        marker = rulelib.superseded(rule, root)
        on = '✕' if rule.get('disabled') else ('●' if id(rule) in active_ids and not marker
                                               else '○')
        extra = []
        if rule.get('disabled'):
            extra.append('disabled by %s' % (rule.get('disabled_by') or rule['source']))
        if marker:
            extra.append('superseded by %s' % marker)
        if rule.get('patched_from'):
            extra.append('override')
        if rule.get('severity_by'):
            extra.append('severity←config')
        if rule.get('base_severity') and rule['base_severity'] != rule['severity']:
            extra.append('%s→%s' % (rule['base_severity'], rule['severity']))
        print('  %s %-8s %-40s %-12s %s' % (
            on, rule['severity'], rule['id'], rule['source'],
            ('[' + ', '.join(extra) + ']') if extra else ''))
    if notes:
        print()
        for level, text in notes:
            print('  %-5s %s' % (level, text))
    return 0


def main():
    remember_plugin_root()
    if '--explain' in sys.argv:
        return explain()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        if '--semantic-queue' in sys.argv:
            print('EMPTY')
        return 0
    if '--semantic-queue' in sys.argv:
        try:
            return semantic_queue(payload)
        except Exception as exc:
            print('EMPTY')
            print('[convention-guard] %s' % exc, file=sys.stderr)
            return 0
    gc_old_sessions()
    try:
        return run(payload)
    except Exception as exc:  # never break the agent on our own bug
        print('[convention-guard] 내부 오류: %s' % exc, file=sys.stderr)
        return 0


if __name__ == '__main__':
    sys.exit(main())
