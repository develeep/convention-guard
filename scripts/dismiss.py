#!/usr/bin/env python3
"""Record a finding as a false positive.

The hook asks the agent to judge; this is where that judgment lands. Without
it the agent's "this rule does not apply here" lived in the chat only, and the
firing log counted it as `fixed: false` -- the same value a rule the agent
simply ignored gets.

    python3 dismiss.py --rule core/php-line-too-long \\
                       --file app/Http/Controllers/OrderController.php \\
                       --line 84 --reason "체이닝을 끊으면 가독성이 더 나빠짐"

    python3 dismiss.py --rule core/js-no-console --file scripts/seed.ts --whole-file \\
                       --reason "시드 스크립트는 콘솔 출력이 인터페이스"
    python3 dismiss.py --list

The snippet, not the line number, is what gets fingerprinted: the suppression
survives edits above it and expires the moment that code itself changes.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, dismiss as dismisslib, gitdiff, log, pipeline  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402
from lib.scope import ChangeScope, ScopeError  # noqa: E402

# How many locations to look through when matching the one being dismissed.
# Far above what a hook shows, so the right line is found even in a noisy file.
SEARCH_CAP = 200


def current_candidates(root, cfg, rule_id):
    """Run the same pipeline the hook runs, so the fingerprint always agrees."""
    scope = ChangeScope.working_tree(root, gitdiff.resolve_base_ref(root, cfg['scope']['base_ref']))
    result = pipeline.run(scope, cfg, run_lint=False, cap=SEARCH_CAP, use_dismiss=False,
                          rule_filter=lambda r: r['id'] == rule_id)
    if not result.rules:
        return None, []
    cands = [c for _, found in result.hits + result.semantic_hits for c in found]
    return result.rules[0], cands


def main():
    parser = argparse.ArgumentParser(description='지적을 오탐으로 기록합니다')
    parser.add_argument('--rule', help='규칙 id (예: core/ts-no-any)')
    parser.add_argument('--file', help='레포 기준 상대 경로')
    parser.add_argument('--line', type=int, help='지적된 줄 번호')
    parser.add_argument('--reason', help='왜 이 경우는 위반이 아닌지 한 줄')
    parser.add_argument('--whole-file', action='store_true', help='이 파일 전체에서 이 규칙을 끕니다')
    parser.add_argument('--list', action='store_true', help='기록된 기각 목록')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    args = parser.parse_args()

    root = git_toplevel(project_dir(args.cwd))

    if args.list:
        _keys, entries = dismisslib.load(root)
        if not entries:
            print('기각 기록 없음 (%s)' % dismisslib.path(root))
            return 0
        print('%s  (%d건)' % (dismisslib.path(root), len(entries)))
        for entry in entries:
            print('  %-40s %s%s' % (entry.get('rule'), entry.get('file'),
                                    '' if entry.get('hash') else ' (파일 전체)'))
            print('      %s' % (entry.get('reason') or '(이유 없음)'))
        return 0

    missing = [name for name, value in (('--rule', args.rule), ('--file', args.file),
                                        ('--reason', args.reason)) if not value]
    if missing:
        print('필수 인자 누락: %s' % ', '.join(missing), file=sys.stderr)
        return 2

    relpath = args.file.replace(os.sep, '/')
    if os.path.isabs(relpath):
        relpath = os.path.relpath(relpath, root).replace(os.sep, '/')

    cfg = configlib.load(root)
    try:
        rule, cands = current_candidates(root, cfg, args.rule)
    except ScopeError as exc:
        print('검사 불가: %s' % exc, file=sys.stderr)
        return 2
    if rule is None:
        print('그런 규칙이 없습니다: %s  (detect_stack.py 로 목록 확인)' % args.rule,
              file=sys.stderr)
        return 2

    if args.whole_file:
        dismisslib.append_whole_file(root, args.rule, relpath, args.reason)
        log.event({'event': 'dismissed', 'rule_id': args.rule, 'file': relpath,
                   'scope': 'file', 'reason': args.reason})
        print('기록했습니다 — %s 에서 %s 는 더 지적하지 않습니다.' % (relpath, args.rule))
        print('  %s' % dismisslib.path(root))
        return 0

    mine = [c for c in cands if c.file == relpath]
    if args.line:
        # never fall back to another location: that would suppress code
        # nobody looked at
        mine = [c for c in mine if c.line == args.line]
    if not mine:
        print('지금 그 위치에서는 이 규칙이 걸리지 않습니다: %s %s:%s'
              % (args.rule, relpath, args.line or '-'), file=sys.stderr)
        print('코드가 이미 바뀌었다면 기각할 것이 없습니다. 파일 전체를 끄려면 '
              '--whole-file 을 쓰세요.', file=sys.stderr)
        return 1

    target = mine[0]
    digest = dismisslib.append(root, args.rule, relpath, target.snippet, args.reason,
                               line=target.line)
    log.event({'event': 'dismissed', 'rule_id': args.rule, 'file': relpath,
               'line': target.line, 'hash': digest, 'reason': args.reason})
    print('기록했습니다 — %s %s:%d (지문 %s)' % (args.rule, relpath, target.line, digest))
    print('  %s' % dismisslib.path(root))
    print('  로그: %s' % log.log_path())
    print('이 코드가 바뀌면 다시 지적됩니다. 커밋해서 팀과 공유하세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
