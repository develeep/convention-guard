#!/usr/bin/env python3
"""Show what convention-guard concluded about a repo: stacks, linters, presets,
and which rules are in play and why the others are not.

    python3 detect_stack.py
    python3 detect_stack.py --cwd /path/to/repo
    python3 detect_stack.py --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, dismiss as dismisslib, pipeline, rules as rulelib  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402


def collect(root):
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, cfg, stacks)
    presets, _ = rulelib.load_presets(pipeline.default_plugin_root())
    dismissals = dismisslib.load(root)

    rows = []
    for rule in ruleset.rules:
        marker = rulelib.superseded(rule, root) if cfg['respect_supersede'] else None
        if marker:
            status, reason = 'inactive', 'superseded by %s' % marker
        elif not rulelib.stack_ok(rule, stacks.tags, stacks.versions):
            status, reason = 'inactive', '스택/버전 불일치'
        else:
            status, reason = 'active', ''
        rows.append((rule, status, reason))
    rows += [(rule, 'inactive', reason) for rule, reason in ruleset.inactive]

    return {
        'root': root,
        'mode': cfg['mode'],
        'config': cfg.repo_path,
        'stacks': stacks.ids,
        'tags': sorted(stacks.tags),
        'versions': stacks.versions,
        'linters': [{'cmd': e['cmd'] if isinstance(e['cmd'], str) else ' '.join(e['cmd']),
                     'parse': e.get('parse')} for e in stacks.lint],
        'presets': [{'name': name, 'active': name in ruleset.presets,
                     'description': presets[name].description}
                    for name in sorted(presets)],
        'rules': [{'id': rule['id'], 'severity': rule['severity'], 'source': rule['source'],
                   'status': status, 'reason': reason,
                   'semantic': bool(rule.get('review')),
                   'override': bool(rule.get('patched_from')),
                   'severity_changed': ('%s→%s' % (rule['base_severity'], rule['severity'])
                                        if rule.get('base_severity') else '')}
                  for rule, status, reason in sorted(
                      rows, key=lambda r: (r[1] != 'active', rulelib.severity_rank(r[0]),
                                           r[0]['id']))],
        'dismissals': {'path': dismisslib.path(root), 'count': len(dismissals)},
        'notes': [{'level': level, 'text': text}
                  for level, text in list(cfg.notes) + list(ruleset.notes)
                  + ([('error', dismissals.error)] if dismissals.error else [])],
    }


def render(info):
    out = ['repo        : %s' % info['root'],
           'mode        : %s' % info['mode'],
           'config      : %s' % (info['config'] or '(없음 — 기본값)'),
           'stacks      : %s' % (', '.join(info['stacks']) or '(감지 실패)'),
           'tags        : %s' % (', '.join(info['tags']) or '-'),
           'versions    : %s' % (info['versions'] or '-'),
           'dismissed   : %d건 (%s)' % (info['dismissals']['count'], info['dismissals']['path'])]
    for linter in info['linters']:
        out.append('linter      : %-56s %s' % (
            linter['cmd'], '[parse: %s → 변경 줄만 차단]' % linter['parse'] if linter['parse']
            else '[출력 파싱 불가 → 전체 출력으로 차단]'))
    if not info['linters']:
        out.append('linter      : -')
    out.append('presets     : %s' % '  '.join(
        ('●' if p['active'] else '○') + p['name'] for p in info['presets']))
    out.append('')
    active = [r for r in info['rules'] if r['status'] == 'active']
    out.append('규칙 %d개 중 적용 %d개  (● 적용 / ○ 비적용, 사유 표시)'
               % (len(info['rules']), len(active)))
    for rule in info['rules']:
        extra = [x for x in (rule['reason'], 'semantic' if rule['semantic'] else '',
                             'override' if rule['override'] else '',
                             rule['severity_changed']) if x]
        out.append('  %s %-5s %-44s %-12s %s' % (
            '●' if rule['status'] == 'active' else '○', rule['severity'], rule['id'],
            rule['source'], ('[' + ', '.join(extra) + ']') if extra else ''))
    if info['notes']:
        out.append('')
        for note in info['notes']:
            out.append('  %-5s %s' % (note['level'], note['text']))
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='스택 감지 결과와 적용 규칙을 보여줍니다')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    info = collect(git_toplevel(project_dir(args.cwd)))
    print(json.dumps(info, ensure_ascii=False, indent=2) if args.json else render(info))
    return 2 if any(n['level'] == 'error' for n in info['notes']) else 0


if __name__ == '__main__':
    sys.exit(main())
