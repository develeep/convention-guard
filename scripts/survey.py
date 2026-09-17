#!/usr/bin/env python3
"""전수조사로 규칙 후보를 추천합니다.

규칙을 추천한다는 건 팀이 **이미 지키고 있는 것을 굳히는** 일입니다. 그래서 후보마다
정상 패턴(`probe.conforming`)과 위반 트리거를 둘 다 들고, 레포 전체를 훅과 같은
엔진으로 훑어 파일 단위 준수율을 냅니다. 92%가 한 방향이면 컨벤션이고 남은 8%는
회귀입니다. 50:50이면 컨벤션이 아니라 취향 차이이고, 그걸 규칙으로 만들면 오탐으로만
보입니다.

    python3 survey.py                       # 추천 목록
    python3 survey.py --json                # 기계용
    python3 survey.py --all-verdicts        # 추천하지 않는 것까지 전부
    python3 survey.py --adopt local-id ...  # 골라서 레포 규칙으로 승격
    python3 survey.py --adopt <id> --severity error

    # 후보 파일을 쓰기 전에 가설 하나만 즉석 측정
    python3 survey.py --probe '<위반>' --conforming '<정상>' --files 'app/**/*.php'

`--adopt` 는 후보 파일에서 카탈로그 전용 키(`probe`/`rationale`/`covered_by`)를 떼고
`<repo>/.claude/convention-rules/` 에 씁니다. 그대로 규칙이 되므로 픽스처도 함께
따라가고, 바로 `test_rules.py` 로 검증됩니다.

`--probe` 는 아무것도 쓰지 않고 같은 엔진·같은 판정으로 숫자만 냅니다. 레포를 훑다
발견한 관습을 후보 파일로 만들기 전에 거르는 용도입니다 — 인상은 규칙이 될 수 없고,
세어보지 않은 관습은 오탐이 됩니다.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import engine, gitdiff, rules as rulelib, stack as stacklib  # noqa: E402
from lib.paths import plugin_root, project_dir, read_yaml  # noqa: E402

CANDIDATE_DIRNAME = 'candidates'
CATALOG_KEYS = ('probe', 'rationale', 'covered_by')
MAX_FILES = 3000

RANK = {'already': 0, 'recommend': 1, 'undecided': 2, 'thin': 3, 'against': 4,
        'absent': 5, 'covered': 6, 'adopted': 7}
VERDICT_TEXT = {
    'already': '이미 100% 준수 — 회귀 방지용',
    'recommend': '추천',
    'undecided': '합의 필요 — 팀이 갈려 있음',
    'thin': '표본 부족 — 해당 코드가 3개 미만',
    'against': '반대 관습 — 추천 안 함',
    'absent': '해당 코드 없음',
    'covered': '공통 규칙이 이미 덮음',
    'adopted': '이미 채택됨',
}
MIN_SAMPLE = 3


# ---------------------------------------------------------------- loading

def candidate_dirs(cwd=None):
    return [(os.path.join(plugin_root(), CANDIDATE_DIRNAME), 'candidate'),
            (os.path.join(rulelib.local_dir(cwd), CANDIDATE_DIRNAME),
             'local-candidate')]


def load_candidates(cwd=None, dirs=None):
    """Returns (candidates, notes). A candidate is a rule plus catalog keys."""
    out, notes = [], []
    for base, source in (dirs or candidate_dirs(cwd)):
        for path in rulelib._iter_rule_files(base):
            try:
                raw = read_yaml(path) or {}
            except Exception as exc:
                notes.append(('error', '%s: 파싱 실패 (%s)' % (path, exc)))
                continue
            if not isinstance(raw, dict):
                notes.append(('error', '%s: 최상위가 매핑이 아님' % path))
                continue
            probe = raw.get('probe') or {}
            conforming = probe.get('conforming') if isinstance(probe, dict) else None
            if not conforming:
                notes.append(('warn', '%s: probe.conforming 없음 (건너뜀)' % path))
                continue
            # candidates get their own namespace: a candidate is not a rule
            # yet, and adopting it produces `local/<id>` instead
            cand = rulelib._normalize(raw, path, source)
            try:
                cand['kind'] = rulelib._compile(cand)
                cand['compiled_conforming'] = re.compile(conforming, re.M)
            except re.error as exc:
                notes.append(('error', '%s: 정규식 오류 (%s)' % (path, exc)))
                continue
            except ValueError as exc:
                notes.append(('warn', '%s: %s (건너뜀)' % (path, exc)))
                continue
            cand['catalog_source'] = source
            cand['bare_id'] = cand['id'].split('/', 1)[-1]
            cand['adopted_id'] = 'local/%s' % cand['bare_id']
            cand['rationale'] = (raw.get('rationale') or '').strip()
            cand['covered_by'] = raw.get('covered_by')
            cand['repo_exclude'] = []
            out.append(cand)
    return out, notes


# ---------------------------------------------------------------- measuring

def tracked_files(root, candidates, repo_exclude, limit=MAX_FILES):
    """Tracked files any candidate could apply to. Same idea as `scan.py --all`."""
    code, out = gitdiff._git(root, ['ls-files'])
    files = out.splitlines() if code == 0 else []
    globs = set()
    for cand in candidates:
        if not cand.get('files'):
            globs = None
            break
        globs.update(cand['files'])
    if globs:
        files = [f for f in files if rulelib._match_any(list(globs), f)]
    files = [f for f in files
             if not rulelib._match_any(repo_exclude, f)
             and os.path.splitext(f)[1].lower() not in gitdiff.SKIP_EXT]
    return sorted(files)[:limit], len(files)


def build_context(root, files, tags, versions):
    """Whole-file context: an audit treats every file as new, so absence
    triggers apply too. That is exactly `scan.py --all` semantics."""
    changed = {}
    for rel in files:
        lines = gitdiff._whole_file(root, rel)
        if lines:
            changed[rel] = lines
    return engine.Context(root, changed, set(changed), tags, versions)


def measure(cand, ctx, active_rule_ids, cap=200, examples=3):
    applicable = [f for f in ctx.files()
                  if rulelib.applies(cand, f, ctx.tags, ctx.versions)]
    locations = engine.scan(cand, ctx, cap)
    violating = sorted({loc['file'] for loc in locations})
    conforming = []
    for rel in applicable:
        if rel in violating:
            continue
        if cand['compiled_conforming'].search(ctx.text(rel)):
            conforming.append(rel)

    total = len(violating) + len(conforming)
    ratio = (len(conforming) / total) if total else None
    covered = bool(cand.get('covered_by') and cand['covered_by'] in active_rule_ids)

    if cand['adopted_id'] in active_rule_ids:
        verdict = 'adopted'
    elif covered:
        verdict = 'covered'
    elif total == 0:
        verdict = 'absent'
    elif not violating and len(conforming) >= MIN_SAMPLE:
        verdict = 'already'
    elif total < MIN_SAMPLE:
        # one file either way is not a convention. Calling it "the repo does
        # the opposite" on a single hit is how a recommendation loses trust.
        verdict = 'thin'
    elif ratio >= 0.8:
        verdict = 'recommend'
    elif ratio >= 0.3:
        verdict = 'undecided'
    else:
        verdict = 'against'

    return {
        'id': cand['id'],
        'adopted_id': cand['adopted_id'],
        'already_adopted': cand['adopted_id'] in active_rule_ids,
        'title': cand['title'],
        'severity': cand['severity'],
        'kind': cand['kind'],
        'source': cand['catalog_source'],
        'path': cand['path'],
        'rationale': cand['rationale'],
        'covered_by': cand.get('covered_by'),
        'stack': cand.get('stack') or [],
        'scanned': len(applicable),
        'conforming': len(conforming),
        'violating': len(violating),
        'violations': len(locations),
        'adherence': ratio,
        'verdict': verdict,
        'suggested_severity': 'error' if verdict == 'already' else 'warn',
        'examples': [{'file': loc['file'], 'line': loc['line'],
                      'snippet': loc['snippet']} for loc in locations[:examples]],
        'conforming_examples': conforming[:examples],
    }


def survey(cwd=None, dirs=None, limit=MAX_FILES):
    root = project_dir(cwd)
    repo_cfg = rulelib.load_repo_config(cwd) or {}
    detected = stacklib.detect(plugin_root(), cwd, forced=repo_cfg.get('stacks'))
    all_rules, rule_notes, _cfg = rulelib.load_all(cwd)
    active = {r['id'] for r in all_rules}
    repo_exclude = (all_rules[0].get('repo_exclude') if all_rules else None) or []

    candidates, notes = load_candidates(cwd, dirs)
    notes = [n for n in rule_notes if n[0] == 'error'] + notes
    applicable = [c for c in candidates
                  if rulelib.stack_ok(c, detected['tags'], detected['versions'])]

    files, matched_total = tracked_files(root, applicable, repo_exclude, limit)
    ctx = build_context(root, files, detected['tags'], detected['versions'])
    rows = [measure(c, ctx, active) for c in applicable]
    rows.sort(key=lambda r: (RANK.get(r['verdict'], 9),
                             -(r['adherence'] or 0), r['id']))
    return {
        'root': root,
        'stacks': detected['stacks'],
        'files_scanned': len(files),
        'files_truncated': max(0, matched_total - len(files)),
        'candidates_total': len(candidates),
        'candidates_applicable': len(applicable),
        'rows': rows,
        'notes': notes,
    }, candidates


# ---------------------------------------------------------------- probing

PROBE_TRIGGERS = {'line': 'code_regex', 'file': 'file_regex'}


def build_probe(violating, conforming, files=None, exclude=None,
                kind='line', flags=''):
    """A candidate that lives only for this one command.

    Writing a YAML file per hunch is too slow to iterate on, and a hunch that
    was never counted has no business becoming a rule. So the regex pair goes
    through the same normalization, the same engine and the same verdicts as
    the catalog -- the only difference is that nothing is persisted.
    """
    raw = {
        'id': 'probe/adhoc',
        'title': '즉석 측정',
        'severity': 'warn',
        'applies_to': {'stack': ['*'], 'files': list(files or []),
                       'exclude': list(exclude or [])},
        'triggers': {PROBE_TRIGGERS[kind]: violating, 'flags': flags},
    }
    cand = rulelib._normalize(raw, '<probe>', 'probe')
    cand['kind'] = rulelib._compile(cand)
    cand['compiled_conforming'] = re.compile(
        conforming, re.M | (re.I if 'i' in str(flags) else 0))
    cand.update({
        'catalog_source': 'probe',
        'bare_id': 'adhoc',
        'adopted_id': '',       # nothing to collide with: this is not a rule
        'rationale': '',
        'covered_by': None,
        'repo_exclude': [],
    })
    return cand


def probe(cand, cwd=None, limit=MAX_FILES, examples=8):
    root = project_dir(cwd)
    repo_cfg = rulelib.load_repo_config(cwd) or {}
    detected = stacklib.detect(plugin_root(), cwd, forced=repo_cfg.get('stacks'))
    all_rules, rule_notes, _cfg = rulelib.load_all(cwd)
    active = {r['id'] for r in all_rules}
    repo_exclude = (all_rules[0].get('repo_exclude') if all_rules else None) or []

    files, matched_total = tracked_files(root, [cand], repo_exclude, limit)
    ctx = build_context(root, files, detected['tags'], detected['versions'])
    return {
        'root': root,
        'stacks': detected['stacks'],
        'files_scanned': len(files),
        'files_truncated': max(0, matched_total - len(files)),
        'row': measure(cand, ctx, active, examples=examples),
        'notes': [n for n in rule_notes if n[0] == 'error'],
    }


def render_probe(report):
    row = report['row']
    ratio = ('%.0f%%' % (row['adherence'] * 100)
             if row['adherence'] is not None else '-')
    out = ['convention-guard 즉석 측정',
           '%s  |  스택: %s  |  파일 %d개 조사'
           % (report['root'], ', '.join(report['stacks']) or '감지 실패',
              report['files_scanned']),
           '']
    if report['files_truncated']:
        out.append('(파일 %d개는 상한을 넘어 제외 — --max-files 로 조정)'
                   % report['files_truncated'])
    out.append('준수 %d / 위반 %d  (대상 %d개)   준수율 %s   %s'
               % (row['conforming'], row['violating'], row['scanned'],
                  ratio, VERDICT_TEXT[row['verdict']]))
    out.append('')
    for ex in row['examples']:
        out.append('  위반 %s:%d  %s' % (ex['file'], ex['line'], ex['snippet']))
    for rel in row['conforming_examples']:
        out.append('  준수 %s' % rel)
    out.append('')
    if row['verdict'] in ('already', 'recommend'):
        out.append('이 숫자가 맞으면 후보 파일로 옮기세요 (권장 강도: %s):'
                   % row['suggested_severity'])
        out.append('  <repo>/.claude/convention-rules/candidates/<id>.yaml')
        out.append('  위반 예시를 몇 개 열어 정규식 오탐이 아닌지 먼저 확인하세요.')
    else:
        out.append('규칙으로 만들지 마세요. 위반 예시가 실제 위반이 아니면 '
                   '정규식을 좁히고 다시 재세요.')
    for level, text in report['notes']:
        out.append('  %-5s %s' % (level, text))
    return '\n'.join(out)


# ---------------------------------------------------------------- adopting

def _strip_top_keys(text, keys):
    """Drop top-level YAML blocks. The candidate files are hand-written and
    flat, so working on the text keeps their comments and layout intact."""
    out, skipping = [], False
    for line in text.replace('\r\n', '\n').split('\n'):
        stripped = line.strip()
        is_top = line[:1] not in (' ', '\t', '') and ':' in line
        if is_top:
            skipping = line.split(':', 1)[0].strip() in keys
        elif skipping and (not stripped or stripped.startswith('#')
                           or line[:1] in (' ', '\t')):
            pass
        elif not stripped and not skipping:
            pass
        if not skipping:
            out.append(line)
    return '\n'.join(out)


def _set_severity(text, severity):
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if line.startswith('severity:'):
            lines[i] = 'severity: %s' % severity
            return '\n'.join(lines)
    return '\n'.join(lines)


def adopt(root, cand, severity=None, newline='\n'):
    """Write a candidate into the repo's rules. Returns the written path."""
    target_dir = os.path.join(root, rulelib.LOCAL_DIRNAME)
    os.makedirs(target_dir, exist_ok=True)
    name = os.path.basename(cand['path'])
    target = os.path.join(target_dir, name)
    with open(cand['path'], 'r', encoding='utf-8') as fh:
        text = fh.read()
    body = _strip_top_keys(text, CATALOG_KEYS)
    if severity:
        body = _set_severity(body, severity)
    header = ('# convention-guard: survey.py 추천을 채택한 규칙입니다.\n'
              '# 원본 후보: %s\n'
              '# 채택 근거: 이 레포의 준수율 측정 결과 (survey.py 로 다시 확인 가능)\n'
              % os.path.relpath(cand['path'], plugin_root()))
    text_out = header + body.strip() + '\n'
    if newline != '\n':
        text_out = text_out.replace('\n', newline)
    with open(target, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text_out)
    return target


def repo_newline(root):
    """Follow the target repo's line endings, not the plugin's."""
    for probe in ('README.md', 'composer.json', 'package.json', 'go.mod'):
        path = os.path.join(root, probe)
        if os.path.isfile(path):
            with open(path, 'rb') as fh:
                head = fh.read(4000)
            return '\r\n' if b'\r\n' in head else '\n'
    return os.linesep


# ---------------------------------------------------------------- reporting

def render(report, show_all=False):
    out = []
    head = '%s  |  스택: %s  |  후보 %d개 중 이 레포 적용 %d개  |  파일 %d개 조사' % (
        report['root'], ', '.join(report['stacks']) or '감지 실패',
        report['candidates_total'], report['candidates_applicable'],
        report['files_scanned'])
    out.append('convention-guard 규칙 후보')
    out.append(head)
    if report['files_truncated']:
        out.append('(파일 %d개는 상한을 넘어 제외했습니다 — --max-files 로 조정)'
                   % report['files_truncated'])
    out.append('')

    shown = [r for r in report['rows']
             if show_all or r['verdict'] in ('already', 'recommend', 'undecided')]
    if not shown:
        out.append('  추천할 후보가 없습니다. --all-verdicts 로 전부 볼 수 있습니다.')
    for row in shown:
        ratio = '%3.0f%%' % (row['adherence'] * 100) if row['adherence'] is not None else '  -'
        out.append('%-38s %s  준수 %d / 위반 %d   %s'
                   % (row['id'], ratio, row['conforming'], row['violating'],
                      VERDICT_TEXT[row['verdict']]))
        out.append('    %s' % row['title'])
        if row['rationale']:
            out.append('    %s' % row['rationale'])
        if row['covered_by']:
            out.append('    이미 있는 규칙: %s' % row['covered_by'])
        for ex in row['examples']:
            out.append('    위반 예: %s:%d  %s' % (ex['file'], ex['line'], ex['snippet']))
        for ex in row['conforming_examples'][:1]:
            out.append('    준수 예: %s' % ex)
        if row['verdict'] != 'adopted':
            out.append('    채택: --adopt %s --severity %s   → 규칙 %s 로 생깁니다'
                       % (row['id'], row['suggested_severity'], row['adopted_id']))
        out.append('')

    counts = {}
    for row in report['rows']:
        counts[row['verdict']] = counts.get(row['verdict'], 0) + 1
    out.append('요약  ' + '  '.join('%s %d' % (VERDICT_TEXT[k], v)
                                    for k, v in sorted(counts.items(),
                                                       key=lambda kv: RANK[kv[0]])))
    if report['notes']:
        out.append('')
        for level, text in report['notes']:
            out.append('  %-5s %s' % (level, text))
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='전수조사로 규칙 후보를 추천합니다')
    parser.add_argument('--adopt', nargs='+', metavar='ID',
                        help='이 후보들을 레포 규칙으로 채택')
    parser.add_argument('--severity', choices=['error', 'warn', 'info'],
                        help='채택할 때 쓸 강도 (기본: 후보의 권장값)')
    parser.add_argument('--all-verdicts', action='store_true',
                        help='추천하지 않는 후보까지 전부 출력')
    parser.add_argument('--probe', metavar='REGEX',
                        help='후보 파일 없이 위반 패턴 하나를 즉석 측정 '
                             '(--conforming 필수)')
    parser.add_argument('--conforming', metavar='REGEX',
                        help='--probe 의 정상 패턴. 이게 걸리는 파일을 준수로 셉니다')
    parser.add_argument('--files', nargs='+', metavar='GLOB', default=[],
                        help='--probe 대상 글롭 (기본: 추적되는 파일 전부)')
    parser.add_argument('--exclude', nargs='+', metavar='GLOB', default=[],
                        help='--probe 에서 제외할 글롭')
    parser.add_argument('--kind', choices=sorted(PROBE_TRIGGERS), default='line',
                        help='line: 한 줄 패턴 (기본) / file: 여러 줄 패턴')
    parser.add_argument('--flags', default='', help="정규식 플래그 (i)")
    parser.add_argument('--examples', type=int, default=8,
                        help='--probe 가 보여줄 예시 수 (기본 8)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--max-files', type=int, default=MAX_FILES)
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    args = parser.parse_args()

    root = project_dir(args.cwd)
    if not gitdiff.is_repo(root):
        print('git 레포가 아닙니다: %s' % root, file=sys.stderr)
        return 2

    if args.probe:
        if not args.conforming:
            print('--probe 에는 --conforming 이 필요합니다. 정상 패턴이 없으면 '
                  '준수율을 셀 수 없고, 그러면 컨벤션인지 알 수 없습니다.',
                  file=sys.stderr)
            return 2
        try:
            cand = build_probe(args.probe, args.conforming, args.files,
                               args.exclude, args.kind, args.flags)
        except re.error as exc:
            print('정규식 오류: %s' % exc, file=sys.stderr)
            return 2
        except ValueError as exc:
            print('%s' % exc, file=sys.stderr)
            return 2
        report = probe(cand, args.cwd, limit=args.max_files,
                       examples=args.examples)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(render_probe(report))
        return 0

    report, candidates = survey(args.cwd, limit=args.max_files)

    if args.adopt:
        by_id = {c['id']: c for c in candidates}
        rows = {r['id']: r for r in report['rows']}
        newline = repo_newline(root)
        missing = [i for i in args.adopt if i not in by_id]
        if missing:
            print('그런 후보가 없습니다: %s' % ', '.join(missing), file=sys.stderr)
            print('사용 가능한 후보: %s'
                  % ', '.join(sorted(by_id)), file=sys.stderr)
            return 2
        for rid in args.adopt:
            row = rows.get(rid)
            severity = args.severity or (row or {}).get('suggested_severity') or 'warn'
            path = adopt(root, by_id[rid], severity, newline)
            verdict = VERDICT_TEXT[row['verdict']] if row else '측정 없음'
            print('채택 %s (%s) → %s' % (rid, severity, path))
            print('   판정: %s / 준수 %s · 위반 %s'
                  % (verdict, (row or {}).get('conforming', '-'),
                     (row or {}).get('violating', '-')))
        print()
        print('검증하세요:')
        print('  python3 "%s" --repo "%s"'
              % (os.path.join(plugin_root(), 'scripts', 'test_rules.py'), root))
        print('  python3 "%s" --all --rule local/ --no-color'
              % os.path.join(plugin_root(), 'scripts', 'scan.py'))
        return 0

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(render(report, args.all_verdicts))
    return 0


if __name__ == '__main__':
    sys.exit(main())
