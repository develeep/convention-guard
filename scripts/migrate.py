#!/usr/bin/env python3
"""Bring a repo's convention-guard setup up to date: 0.x layout, 3.0 rules.

    python3 migrate.py                       # 이 레포: 무엇이 바뀌는지 보여주기만 (기본)
    python3 migrate.py --write               # 실제로 변환합니다
    python3 migrate.py --user --write        # 개인 규칙 디렉터리
    python3 migrate.py --rules-dir DIR --write   # 규칙 디렉터리 하나를 제자리에서

What changes:
  .claude/convention-rules/**               → .claude/convention-guard/** (0.x 레이아웃과 형식)
  detect: 에 not_in: [comment, string]      → 주석·문자열 안의 매치를 위반으로 보지 않음 (3.0)

Both conversions are line based, so the comments people wrote in their rules
survive. A 0.x rule is checked to mean exactly what it meant before; a 3.0
condition is checked against the rule's own fixtures and against a false
positive the tool writes from them. Either check failing reports the file
instead of writing it.

`in_scope` 와 `block_empty` 는 넣지 않습니다 — 규칙이 무엇을 의도하는지 알아야
고를 수 있고, 도구는 정규식을 해석하지 않습니다.

Exit codes: 0 nothing left to do or written, 1 changes pending (dry run),
2 a conversion failed verification.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import migrate, rules as rulelib  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402

MANUAL_NOTE = ('`in_scope`·`block_empty` 는 규칙의 의도를 알아야 하므로 손으로 넣습니다 '
               '— docs/rules.md')
CACHE_NOTE = ('조건이 추가된 규칙의 저장된 AI 판정은 한 번 만료됩니다 '
              '(기각 기록은 그대로입니다)')


def show(changes, verbose):
    for change in changes:
        label = migrate.LABELS.get(change.action, change.action)
        target = ' → %s' % change.dst if change.dst and change.dst != change.src else ''
        print('%s  %s%s' % (label, change.src, target))
        for note in change.notes:
            print('      · %s' % note)
        for problem in change.problems:
            print('      ✗ %s' % problem)
        if verbose and change.diff():
            print(change.diff())


def main():
    parser = argparse.ArgumentParser(
        description='convention-guard 설정을 최신 형식으로 옮깁니다 (0.x 레이아웃, 3.0 구조 조건)')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    parser.add_argument('--user', action='store_true', help='개인 규칙 디렉터리를 옮깁니다')
    parser.add_argument('--rules-dir', help='이 디렉터리의 규칙 파일을 제자리에서 변환')
    parser.add_argument('--write', action='store_true', help='실제로 씁니다 (없으면 미리보기)')
    parser.add_argument('--quiet', action='store_true', help='diff 를 출력하지 않습니다')
    args = parser.parse_args()

    if args.rules_dir:
        base = os.path.abspath(args.rules_dir)
        changes = migrate.plan_rules_dir(base, base, source='core')
        conditions_dir, source = base, 'local'
    elif args.user:
        home = os.path.expanduser('~/.claude')
        changes = migrate.plan_rules_dir(os.path.join(home, 'convention-rules'),
                                         os.path.join(home, 'convention-guard', 'rules'),
                                         source='user')
        conditions_dir, source = rulelib.user_rules_dir(), 'user'
    else:
        root = git_toplevel(project_dir(args.cwd))
        changes = migrate.plan_repo(root)
        conditions_dir, source = rulelib.local_rules_dir(root), 'local'

    # `plan_repo` returns nothing once the 0.x layout is gone, so the 3.0 pass
    # is its own call. Only this one is timed: the diff below can be hundreds
    # of lines, and a number that moves with the terminal is not a measurement.
    started = time.perf_counter()
    condition_changes = migrate.plan_conditions(conditions_dir, source)
    elapsed = time.perf_counter() - started
    changes += condition_changes

    actionable = [c for c in changes if c.action in migrate.WRITABLE]
    # A rule that cannot carry a condition is a finished judgement, not a
    # failure: `leave` never had a file to write, so it must not push the exit
    # code to 2 on every run for ever after (NR-U4-08 vs MR-13).
    failed = [c for c in changes if c.problems and c.action != 'leave']
    if not changes:
        print('옮길 것이 없습니다.')
        return 0
    show(changes, verbose=not args.quiet)
    if any(c.action == 'enhance' and not c.problems for c in condition_changes):
        print('\n%s' % MANUAL_NOTE)
        print(CACHE_NOTE)
    if condition_changes:
        print('규칙 %d개 검사, %.1f초' % (len(condition_changes), elapsed))

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
