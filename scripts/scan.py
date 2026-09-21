#!/usr/bin/env python3
"""Run the convention rules on demand -- no hook, no session state.

Same pipeline as the Stop hook, so a manual run and an automatic one never
disagree. Useful before opening a PR, in CI, and for auditing a repo before
turning the hook on.

    python3 scan.py                        # 워킹 트리 (기본)
    python3 scan.py --staged               # 스테이지된 것만
    python3 scan.py --range main..HEAD     # 브랜치 변경분
    python3 scan.py --files a.php b.php    # 지정 파일 전체
    python3 scan.py --all                  # 레포 전수조사 (레거시 감사)
    python3 scan.py --json                 # 기계가 읽을 형태
    python3 scan.py --fail-on warn         # CI 종료 코드 기준

Exit codes: 0 pass, 1 findings at or above --fail-on (or, with
--fail-on-pending, candidates nobody judged), 2 unable to inspect.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import autofix, config as configlib, gitdiff, pipeline, report, semantic  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402
from lib.scope import ChangeScope, ScopeError  # noqa: E402

RANK = {'error': 0, 'warn': 1, 'info': 2}
EXIT_PASS, EXIT_FINDINGS, EXIT_UNINSPECTABLE = 0, 1, 2


def build_scope(root, args, cfg):
    if args.all:
        return ChangeScope.everything(root)
    if args.files:
        return ChangeScope.files(root, args.files)
    if args.range:
        return ChangeScope.git_range(root, args.range)
    if args.staged:
        return ChangeScope.staged(root)
    configured = args.base_ref if args.base_ref is not None else cfg['scope']['base_ref']
    base_ref = gitdiff.resolve_base_ref(root, configured)
    if configured and configured != 'auto' and not base_ref:
        raise ScopeError('base ref 를 찾을 수 없습니다: %s' % configured)
    return ChangeScope.working_tree(root, base_ref)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='컨벤션 규칙을 훅 없이 실행합니다')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--staged', action='store_true', help='스테이지된 변경만')
    group.add_argument('--range', help='git 리비전 범위 (예: main..HEAD)')
    group.add_argument('--files', nargs='+', help='지정한 파일 전체를 검사')
    group.add_argument('--all', action='store_true',
                       help='레포 전수조사. 레거시 감사용이며 결과가 많습니다')
    parser.add_argument('--severity', choices=['error', 'warn', 'info'], default='info',
                        help='이 강도 이상만 출력 (종료 코드에는 영향 없음)')
    parser.add_argument('--rule', help='이 규칙 하나만 실행 (id 또는 일부 문자열)')
    parser.add_argument('--no-lint', action='store_true', help='린터 위임 생략')
    parser.add_argument('--json', action='store_true', help='JSON 출력')
    parser.add_argument('--no-color', action='store_true')
    parser.add_argument('--max-hits', type=int, default=10, help='규칙당 최대 위치 수')
    parser.add_argument('--fail-on', choices=['error', 'warn', 'info', 'never'],
                        default='error', help='이 강도가 있으면 종료 코드 1')
    parser.add_argument('--base-ref', default=None,
                        help="비교 기준 ref. 'auto' 면 기본 브랜치와의 merge-base")
    parser.add_argument('--no-dismiss', action='store_true',
                        help='dismissed.yaml 의 기각 기록을 무시하고 전부 봅니다')
    parser.add_argument('--fix', action='store_true',
                        help='fix.auto 가 있는 규칙의 자동 수정안을 보여줍니다 (--write 로 적용)')
    parser.add_argument('--write', action='store_true', help='--fix 의 수정안을 실제로 적용')
    parser.add_argument('--review', action='store_true',
                        help='semantic 규칙 후보를 판정 배치로 만들고, 캐시된 VIOLATION 판정을 결과에 포함')
    parser.add_argument('--fail-on-pending', action='store_true',
                        help='--review 에서 판정이 남은 후보가 있으면 종료 코드 1. '
                             '리뷰어를 돌릴 수 없는 CI 가 "판정 못 함"을 통과로 읽지 않게 합니다')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    return parser.parse_args(argv)


def review_semantic(result, cfg):
    """(extra findings, review info) for --review: cached VIOLATIONs become
    findings, candidates without a verdict become a batch for the reviewer."""
    triage = semantic.triage(result, cfg)
    grouped = {}
    for rule, cand, _verdict in triage.violations:
        grouped.setdefault(rule['id'], (rule, []))[1].append(cand)
    path, items, deferred = semantic.build_batch(result.scope.root, None, triage.pending, cfg,
                                                 label='scan')
    info = {'batch': path, 'candidates': len(items), 'deferred': len(deferred),
            'cached_violations': len(triage.violations), 'cleared': len(triage.cleared)}
    return list(grouped.values()), info


def main(argv=None):
    args = parse_args(argv)
    if args.write and not args.fix:
        print('--write 는 --fix 와 함께 씁니다', file=sys.stderr)
        return EXIT_UNINSPECTABLE
    root = git_toplevel(project_dir(args.cwd))
    cfg = configlib.load(root)
    for level, text in cfg.notes:
        print('[%s] %s' % (level, text), file=sys.stderr)

    try:
        scope = build_scope(root, args, cfg)
    except ScopeError as exc:
        print('검사 불가: %s' % exc, file=sys.stderr)
        return EXIT_UNINSPECTABLE

    rule_filter = (lambda r: args.rule in r['id']) if args.rule else None
    result = pipeline.run(scope, cfg, run_lint=not args.no_lint, cap=args.max_hits,
                          use_dismiss=not args.no_dismiss, rule_filter=rule_filter)
    for level, text in result.notes:
        if level in ('error', 'warn'):
            print('[%s] %s' % (level, text), file=sys.stderr)
    load_errors = [t for lv, t in list(cfg.notes) + list(result.notes) if lv == 'error']
    if args.rule and not result.rules:
        print('일치하는 규칙 없음: %s' % args.rule, file=sys.stderr)
        return EXIT_UNINSPECTABLE

    fixes, fixed = [], []
    if args.fix and not load_errors:
        fixes = autofix.plan(root, result.hits)
        if args.write and fixes:
            fixed = autofix.apply(root, fixes)
            # re-check what is left, from a fresh scope: the files changed
            scope = build_scope(root, args, cfg)
            result = pipeline.run(scope, cfg, run_lint=not args.no_lint, cap=args.max_hits,
                                  use_dismiss=not args.no_dismiss, rule_filter=rule_filter)

    hits, review = list(result.hits), None
    if args.review and result.semantic_hits:
        extra, review = review_semantic(result, cfg)
        hits += extra

    counts = {'error': 0, 'warn': 0, 'info': 0}
    for rule, _ in hits:
        counts[rule['severity']] = counts.get(rule['severity'], 0) + 1
    threshold = RANK[args.severity]
    shown = [h for h in hits if RANK.get(h[0]['severity'], 9) <= threshold]
    payload = {
        'head': {
            'root': root,
            'label': scope.label,
            'stacks': result.stacks.ids,
            'file_count': len(scope),
            'rules_total': len(result.rules),
            'rules_applicable': len(result.applicable),
            'semantic': sum(len(c) for _, c in result.semantic_hits),
            'lint_failures': result.lint_blocking,
            'lint_notes': result.lint_notes,
            'dismissed': result.dismissals,
            'review': review,
            'fixes': [f.to_dict() for f in (fixed if args.write else fixes)],
            'fixes_applied': bool(args.write and fixed),
        },
        'counts': counts,
        'findings': report.findings(shown),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        color = not (args.no_color or not sys.stdout.isatty())
        print(report.render_text(payload, report.Palette(color)))
        if args.fix:
            if args.write:
                print('\n자동 수정 %d건을 적용했습니다 (위 결과는 적용 후 남은 것)' % len(fixed))
            else:
                print('\n자동 수정 가능 %d건 — 적용하려면 --write 를 붙이세요' % len(fixes))
            if fixed or fixes:
                print(autofix.diff(fixed if args.write else fixes))
        if review and review['batch']:
            print('\n심층 판정 대기 후보 %d건%s — convention-guard:convention-reviewer 에이전트에게 전달하세요:'
                  % (review['candidates'],
                     ' (예산 초과로 %d건 미룸)' % review['deferred'] if review['deferred'] else ''))
            print('  python3 "%s" show "%s"' % (report.script_path('review.py'), review['batch']))

    if load_errors:
        return EXIT_UNINSPECTABLE
    if args.fail_on_pending and review and (review['candidates'] or review['deferred']):
        return EXIT_FINDINGS
    if args.fail_on == 'never':
        return EXIT_PASS
    # the exit code judges every finding, not just the ones --severity displayed
    worst = min([RANK[rule['severity']] for rule, _ in hits], default=9)
    return EXIT_FINDINGS if (result.lint_blocking or worst <= RANK[args.fail_on]) else EXIT_PASS


if __name__ == '__main__':
    sys.exit(main())
