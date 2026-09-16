#!/usr/bin/env python3
"""Run the convention rules on demand -- no hook, no session state.

Same engine as the Stop hook, so a manual run and an automatic one never
disagree. Useful before opening a PR, in CI, and for auditing a repo before
turning the hook on.

    python3 scan.py                        # 워킹 트리 (기본)
    python3 scan.py --staged               # 스테이지된 것만
    python3 scan.py --range main..HEAD     # 브랜치 변경분
    python3 scan.py --files a.php b.php    # 지정 파일 전체
    python3 scan.py --all                  # 레포 전수조사 (레거시 감사)
    python3 scan.py --json                 # 기계가 읽을 형태
    python3 scan.py --fail-on warn         # CI 종료 코드 기준
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import (dismiss as dismisslib, engine, gitdiff, lint,  # noqa: E402
                 rules as rulelib, stack as stacklib)
from lib.paths import plugin_root, project_dir  # noqa: E402

RANK = {'error': 0, 'warn': 1, 'info': 2}
COLOR = {'error': '\033[31m', 'warn': '\033[33m', 'info': '\033[36m'}
DIM, BOLD, RESET = '\033[2m', '\033[1m', '\033[0m'


def _plain():
    global COLOR, DIM, BOLD, RESET
    COLOR = {k: '' for k in COLOR}
    DIM = BOLD = RESET = ''


def _git(root, args):
    try:
        proc = subprocess.run(['git'] + args, cwd=root, capture_output=True,
                              text=True, errors='replace', timeout=30)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ''


# ---------------------------------------------------------------- collecting

def _diff_lines(root, diff_args, paths):
    """{relpath: [(lineno, text)]} from one batched git diff."""
    return gitdiff.diff_lines(root, paths, diff_args)


def _whole(root, paths):
    result = {}
    for rel in paths:
        lines = gitdiff._whole_file(root, rel)
        if lines:
            result[rel] = lines
    return result


def gather(root, args, all_rules):
    """Returns (changed, new_files, label)."""
    if args.all:
        globs = set()
        for rule in all_rules:
            globs.update(rule.get('files') or [])
        code, out = _git(root, ['ls-files'])
        tracked = out.splitlines() if code == 0 else []
        if globs:
            tracked = [f for f in tracked if rulelib._match_any(list(globs), f)]
        # every file is treated as new so absence rules apply -- that is the
        # point of an audit, and it is opt-in precisely because it is noisy
        return _whole(root, tracked), set(tracked), '전수조사 (%d개 파일)' % len(tracked)

    if args.files:
        rels = []
        for raw in args.files:
            path = os.path.abspath(raw)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            if not rel.startswith('..'):
                rels.append(rel)
        return _whole(root, rels), set(rels), '지정 파일 %d개' % len(rels)

    if args.range:
        code, out = _git(root, ['diff', '--name-only', args.range])
        paths = out.splitlines() if code == 0 else []
        code, out = _git(root, ['diff', '--name-only', '--diff-filter=A', args.range])
        new = set(out.splitlines()) if code == 0 else set()
        return _diff_lines(root, [args.range], paths), new, args.range

    if args.staged:
        code, out = _git(root, ['diff', '--cached', '--name-only'])
        paths = out.splitlines() if code == 0 else []
        code, out = _git(root, ['diff', '--cached', '--name-only', '--diff-filter=A'])
        new = set(out.splitlines()) if code == 0 else set()
        return _diff_lines(root, ['--cached'], paths), new, '스테이지된 변경'

    code, out = _git(root, ['diff', 'HEAD', '--name-only'])
    paths = out.splitlines() if code == 0 else []
    fresh = gitdiff.new_files(root)
    changed = gitdiff.added_lines(root, sorted(set(paths) | fresh),
                                  gitdiff.resolve_base_ref(root, args.base_ref))
    return changed, fresh & set(changed), '워킹 트리'


# ---------------------------------------------------------------- reporting

def render(report, show_injection=True):
    out = []
    head = report['head']
    out.append('%sconvention-guard%s  %s' % (BOLD, RESET, head['label']))
    out.append('%s%s  |  스택: %s  |  검사 대상 %d개 파일%s'
               % (DIM, head['root'], ', '.join(head['stacks']) or '감지 실패',
                  head['file_count'], RESET))
    if head['lint_failures']:
        out.append('')
        out.append('%s린터 실패 — 이번 변경 줄에서 확정 위반%s' % (COLOR['error'], RESET))
        for fail in head['lint_failures']:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:15]:
                out.append('    %s%s%s' % (DIM, line, RESET))
            if fail.get('carried'):
                out.append('    %s(기존 코드에 %d건 더 — 차단 대상 아님)%s'
                           % (DIM, fail['carried'], RESET))
    if head.get('lint_notes'):
        out.append('')
        out.append('%s린터가 이번 변경 밖에서 찾은 것 (차단하지 않음)%s' % (DIM, RESET))
        for fail in head['lint_notes']:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:5]:
                out.append('    %s%s%s' % (DIM, line, RESET))
    out.append('')

    if not report['findings']:
        out.append('  지적 사항 없음')
    for finding in report['findings']:
        sev = finding['severity']
        out.append('%s%-5s%s %s  %s%s%s'
                   % (COLOR[sev], sev, RESET, finding['title'],
                      DIM, finding['rule_id'], RESET))
        for loc in finding['locations']:
            out.append('      %s:%d  %s%s%s'
                       % (loc['file'], loc['line'], DIM, loc['snippet'], RESET))
        if show_injection and finding.get('guidance'):
            for line in finding['guidance'].split('\n'):
                out.append('      %s→ %s%s' % (DIM, line, RESET))
        out.append('')

    counts = report['counts']
    out.append('%s요약%s  error %d / warn %d / info %d   (규칙 %d개 중 %d개 적용)'
               % (BOLD, RESET, counts['error'], counts['warn'], counts['info'],
                  report['head']['rules_total'], report['head']['rules_applicable']))
    if report['head']['semantic']:
        out.append('%s      정규식으로 판정 불가한 semantic 규칙 %d개는 이 명령으로 검사되지 '
                   '않습니다%s' % (DIM, report['head']['semantic'], RESET))
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='컨벤션 규칙을 훅 없이 실행합니다')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--staged', action='store_true', help='스테이지된 변경만')
    group.add_argument('--range', help='git 리비전 범위 (예: main..HEAD)')
    group.add_argument('--files', nargs='+', help='지정한 파일 전체를 검사')
    group.add_argument('--all', action='store_true',
                       help='레포 전수조사. 레거시 감사용이며 결과가 많습니다')
    parser.add_argument('--severity', choices=['error', 'warn', 'info'], default='info',
                        help='이 강도 이상만 출력 (기본 info)')
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
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    args = parser.parse_args()

    if args.no_color or args.json or not sys.stdout.isatty():
        _plain()

    root = project_dir(args.cwd)
    if not gitdiff.is_repo(root):
        print('git 레포가 아닙니다: %s' % root, file=sys.stderr)
        return 2

    repo_cfg = rulelib.load_repo_config(args.cwd) or {}
    detected = stacklib.detect(plugin_root(), args.cwd, forced=repo_cfg.get('stacks'))
    all_rules, notes, _ = rulelib.load_all(args.cwd)
    for level, text in notes:
        if level in ('error', 'warn'):
            print('[%s] %s' % (level, text), file=sys.stderr)

    if args.rule:
        all_rules = [r for r in all_rules if args.rule in r['id']]
        if not all_rules:
            print('일치하는 규칙 없음: %s' % args.rule, file=sys.stderr)
            return 2

    args.base_ref = args.base_ref if args.base_ref is not None \
        else (repo_cfg.get('base_ref') or '')
    changed, new_files, label = gather(root, args, all_rules)
    dismissed = frozenset()
    dismissal_count = 0
    if not args.no_dismiss:
        dismissed, entries = dismisslib.load(root)
        dismissal_count = len(entries)
    ctx = engine.Context(root, changed, new_files, detected['tags'],
                         detected['versions'], dismissed)

    lint_failures, lint_notes = [], []
    if not args.no_lint and detected['lint'] and changed:
        lint_failures, lint_notes = lint.split_by_change(
            lint.run(root, detected['lint'], list(changed)), ctx)

    respect = repo_cfg.get('respect_supersede', True)
    hits = engine.collect(all_rules, ctx, args.max_hits, respect_supersede=respect)

    threshold = RANK[args.severity]
    findings, counts = [], {'error': 0, 'warn': 0, 'info': 0}
    for hit in hits:
        sev = hit['rule']['severity']
        counts[sev] = counts.get(sev, 0) + 1
        if RANK.get(sev, 9) > threshold:
            continue
        findings.append({
            'rule_id': hit['rule']['id'],
            'title': hit['rule']['title'],
            'severity': sev,
            'source': hit['rule']['source'],
            'guidance': hit['rule']['injection'],
            'locations': hit['locations'],
        })

    applicable = [r for r in all_rules
                  if not r.get('stack') or '*' in r['stack']
                  or set(r['stack']) & set(detected['tags'])]
    report = {
        'head': {
            'root': root,
            'label': label,
            'stacks': detected['stacks'],
            'file_count': len(changed),
            'rules_total': len(all_rules),
            'rules_applicable': len(applicable),
            'semantic': len([r for r in applicable if r.get('kind') == 'semantic']),
            'lint_failures': lint_failures,
            'lint_notes': lint_notes,
            'dismissed': dismissal_count,
        },
        'counts': counts,
        'findings': findings,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))

    if args.fail_on == 'never':
        return 0
    limit = RANK[args.fail_on]
    worst = min([RANK[f['severity']] for f in findings], default=9)
    return 1 if (lint_failures or worst <= limit) else 0


if __name__ == '__main__':
    sys.exit(main())
