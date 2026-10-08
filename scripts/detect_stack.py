#!/usr/bin/env python3
"""Show what convention-guard concluded about a repo: stacks, linters, presets,
and which rules are in play and why the others are not.

    python3 detect_stack.py
    python3 detect_stack.py --cwd /path/to/repo
    python3 detect_stack.py --json
    python3 detect_stack.py --path src/a.js     # 이 경로에 어떤 규칙이 왜 적용되는지
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import (config as configlib, dismiss as dismisslib, fmt, lint, pipeline,  # noqa: E402
                 rules as rulelib)
from lib.paths import git_toplevel, project_dir, repo_relative  # noqa: E402

# why a rule does not read a path: the repo-level reasons first, then
# rules.Reach.reason's -- machine codes in --json, these words in the text
REASONS = {'disabled': '꺼짐', 'preset': '프리셋 비활성', 'superseded': '포맷터 설정이 대신함',
           'stack': '스택/버전 불일치', 'config_exclude': '설정 exclude',
           'generated': '기본 제외 (generated)', 'rule_exclude': '규칙 exclude',
           'self': 'convention-guard 자체 설정',
           'files': 'files 글롭 밖', 'not_trigger': 'when_changed 밖',
           'not_evidence': 'require_changed 밖'}
# a paired rule reads a path in two roles (rules.Reach)
ROLES = (('trigger', '트리거'), ('evidence', '증거'))


def collect(root, paths=()):
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, cfg, stacks)
    presets, _ = rulelib.load_presets(pipeline.default_plugin_root())
    dismissals = dismisslib.load(root)
    reach = rulelib.Reach.from_config(cfg, stacks)

    rows = []
    for rule in ruleset.rules:
        marker = rulelib.superseded(rule, root) if cfg['respect_supersede'] else None
        if marker:
            status, reason, code = 'inactive', 'superseded by %s' % marker, 'superseded'
        elif reach.rule_reason(rule):
            status, reason, code = 'inactive', '스택/버전 불일치', 'stack'
        else:
            status, reason, code = 'active', '', None
        rows.append((rule, status, reason, code))
    rows += [(rule, 'inactive', reason, 'preset' if reason == 'preset 비활성' else 'disabled')
             for rule, reason in ruleset.inactive]

    return {
        'root': root,
        'mode': cfg['mode'],
        'config': cfg.repo_path,
        'stacks': stacks.ids,
        'tags': sorted(stacks.tags),
        'versions': stacks.versions,
        'linters': [{'cmd': e['cmd'] if isinstance(e['cmd'], str) else ' '.join(e['cmd']),
                     'parse': e.get('parse'), 'installed': lint.binary_present(root, e)}
                    for e in stacks.lint],
        'presets': [{'name': name, 'active': name in ruleset.presets,
                     'description': presets[name].description}
                    for name in sorted(presets)],
        'rules': [{'id': rule['id'], 'severity': rule['severity'], 'source': rule['source'],
                   'status': status, 'reason': reason,
                   'semantic': bool(rule.get('review')),
                   'override': bool(rule.get('patched_from')),
                   'severity_changed': ('%s->%s' % (rule['base_severity'], rule['severity'])
                                        if rule.get('base_severity') else '')}
                  for rule, status, reason, _ in sorted(
                      rows, key=lambda r: (r[1] != 'active', rulelib.severity_rank(r[0]),
                                           r[0]['id']))],
        'paths': [explain(rows, reach, rel) for rel in paths],
        'dismissals': {'path': dismisslib.path(root), 'count': len(dismissals)},
        'notes': [{'level': level, 'text': text}
                  for level, text in list(cfg.notes) + list(ruleset.notes)
                  + ([('error', dismissals.error)] if dismissals.error else [])],
    }


def resolve(raw, root):
    """A --path the way scan.py --files reads one: from the current directory,
    else from the repo root. The file need not exist (asking about a file
    before writing it is the point); outside the repo is None."""
    path = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw))
    if not os.path.exists(path) and not os.path.isabs(raw) \
            and os.path.exists(os.path.join(root, raw)):
        path = os.path.join(root, raw)
    return repo_relative(path, root)


def explain(rows, reach, relpath):
    """Every rule against one path: does it read it, and if not, why. A
    paired rule answers per role; `applies`/`reason` are the trigger's."""
    out = []
    for rule, _status, _reason, code in sorted(rows, key=lambda r: r[0]['id']):
        row = {'id': rule['id'], 'severity': rule['severity']}
        if code is None and rule['kind'] == 'paired':
            row['roles'] = {role: reach.reason(rule, relpath, role) for role, _ in ROLES}
            code = row['roles']['trigger']
        else:
            code = code or reach.reason(rule, relpath)
        out.append(dict(row, applies=code is None, reason=code))
    return {'path': relpath, 'rules': out}


def reason_text(row):
    if 'roles' in row:
        return ' · '.join('%s: %s' % (word, REASONS.get(code, code) if code else '읽음')
                          for word, code in ((word, row['roles'][role]) for role, word in ROLES))
    return REASONS.get(row['reason'], row['reason'] or '')


def render_paths(info, style):
    blocks = []
    for entry in info['paths']:
        on = [r for r in entry['rules'] if r['applies']]
        rows = [('%s %s' % (fmt.GLYPH['on' if r['applies'] else 'off'],
                            'on' if r['applies'] else 'off'),
                 r['severity'], r['id'], reason_text(r))
                for r in sorted(entry['rules'], key=lambda r: (not r['applies'], r['id']))]
        blocks.append([fmt.section('경로 %s' % entry['path'],
                                   '%d개 중 %d개 적용' % (len(entry['rules']), len(on)),
                                   style=style)]
                      + fmt.table(['상태', '강도', '규칙', '사유'], rows, style=style))
    return blocks


def render(info, style=fmt.PLAIN):
    head = fmt.header('detect_stack', [info['root'], 'mode %s' % info['mode'],
                                       ('스택 %s' % ', '.join(info['stacks'])) if info['stacks']
                                       else '스택 감지 실패'], style=style)
    on = ', '.join(p['name'] for p in info['presets'] if p['active'])
    off = ', '.join(p['name'] for p in info['presets'] if not p['active'])

    def rel(path):
        return os.path.relpath(path, info['root']).replace(os.sep, '/')

    settings = [('config', rel(info['config']) if info['config'] else '(없음 — 기본값)'),
                ('태그', ', '.join(info['tags']) or '-'),
                ('버전', ', '.join('%s %s' % kv for kv in sorted(info['versions'].items())) or '-'),
                ('기각', '%d건 (%s)' % (info['dismissals']['count'], rel(info['dismissals']['path']))),
                ('프리셋', fmt.attrs([on and '%s %s' % (fmt.GLYPH['on'], on),
                                      off and '%s %s' % (fmt.GLYPH['off'], off)]) or '-')]
    size = max(fmt.width(k) for k, _ in settings)
    config = [fmt.section('설정', style=style)]
    config += ['  %s  %s' % (fmt.pad(k, size + 2), v) for k, v in settings]

    linters = [fmt.section('린터', style=style)] if info['linters'] else []
    for linter in info['linters']:
        if not linter['installed']:
            kind, note = 'off', '설치 안 됨 — 건너뜀'
        elif linter['parse']:
            kind, note = 'on', 'parse %s — 변경 줄만 차단' % linter['parse']
        else:
            kind, note = 'on', '출력 파싱 불가 — 전체 출력으로 차단'
        linters.append(fmt.item_head(kind, linter['cmd'], style=style))
        linters += fmt.aux('참고', note, style=style)

    active = [r for r in info['rules'] if r['status'] == 'active']
    rows = []
    for rule in info['rules']:
        kind = 'on' if rule['status'] == 'active' else 'off'
        extra = [x for x in (rule['reason'], 'semantic' if rule['semantic'] else '',
                             'override' if rule['override'] else '',
                             rule['severity_changed']) if x]
        rows.append(('%s %s' % (fmt.GLYPH[kind], kind), rule['severity'], rule['id'],
                     rule['source'], ', '.join(extra)))
    rules = [fmt.section('규칙', '%d개 중 %d개 적용' % (len(info['rules']), len(active)), style=style)]
    rules += fmt.table(['상태', '강도', '규칙', '출처', '사유'], rows, style=style)
    return style.finish(fmt.blocks([head], config, linters, rules,
                                   *render_paths(info, style)))


def main():
    parser = argparse.ArgumentParser(description='스택 감지 결과와 적용 규칙을 보여줍니다')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--path', action='append', default=[], metavar='PATH',
                        help='이 경로에 규칙마다 적용되는지와 사유 (여러 번 줄 수 있음)')
    args = parser.parse_args()
    root = git_toplevel(project_dir(args.cwd))
    paths = [resolve(p, root) for p in args.path]
    outside = [raw for raw, rel in zip(args.path, paths) if rel in (None, '.')]
    if outside:
        fmt.eprint('error', '레포 안의 경로가 아닙니다: %s' % ', '.join(outside))
        return 2
    info = collect(root, paths)
    notes = [(n['level'], n['text']) for n in info['notes']]
    if args.json:
        body = {k: v for k, v in info.items() if k != 'notes'}
        summary = {'stacks': info['stacks'], 'rules_total': len(info['rules']),
                   'rules_applicable': sum(r['status'] == 'active' for r in info['rules'])}
        print(fmt.dumps(fmt.envelope('detect-stack', summary, body, notes)))
    else:
        for level, text in notes:
            fmt.eprint(level, text)
        print(render(info, fmt.Style.for_stream()))
    return 2 if any(level == 'error' for level, _ in notes) else 0

if __name__ == '__main__':
    sys.exit(main())
