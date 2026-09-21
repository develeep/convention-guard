#!/usr/bin/env python3
"""Record a finding as a false positive.

The hook asks the agent to judge; this is where that judgment lands. Without
it "this rule does not apply here" lived in the chat only, and the tuning log
could not tell a declined finding from an ignored one.

    python3 dismiss.py --rule core/php-line-too-long --file app/Http/OrderController.php \\
                       --line 84 --reason "체이닝을 끊으면 가독성이 더 나빠짐" --by agent
    python3 dismiss.py --key core/php-line-too-long:app/Http/OrderController.php:6f1c93ab24 \\
                       --reason "..."
    python3 dismiss.py --rule core/js-no-console --file scripts/seed.ts --whole-file \\
                       --reason "시드 스크립트는 콘솔 출력이 인터페이스"
    python3 dismiss.py --list

--rule/--file/--line finds the location with the same pipeline the hook runs,
so the fingerprint always agrees. --key takes the fingerprint as given
(rule:file:hash, as convention-guard prints it) without re-scanning.

Exit codes: 0 recorded (or already recorded), 1 nothing to dismiss at that
location, 2 invalid input or an unreadable dismissed.yaml.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, dismiss as dismisslib, gitdiff, log, pipeline  # noqa: E402
from lib.candidate import parse_key  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402
from lib.scope import ChangeScope, ScopeError  # noqa: E402

# How many locations to look through when matching the one being dismissed.
# Far above what a hook shows, so the right line is found even in a noisy file.
SEARCH_CAP = 200


def _candidates(scope, cfg, rule_id):
    result = pipeline.run(scope, cfg, run_lint=False, cap=SEARCH_CAP, use_dismiss=False,
                          rule_filter=lambda r: r['id'] == rule_id)
    if not result.rules:
        return None, []
    return result.rules[0], [c for _, found in result.hits + result.semantic_hits for c in found]


def current_candidates(root, cfg, rule_id, relpath=None):
    """(rule or None, [Candidate]) from the same pipeline the hook runs.

    The change scope first, because that is what the hook flagged. Falling back
    to the whole file matters for the audit path: `scan.py --all` reports
    findings in code this change never touched, and those were impossible to
    dismiss -- the change scope cannot see them, and the `--key` form the docs
    point at is only ever printed by the hook, never by scan.py.
    """
    base = gitdiff.resolve_base_ref(root, cfg['scope']['base_ref'])
    rule, found = _candidates(ChangeScope.working_tree(root, base), cfg, rule_id)
    if found or not relpath:
        return rule, found
    try:
        whole = ChangeScope.files(root, [relpath])
    except ScopeError:
        return rule, found
    if not whole:                   # binary, too large, or an ignored extension
        return rule, found
    return _candidates(whole, cfg, rule_id)


def rule_exists(root, cfg, rule_id):
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, cfg, stacks)
    return any(r['id'] == rule_id for r in ruleset.rules) or \
        any(r['id'] == rule_id for r, _ in ruleset.inactive)


def show_list(root):
    recorded = dismisslib.load(root)
    if recorded.error:
        print(recorded.error, file=sys.stderr)
        return 2
    if not recorded.entries:
        print('기각 기록 없음 (%s)' % recorded.path)
        return 0
    print('%s  (%d건)' % (recorded.path, len(recorded)))
    for entry in recorded.entries:
        scope = '%s:%s' % (entry.get('file'), entry.get('hash')) if entry.get('hash') \
            else '%s (파일 전체)' % entry.get('file')
        print('  %-40s %s  [%s, %s]' % (entry.get('rule'), scope, entry.get('by') or '?',
                                        entry.get('at') or '?'))
        print('      %s' % (entry.get('reason') or '(이유 없음)'))
    return 0


def record(root, rule_id, relpath, reason, by, digest=None, snippet=None, line=None):
    try:
        added = dismisslib.add(root, rule_id, relpath, reason, digest=digest, snippet=snippet,
                               line=line, by=by)
    except dismisslib.DismissalError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not added:
        print('이미 기록돼 있습니다 — %s %s%s' % (rule_id, relpath, ':' + digest if digest else ''))
        return 0
    log.event({'event': 'dismissed', 'repo': root, 'rule_id': rule_id, 'file': relpath,
               'line': line, 'hash': digest, 'scope': 'code' if digest else 'file',
               'reason': reason, 'by': by})
    where = '%s:%s (지문 %s)' % (relpath, line, digest) if digest and line else \
        ('%s (지문 %s)' % (relpath, digest) if digest else '%s 파일 전체' % relpath)
    print('기록했습니다 — %s %s' % (rule_id, where))
    print('  %s' % dismisslib.path(root))
    print('이 코드가 바뀌면 다시 지적됩니다. 커밋해서 팀과 공유하세요.' if digest else
          '이 파일에서는 이 규칙을 더 지적하지 않습니다. 커밋해서 팀과 공유하세요.')
    return 0


def main():
    parser = argparse.ArgumentParser(description='지적을 오탐으로 기록합니다')
    parser.add_argument('--rule', help='규칙 id (예: core/ts-no-any)')
    parser.add_argument('--file', help='레포 기준 상대 경로')
    parser.add_argument('--line', type=int, help='지적된 줄 번호')
    parser.add_argument('--key', help='규칙id:파일:지문 — 다시 검사하지 않고 그대로 기록')
    parser.add_argument('--reason', help='왜 이 경우는 위반이 아닌지 한 줄')
    parser.add_argument('--by', choices=['agent', 'human'], default='human',
                        help='누가 판단했는지 (에이전트는 agent)')
    parser.add_argument('--whole-file', action='store_true', help='이 파일 전체에서 이 규칙을 끕니다')
    parser.add_argument('--list', action='store_true', help='기록된 기각 목록')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    args = parser.parse_args()

    root = git_toplevel(project_dir(args.cwd))
    if args.list:
        return show_list(root)

    if args.key:
        try:
            args.rule, args.file, digest = parse_key(args.key)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        digest = None
    missing = [name for name, value in (('--rule', args.rule), ('--file', args.file),
                                        ('--reason', args.reason)) if not value]
    if missing:
        print('필수 인자 누락: %s' % ', '.join(missing), file=sys.stderr)
        return 2

    relpath = args.file.replace(os.sep, '/')
    if os.path.isabs(relpath):
        relpath = os.path.relpath(relpath, root).replace(os.sep, '/')
    cfg = configlib.load(root)

    if args.key or args.whole_file:
        if not rule_exists(root, cfg, args.rule):
            print('그런 규칙이 없습니다: %s  (detect_stack.py 로 목록 확인)' % args.rule,
                  file=sys.stderr)
            return 2
        return record(root, args.rule, relpath, args.reason, args.by,
                      digest=None if args.whole_file else digest)

    try:
        rule, cands = current_candidates(root, cfg, args.rule, relpath)
    except ScopeError as exc:
        print('검사 불가: %s' % exc, file=sys.stderr)
        return 2
    if rule is None:
        print('그런 규칙이 없습니다: %s  (detect_stack.py 로 목록 확인)' % args.rule,
              file=sys.stderr)
        return 2
    mine = [c for c in cands if c.file == relpath]
    if args.line:
        # never fall back to another location: that would suppress code nobody looked at
        mine = [c for c in mine if c.line == args.line]
    if not mine:
        print('지금 그 위치에서는 이 규칙이 걸리지 않습니다: %s %s:%s'
              % (args.rule, relpath, args.line or '-'), file=sys.stderr)
        print('코드가 이미 바뀌었다면 기각할 것이 없습니다. 파일 전체를 끄려면 '
              '--whole-file 을 쓰세요.', file=sys.stderr)
        return 1
    if len(mine) > 1 and not args.line:
        print('이 파일에 %d곳이 걸립니다. --line 으로 하나를 고르거나 --whole-file 을 쓰세요:'
              % len(mine), file=sys.stderr)
        for cand in mine[:10]:
            print('  %s:%d  %s' % (cand.file, cand.line, cand.snippet), file=sys.stderr)
        return 2
    target = mine[0]
    return record(root, args.rule, relpath, args.reason, args.by, digest=target.code_hash,
                  snippet=target.snippet, line=target.line)


if __name__ == '__main__':
    sys.exit(main())
