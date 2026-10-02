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
--fail-on-pending, candidates nobody judged), 2 unable to inspect (with
--require-engine: also when the structure engine was missing).
"""

import argparse
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import (autofix, config as configlib, fmt, gitdiff, pipeline,  # noqa: E402
                 report, semantic)
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
    configured = args.base_ref
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
    parser.add_argument('--require-engine', action='store_true',
                        help='구조 엔진이 없어 구조 조건을 확인하지 못했으면 종료 코드 2. '
                             'CI 에서 "확인 못 함" 을 통과로 읽지 않게 합니다 (먼저 engine.py ensure)')
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


# a full-repo audit can name hundreds of files; the hook path lists them all
UNCHECKED_LIMIT = 20


def scope_args(args):
    """The user's scope arguments, so a suggested command checks the same thing."""
    out = ['--cwd', shlex.quote(args.cwd)] if args.cwd else []
    if args.all:
        out.append('--all')
    elif args.files:
        out += ['--files'] + [shlex.quote(f) for f in args.files]
    elif args.range:
        out += ['--range', shlex.quote(args.range)]
    elif args.staged:
        out.append('--staged')
    if args.base_ref is not None:
        out += ['--base-ref', shlex.quote(args.base_ref)]
    if args.rule:
        out += ['--rule', shlex.quote(args.rule)]
    return out


def main(argv=None):
    args = parse_args(argv)
    if args.write and not args.fix:
        fmt.eprint('error', '--write 는 --fix 와 함께 씁니다')
        return EXIT_UNINSPECTABLE
    root = git_toplevel(project_dir(args.cwd))
    cfg = configlib.load(root)
    notes = list(cfg.notes)
    for level, text in cfg.notes:
        fmt.eprint(level, text)

    try:
        scope = build_scope(root, args, cfg)
    except ScopeError as exc:
        fmt.eprint('error', str(exc))
        return EXIT_UNINSPECTABLE

    rule_filter = (lambda r: args.rule in r['id']) if args.rule else None
    result = pipeline.run(scope, cfg, run_lint=not args.no_lint, cap=args.max_hits,
                          use_dismiss=not args.no_dismiss, rule_filter=rule_filter)
    for level, text in result.notes:
        if level in ('error', 'warn'):
            fmt.eprint(level, text)
            notes.append((level, text))
    load_errors = [t for lv, t in notes if lv == 'error']
    if args.rule and not result.rules:
        fmt.eprint('error', '일치하는 규칙 없음: %s' % args.rule)
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

    unread = [f for f in result.unchecked.files()
              if (result.unchecked.reason(f) or '').startswith('engine_missing:')]
    if load_errors:
        code = EXIT_UNINSPECTABLE
    elif args.require_engine and unread:
        code = EXIT_UNINSPECTABLE
        fmt.eprint('error', '구조 엔진이 없어 %d개 파일의 구조 조건을 확인하지 못했습니다 — '
                   'engine.py ensure 로 설치한 뒤 다시 실행하세요' % len(unread))
    elif args.fail_on_pending and review and (review['candidates'] or review['deferred']):
        code = EXIT_FINDINGS
    elif args.fail_on == 'never':
        code = EXIT_PASS
    else:
        # the exit code judges every finding, not just the ones --severity displayed
        worst = min([RANK[rule['severity']] for rule, _ in hits], default=9)
        code = EXIT_FINDINGS if (result.lint_blocking or worst <= RANK[args.fail_on]) \
            else EXIT_PASS

    semantic_count = sum(len(c) for _, c in result.semantic_hits)
    applied = fixed if args.write else fixes
    body = {
        'scope': {'root': root, 'label': scope.label, 'file_count': len(scope),
                  'stacks': result.stacks.ids, 'rules_total': len(result.rules),
                  'rules_applicable': len(result.applicable), 'semantic': semantic_count},
        'findings': report.findings(shown),
        'lint': {'failures': result.lint_blocking, 'notes': result.lint_notes},
        'review': review,
        'fixes': [f.to_dict() for f in applied],
        'fixes_applied': bool(args.write and fixed),
        'dismissed': result.dismissals,
        'unchecked': [{'file': f, 'reason': result.unchecked.reason(f)}
                      for f in result.unchecked.files()],
        'too_large': list(result.too_large),
    }
    pending = review['candidates'] + review['deferred'] if review else semantic_count
    summary = dict({'total': sum(counts.values())}, **counts,
                   lint_failures=len(result.lint_blocking), review_pending=pending,
                   exit_code=code)
    rest = scope_args(args)
    steps = report.scan_steps(body, lambda *flags: fmt.command('scan.py', *(list(flags) + rest)),
                              args.review)
    data = fmt.envelope('scan', summary, body, notes, steps)
    if args.json:
        print(fmt.dumps(data))
    else:
        style = fmt.Style.for_stream(sys.stdout, args.no_color)
        # an audit can touch the whole repository, so the list folds here
        unchecked = [n for n in (report.unchecked_note(result.unchecked, limit=UNCHECKED_LIMIT),
                                 report.too_large_note(result.too_large, limit=UNCHECKED_LIMIT))
                     if n]
        print(style.finish(report.render_text(data, steps, style,
                                              fix_diff=autofix.diff(applied) if args.fix else '',
                                              unchecked=unchecked)))
    return code


if __name__ == '__main__':
    sys.exit(main())
