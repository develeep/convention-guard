#!/usr/bin/env python3
"""Rule health from the firing log -- the numbers rule-tune runs on.

    python3 log_report.py                  # 전체
    python3 log_report.py --repo .         # 이 레포에서 발생한 것만
    python3 log_report.py --since 21       # 최근 21일
    python3 log_report.py --json

Per rule:

    candidates   distinct candidates detected (shown or not)
    fixed        flagged, then gone when the cycle closed
    still        flagged, still there when the cycle closed
    dismissed    declined as a false positive (dismiss.py)
    new          introduced by a fix (the fix broke this rule)
    verdicts     reviewer VIOLATION / VALID / FALSE_POSITIVE, counted apart:
                 VALID means the gate was fair but the code is fine,
                 FALSE_POSITIVE means the gate itself caught the wrong code
    autofix      lines auto-fix rewrote

    fix rate     fixed / (fixed + still)
    dismiss rate dismissed / (fixed + still + dismissed)
    precision    VIOLATION / all verdicts        (semantic rules: how good the gate is)
    fp rate      FALSE_POSITIVE / all verdicts   (semantic rules: gate caught the
                                                  wrong code -- fix the regex, not
                                                  the instruction)

Only schema-2 events (1.0) are read; 0.x rows are skipped and counted.
"""

import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.log import log_path, read as read_log  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402

# Below this many decided outcomes a rate says more about luck than the rule.
MIN_DECIDED = 3
HEALTHY, REVIEW = 0.7, 0.3


def _ts(row):
    try:
        return time.mktime(time.strptime(row.get('ts', '')[:19], '%Y-%m-%dT%H:%M:%S'))
    except (ValueError, OverflowError):
        return 0


def select(rows, repo=None, since_days=None):
    cutoff = time.time() - since_days * 86400 if since_days else None
    kept, legacy = [], 0
    for row in rows:
        if row.get('schema') != 2:
            legacy += 1
            continue
        if repo and row.get('repo') != repo:
            continue
        if cutoff and _ts(row) < cutoff:
            continue
        kept.append(row)
    return kept, legacy


def build(rows):
    stats = collections.defaultdict(lambda: {
        'severity': '?', 'semantic': False, 'candidates': set(), 'shown': set(),
        'fixed': 0, 'still': 0, 'dismissed': 0, 'new': 0, 'autofix': 0,
        'review_skipped': 0, 'files': collections.Counter(),
        'verdicts': collections.Counter(), 'dismiss_reasons': []})
    linters = collections.defaultdict(lambda: {'failed': 0, 'blocking': 0, 'anchored': 0})
    final = {}
    # a candidate stays 'new' across every retry of its cycle, so counting rows
    # would let one bad fix look like several
    introduced = set()
    for row in rows:
        event = row.get('event')
        if event == 'lint':
            entry = linters[row.get('cmd') or '?']
            entry['failed'] += 1
            entry['blocking'] += bool(row.get('blocking'))
            entry['anchored'] += bool(row.get('anchored'))
            continue
        rid = row.get('rule_id')
        if not rid or rid == 'lint':
            continue
        entry = stats[rid]
        if event == 'candidate':
            entry['severity'] = row.get('severity', entry['severity'])
            entry['semantic'] = entry['semantic'] or bool(row.get('semantic'))
            entry['candidates'].add(row.get('key'))
            if row.get('shown'):
                entry['shown'].add(row.get('key'))
            entry['files'][row.get('file')] += 1
        elif event == 'verify':
            if row.get('outcome') == 'new':
                introduced.add((row.get('cycle'), row.get('key'), rid))
            else:
                # the last outcome a flagged candidate had in its cycle is its result
                final[(row.get('cycle'), row.get('key'))] = (rid, row.get('outcome'))
        elif event == 'verdict':
            entry['semantic'] = True
            entry['verdicts'][row.get('verdict')] += 1
        elif event == 'dismissed':
            entry['dismissed'] += 1
            if row.get('reason'):
                entry['dismiss_reasons'].append(row['reason'])
        elif event == 'autofix':
            entry['autofix'] += 1
        elif event == 'review_skipped':
            entry['review_skipped'] += 1
    for (_cycle, _key), (rid, outcome) in final.items():
        if outcome in ('fixed', 'still'):
            stats[rid][outcome] += 1
    for _cycle, _key, rid in introduced:
        stats[rid]['new'] += 1
    return stats, linters


def verdict(entry):
    decided = entry['fixed'] + entry['still'] + entry['dismissed']
    total_verdicts = sum(entry['verdicts'].values())
    if decided and entry['dismissed'] / decided >= 0.5:
        return '오탐 확정 — 팀이 기각함, 조건을 좁히세요'
    if total_verdicts >= MIN_DECIDED and entry['verdicts']['FALSE_POSITIVE'] / total_verdicts >= 0.5:
        return '게이트가 엉뚱함 — 리뷰어가 후보 자체를 오탐으로 판정, detect 정규식을 고치세요'
    if total_verdicts >= MIN_DECIDED and entry['verdicts']['VIOLATION'] / total_verdicts < 0.2:
        return '게이트가 넓음 — 리뷰어가 대부분 위반 아님으로 판정, detect 를 좁히세요'
    if entry['new'] >= 2 and entry['new'] >= entry['fixed']:
        return '수정이 새 위반을 만듦 — message 의 수정 지침을 구체화하세요'
    if entry['fixed'] + entry['still'] < MIN_DECIDED:
        return '데이터 부족'
    rate = entry['fixed'] / (entry['fixed'] + entry['still'])
    if rate >= HEALTHY:
        return '건강함'
    if rate >= REVIEW:
        return '조건 검토'
    return '오탐 의심 — 좁히거나 삭제'


def summarize(stats):
    items = []
    for rid, entry in stats.items():
        acted = entry['fixed'] + entry['still']
        decided = acted + entry['dismissed']
        total_verdicts = sum(entry['verdicts'].values())
        items.append({
            'rule_id': rid, 'severity': entry['severity'], 'semantic': entry['semantic'],
            'candidates': len(entry['candidates']), 'shown': len(entry['shown']),
            'fixed': entry['fixed'], 'still': entry['still'], 'dismissed': entry['dismissed'],
            'new': entry['new'], 'autofix': entry['autofix'],
            'review_skipped': entry['review_skipped'],
            'verdicts': dict(entry['verdicts']),
            'fix_rate': entry['fixed'] / acted if acted else None,
            'dismiss_rate': entry['dismissed'] / decided if decided else None,
            'precision': entry['verdicts']['VIOLATION'] / total_verdicts if total_verdicts else None,
            'false_positive_rate': (entry['verdicts']['FALSE_POSITIVE'] / total_verdicts
                                    if total_verdicts else None),
            'reviewed': total_verdicts,
            'top_files': [f for f, _ in entry['files'].most_common(3) if f],
            'dismiss_reasons': entry['dismiss_reasons'][-3:],
            'verdict': verdict(entry),
        })
    items.sort(key=lambda i: (i['fix_rate'] if i['fix_rate'] is not None else 2,
                              -i['candidates']))
    return items


def pct(value):
    return '-' if value is None else '%d%%' % round(value * 100)


def render(items, linters, rows, legacy, path):
    out = ['규칙 건강도  (이벤트 %d건%s, 로그 %s)' % (
        len(rows), ', 0.x 이벤트 %d건 제외' % legacy if legacy else '', path), '']
    out.append('%-40s %-5s %5s %5s %5s %5s %5s %6s %6s  %s'
               % ('규칙', '강도', '후보', '고침', '남음', '기각', '신규', '수정률', '정밀도', '판정'))
    out.append('-' * 118)
    for item in items:
        out.append('%-40s %-5s %5d %5d %5d %5d %5d %6s %6s  %s' % (
            item['rule_id'] + (' *' if item['semantic'] else ''), item['severity'],
            item['candidates'], item['fixed'], item['still'], item['dismissed'], item['new'],
            pct(item['fix_rate']), pct(item['precision']), item['verdict']))
    out.append('')
    out.append('* = 의미 판정 규칙. 정밀도 = 리뷰어가 VIOLATION 으로 판정한 비율')
    reviewed = [i for i in items if i['reviewed']]
    if reviewed:
        out.append('')
        out.append('의미 판정 내역  (판정 / VIOLATION / VALID / FALSE_POSITIVE / 게이트 오탐률)')
        for item in reviewed:
            v = item['verdicts']
            out.append('  %-40s %4d %4d %4d %4d %7s'
                       % (item['rule_id'][:40], item['reviewed'], v.get('VIOLATION', 0),
                          v.get('VALID', 0), v.get('FALSE_POSITIVE', 0),
                          pct(item['false_positive_rate'])))
        out.append('  VALID = 게이트는 적절했고 코드가 정상 / FALSE_POSITIVE = 게이트가 잘못 잡음')
    weak = [i for i in items if i['verdict'] not in ('건강함', '데이터 부족')]
    if weak:
        out.append('')
        out.append('손봐야 할 규칙 %d개:' % len(weak))
        for item in weak:
            out.append('  %s — %s' % (item['rule_id'], item['verdict']))
            if item['top_files']:
                out.append('      자주 걸린 파일: %s' % ', '.join(item['top_files']))
            for reason in item['dismiss_reasons']:
                out.append('      기각 사유: %s' % reason)
    if linters:
        out.append('')
        out.append('린터  (실패 / 그중 차단 / 출력 파싱 성공)')
        for cmd, entry in sorted(linters.items()):
            out.append('  %-60s %4d / %4d / %4d'
                       % (cmd[:60], entry['failed'], entry['blocking'], entry['anchored']))
        out.append('  파싱 성공이 실패보다 적은 린터는 변경 줄로 좁혀지지 않아 출력 전체로 차단합니다 '
                   '— stacks/*.yaml 의 parse 를 확인하세요.')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='규칙 건강도 리포트')
    parser.add_argument('--log', help='로그 경로 (기본: 플러그인 데이터 디렉터리)')
    parser.add_argument('--repo', help='이 레포에서 발생한 이벤트만')
    parser.add_argument('--since', type=int, help='최근 N일')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    path = args.log or log_path()
    repo = git_toplevel(project_dir(args.repo)) if args.repo else None
    rows, legacy = select(read_log(path), repo, args.since)
    if not rows:
        print('읽을 이벤트가 없습니다: %s%s' % (path, ' (0.x 이벤트 %d건은 읽지 않습니다)' % legacy
                                           if legacy else ''))
        print('훅이 아직 돌지 않았거나 CLAUDE_PLUGIN_DATA / userConfig log_dir 경로가 다릅니다.')
        return 0
    stats, linters = build(rows)
    items = summarize(stats)
    if args.json:
        print(json.dumps({'events': len(rows), 'legacy_skipped': legacy, 'rules': items,
                          'linters': linters}, ensure_ascii=False, indent=2))
    else:
        print(render(items, linters, rows, legacy, path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
