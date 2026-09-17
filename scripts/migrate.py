#!/usr/bin/env python3
"""Move a repo from convention-guard 0.x to 1.0.

    python3 migrate.py                       # 이 레포: 무엇이 바뀌는지 보여주기만 (기본)
    python3 migrate.py --write               # 실제로 변환하고 옛 파일을 지움
    python3 migrate.py --user --write        # ~/.claude/convention-rules → ~/.claude/convention-guard/rules
    python3 migrate.py --rules-dir DIR --write   # 규칙 디렉터리 하나를 제자리에서 변환

What changes:
  .claude/convention-rules/config.yaml     → .claude/convention-guard/config.yaml (키 이름 변환)
  .claude/convention-rules/dismissed.yaml  → .claude/convention-guard/dismissed.yaml (그대로)
  .claude/convention-rules/**/*.yaml       → .claude/convention-guard/rules/** (규칙 형식 변환)

Comments are kept. Every converted rule is checked to mean exactly what it
meant before; a file that fails the check is reported and not written.

Exit codes: 0 nothing left to do or written, 1 changes pending (dry run),
2 a conversion failed verification.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import migrate  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402


def show(changes, verbose):
    for change in changes:
        label = {'convert': '변환', 'move': '이동', 'leave': '남김', 'error': '실패'}[change.action]
        target = ' → %s' % change.dst if change.dst and change.dst != change.src else ''
        print('%s  %s%s' % (label, change.src, target))
        for note in change.notes:
            print('      · %s' % note)
        for problem in change.problems:
            print('      ✗ %s' % problem)
        if verbose and change.diff():
            print(change.diff())


def main():
    parser = argparse.ArgumentParser(description='convention-guard 0.x 설정을 1.0 으로 옮깁니다')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    parser.add_argument('--user', action='store_true', help='개인 규칙 디렉터리를 옮깁니다')
    parser.add_argument('--rules-dir', help='이 디렉터리의 규칙 파일을 제자리에서 변환')
    parser.add_argument('--write', action='store_true', help='실제로 씁니다 (없으면 미리보기)')
    parser.add_argument('--quiet', action='store_true', help='diff 를 출력하지 않습니다')
    args = parser.parse_args()

    if args.rules_dir:
        base = os.path.abspath(args.rules_dir)
        changes = migrate.plan_rules_dir(base, base, source='core')
    elif args.user:
        home = os.path.expanduser('~/.claude')
        changes = migrate.plan_rules_dir(os.path.join(home, 'convention-rules'),
                                         os.path.join(home, 'convention-guard', 'rules'),
                                         source='user')
    else:
        root = git_toplevel(project_dir(args.cwd))
        changes = migrate.plan_repo(root)

    actionable = [c for c in changes if c.action in ('convert', 'move')]
    failed = [c for c in changes if c.problems]
    if not changes:
        print('옮길 것이 없습니다.')
        return 0
    show(changes, verbose=not args.quiet)

    if failed:
        print('\n검증 실패 %d건 — 해당 파일은 쓰지 않습니다. 직접 고친 뒤 다시 실행하세요.'
              % len(failed))
    if not args.write:
        print('\n미리보기입니다. 적용하려면 --write 를 붙이세요.')
        return 2 if failed else (1 if actionable else 0)

    written = migrate.apply(changes)
    print('\n%d개 파일을 썼습니다.' % len(written))
    if not args.rules_dir and not args.user:
        legacy = os.path.join(git_toplevel(project_dir(args.cwd)), '.claude', 'convention-rules')
        if os.path.isdir(legacy) and not any(files for _, _, files in os.walk(legacy)):
            for dirpath, _dirs, _files in sorted(os.walk(legacy), reverse=True):
                os.rmdir(dirpath)
            print('빈 %s 를 지웠습니다.' % legacy)
    return 2 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
