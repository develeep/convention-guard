#!/usr/bin/env python3
"""Show what convention-guard concluded about a repo: stacks, linters, and
which rules apply and why the others do not.

    python3 detect_stack.py
    python3 detect_stack.py --cwd /path/to/repo
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, dismiss as dismisslib, pipeline, rules as rulelib  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402


def explain(root):
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    rules, notes = pipeline.load_rules(root, include_disabled=True)
    notes = list(notes) + list(cfg.notes)
    _keys, dismissals = dismisslib.load(root)

    print('repo          : %s' % root)
    print('stacks        : %s' % (', '.join(stacks.ids) or '(감지 실패)'))
    print('tags          : %s' % (', '.join(sorted(stacks.tags)) or '-'))
    print('versions      : %s' % (stacks.versions or '-'))
    print('local rules   : %s' % rulelib.local_dir(root))
    print('repo config   : %s' % (cfg.repo.get('_path') or '(없음)'))
    print('기각 기록     : %s (%d건)' % (dismisslib.path(root) if dismissals else '(없음)',
                                         len(dismissals)))
    for entry in stacks.lint:
        cmd = entry['cmd'] if isinstance(entry['cmd'], str) else ' '.join(entry['cmd'])
        print('linter        : %-58s %s' % (
            cmd, '[parse: %s → 변경 줄만 차단]' % entry['parse'] if entry.get('parse')
            else '[출력 파싱 불가 → 전체 출력으로 차단]'))
    if not stacks.lint:
        print('linter        : -')
    print()

    active = [r for r in rules if not r.get('disabled')
              and rulelib.stack_ok(r, stacks.tags, stacks.versions)]
    active_ids = {id(r) for r in active}
    print('로드된 규칙 %d개 중 이 레포에 적용 %d개' % (len(rules), len(active)))
    for rule in sorted(rules, key=lambda r: (rulelib.severity_rank(r), r['id'])):
        marker = rulelib.superseded(rule, root)
        if rule.get('disabled'):
            on = '✕'
        elif id(rule) in active_ids and not marker:
            on = '●'
        else:
            on = '○'
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
        print('  %s %-8s %-40s %-12s %s' % (on, rule['severity'], rule['id'], rule['source'],
                                            ('[' + ', '.join(extra) + ']') if extra else ''))
    if notes:
        print()
        for level, text in notes:
            print('  %-5s %s' % (level, text))
    return 0


def main():
    parser = argparse.ArgumentParser(description='스택 감지 결과와 적용 규칙을 보여줍니다')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    args = parser.parse_args()
    return explain(git_toplevel(project_dir(args.cwd)))


if __name__ == '__main__':
    sys.exit(main())
