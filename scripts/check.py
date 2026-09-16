#!/usr/bin/env python3
"""Stop hook: one convention pass over everything the agent changed.

Order of business:
  1. loop guard   -- one check per user prompt, hard cap per session
  2. early exit   -- nothing changed / not a repo / the turn ended in a question
  3. linters      -- deterministic failures block first; no regex work is done
  4. rules        -- regex narrows candidates, the agent makes the call
  5. budget       -- at most N rules, each at most once per session

`error` blocks. `warn` never blocks on its own but rides along with a block,
so warnings reach the agent exactly when it is already going back into the code.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import engine, gitdiff, lint, rules as rulelib, stack as stacklib  # noqa: E402
from lib.engine import Context, scan  # noqa: E402
from lib.paths import (gc_old_sessions, load_state, log_event,  # noqa: E402
                       plugin_root, project_dir, save_state, user_option)

DEFAULTS = {
    'max_rules': 4,
    'max_warns': 3,
    'max_blocks_per_session': 2,
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
    cfg.update({k: v for k, v in (rulelib.load_plugin_config() or {}).items()
                if k in DEFAULTS})
    report_only = user_option('report_only')
    if report_only is not None:
        cfg['block_level'] = 'report' if report_only else 'error'
    semantic_review = user_option('semantic_review')
    if semantic_review is not None:
        cfg['semantic_review'] = semantic_review
    repo = rulelib.load_repo_config(cwd) or {}
    cfg.update({k: v for k, v in repo.items() if k in DEFAULTS})
    return cfg


def ends_with_question(message):
    text = (message or '').strip()
    if not text:
        return False
    return text.rstrip('`*_)"\'」』') .endswith(('?', '？'))


# ---------------------------------------------------------------- reporting

def build_reason(lint_failures, errors, warns):
    out = []
    if lint_failures:
        out.append('■ 린터 실패 — 확정 위반입니다. 먼저 고치세요.')
        for fail in lint_failures:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:20]:
                out.append('    %s' % line)
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

    out.append('위 규칙 후보는 정규식으로 좁힌 것이라 오탐이 있을 수 있습니다.')
    out.append('각 항목이 실제 위반인지 코드를 보고 판단하세요. 위반이면 고치고,')
    out.append('오탐이면 고치지 말고 왜 해당하지 않는지 한 줄로만 남기세요.')
    out.append('처리 후 다시 완료를 선언하면 이번 요청에 대해서는 재검사하지 않습니다.')
    return '\n'.join(out)


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

def resolve_pending(pending, ctx, all_rules):
    """Did the agent actually act on what we flagged last time?"""
    by_id = {r['id']: r for r in all_rules}
    resolved = []
    for item in pending or []:
        rule = by_id.get(item.get('rule_id'))
        if not rule:
            continue
        resolved.append({'rule_id': rule['id'], 'fixed': not scan(rule, ctx, 1)})
    return resolved


# ---------------------------------------------------------------- main

def run(payload):
    cwd = payload.get('cwd')
    root = project_dir(cwd)
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg = merged_config(cwd)

    state = load_state(session)

    # 1. loop guard -- the single most important line in this file
    if prompt_id is not None and str(prompt_id) in state.get('checked_prompt_ids', []):
        return ok()
    if state.get('blocks', 0) >= int(cfg['max_blocks_per_session']):
        return ok()
    if cfg['skip_if_question'] and ends_with_question(payload.get('last_assistant_message')):
        return ok()

    # 2. early exit
    touched = state.get('touched') or []
    if not touched:
        return ok()
    if not gitdiff.is_repo(root):
        return ok()

    base_ref = gitdiff.resolve_base_ref(root, cfg.get('base_ref'))
    changed = gitdiff.added_lines(root, touched, base_ref)
    if not changed:
        return ok()
    new_files = gitdiff.untracked(root) & set(changed)

    detected = stacklib.detect(plugin_root(), cwd,
                               forced=(rulelib.load_repo_config(cwd) or {}).get('stacks'))
    tags, versions = detected['tags'], detected['versions']

    all_rules, notes, _repo_cfg = rulelib.load_all(cwd)
    for level, text in notes:
        if level == 'error':
            print('[convention-guard] %s' % text, file=sys.stderr)

    ctx = Context(root, changed, new_files, tags, versions)

    # did the previous block get acted on?
    followups = resolve_pending(state.get('pending'), ctx, all_rules)
    for item in followups:
        log_event({'event': 'followup', 'session': session, **item})
    unresolved = {item['rule_id'] for item in followups if not item['fixed']}

    # 3. linters first -- deterministic beats heuristic
    lint_failures = []
    if cfg['run_linters'] and detected['lint']:
        lint_failures = lint.run(root, detected['lint'], list(changed.keys()),
                                 timeout=int(cfg['lint_timeout']))

    # 4. rules
    fired = set(state.get('fired_rules') or [])
    hits = []
    for rule in all_rules:
        # a rule already raised is normally not raised again -- except when it was
        # raised last turn and the finding is still there. Silence would read as
        # "that one was fine". The session block cap still bounds the nagging.
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

    if prompt_id is not None:
        state.setdefault('checked_prompt_ids', []).append(str(prompt_id))

    report_only = str(cfg.get('block_level', 'error')).lower() == 'report'
    blocking = bool(lint_failures or errors) and not report_only
    shown = errors + (warns if blocking else [])

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
        state['touched'] = touched
        save_state(session, state)
        if report_only and (errors or lint_failures):
            return ok('convention-guard: error %d건 / 린트 실패 %d건 기록 '
                      '(block_level=report 라 차단하지 않았습니다)'
                      % (len(errors), len(lint_failures)))
        if warns or infos:
            parts = []
            if warns:
                parts.append('warn %d건 (%s)'
                             % (len(warns), ', '.join(h['rule']['id'] for h in warns)))
            if infos:
                parts.append('info %d건' % len(infos))
            return ok('convention-guard: %s 기록. 차단하지 않았습니다.' % ', '.join(parts))
        return ok()

    for hit in shown:
        fired.add(hit['rule']['id'])
    state['fired_rules'] = sorted(fired)
    state['blocks'] = state.get('blocks', 0) + 1
    state['pending'] = [{'rule_id': h['rule']['id']} for h in shown]
    save_state(session, state)

    reason = build_reason(lint_failures, errors, warns if blocking else [])
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
    """
    cwd = payload.get('cwd')
    root = project_dir(cwd)
    session = payload.get('session_id')
    prompt_id = payload.get('prompt_id') or payload.get('turn_number')
    cfg = merged_config(cwd)
    state = load_state(session)

    if not cfg.get('semantic_review'):
        print('EMPTY')          # 사용자가 켜지 않았으면 여기서 끝
        return 0
    if prompt_id is not None and str(prompt_id) in state.get('reviewed_prompt_ids', []):
        print('EMPTY')
        return 0
    if state.get('reviews', 0) >= int(cfg['max_semantic_reviews_per_session']):
        print('EMPTY')
        return 0
    touched = state.get('touched') or []
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
    ctx = Context(root, changed, gitdiff.untracked(root) & set(changed),
                  detected['tags'], detected['versions'])

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
    save_state(session, state)

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
    print('repo          : %s' % root)
    print('stacks        : %s' % (', '.join(detected['stacks']) or '(감지 실패)'))
    print('tags          : %s' % (', '.join(sorted(detected['tags'])) or '-'))
    print('versions      : %s' % (detected['versions'] or '-'))
    print('local rules   : %s' % rulelib.local_dir(cwd))
    print('repo config   : %s' % (cfg.get('_path') or '(없음)'))
    print('linters       : %s' % (', '.join(e['cmd'] if isinstance(e['cmd'], str)
                                            else ' '.join(e['cmd'])
                                            for e in detected['lint']) or '-'))
    print()
    active = [r for r in all_rules
              if not r.get('disabled') and (not r.get('stack') or '*' in r['stack']
                                            or set(r['stack']) & set(detected['tags']))]
    print('로드된 규칙 %d개 중 이 레포에 적용 %d개' % (len(all_rules), len(active)))
    for rule in sorted(all_rules, key=lambda r: (rulelib.severity_rank(r), r['id'])):
        marker = rulelib.superseded(rule, root)
        on = '✕' if rule.get('disabled') else ('●' if rule in active and not marker
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
