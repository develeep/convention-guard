#!/usr/bin/env python3
"""Rule health report from the firing log.

The number that matters is the fix rate: of the times a rule was shown to the
agent, how often did the finding actually disappear. A rule that fires often
and is never acted on is either a false positive or something the team does not
agree with. Either way it is costing attention and buying nothing.

    python3 log_report.py                 # 전체
    python3 log_report.py --repo <path>   # 이 레포에서 걸린 것만
    python3 log_report.py --json
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.log import log_path, read as read_log  # noqa: E402


def load(path):
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return rows


def build(rows):
    stat = collections.defaultdict(
        lambda: {'fired': 0, 'shown': 0, 'followups': 0, 'fixed': 0,
                 'dismissed': 0, 'severity': '?', 'source': '?',
                 'files': collections.Counter(), 'downgraded': 0, 'queued': 0})
    linters = collections.defaultdict(
        lambda: {'failed': 0, 'blocking': 0, 'anchored': 0})
    for row in rows:
        event = row.get('event')
        if event == 'lint':
            entry = linters[row.get('cmd') or '?']
            entry['failed'] += 1
            entry['blocking'] += bool(row.get('blocking'))
            entry['anchored'] += bool(row.get('anchored'))
            continue
        rid = row.get('rule_id')
        if not rid:
            continue
        entry = stat[rid]
        if event == 'match':
            entry['fired'] += 1
            entry['shown'] += bool(row.get('shown'))
            entry['severity'] = row.get('severity', entry['severity'])
            entry['source'] = row.get('source', entry['source'])
            entry['downgraded'] += bool(row.get('downgraded'))
            for f in row.get('files') or []:
                entry['files'][f] += 1
        elif event == 'followup':
            if row.get('dismissed'):
                # declined as a false positive: counting it as "not fixed"
                # is what used to make a correct rejection look like neglect
                entry['dismissed'] += 1
                continue
            entry['followups'] += 1
            entry['fixed'] += bool(row.get('fixed'))
        elif event == 'dismissed':
            entry['dismissed'] += 1
        elif event == 'semantic_queued':
            entry['queued'] += 1
            entry['severity'] = row.get('severity', entry['severity'])
    return stat, linters


def verdict(entry):
    decided = entry['followups'] + entry['dismissed']
    if decided and entry['dismissed'] / decided >= 0.5:
        return '오탐 확정 — 팀이 기각함, 조건을 좁히세요'
    if entry['followups'] < 3:
        return '데이터 부족'
    rate = entry['fixed'] / entry['followups']
    if rate >= 0.7:
        return '건강함'
    if rate >= 0.3:
        return '조건 검토'
    return '오탐 의심 — 좁히거나 삭제'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default=None, help='로그 경로 (기본: 플러그인 데이터 디렉터리)')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--min-fired', type=int, default=1)
    args = parser.parse_args()

    args.log = args.log or log_path()
    rows = read_log(args.log)
    if not rows:
        print('로그가 비어 있습니다: %s' % args.log)
        print('훅이 아직 돌지 않았거나 CLAUDE_PLUGIN_DATA 경로가 다릅니다.')
        return 0

    stat, linters = build(rows)
    items = []
    for rid, entry in stat.items():
        if entry['fired'] < args.min_fired and not entry['queued'] \
                and not entry['dismissed']:
            continue
        rate = (entry['fixed'] / entry['followups']) if entry['followups'] else None
        items.append({
            'rule_id': rid,
            'severity': entry['severity'],
            'source': entry['source'],
            'fired': entry['fired'],
            'shown': entry['shown'],
            'followups': entry['followups'],
            'fixed': entry['fixed'],
            'fix_rate': rate,
            'queued': entry['queued'],
            'dismissed': entry['dismissed'],
            'top_files': [f for f, _ in entry['files'].most_common(3)],
            'verdict': verdict(entry),
        })
    items.sort(key=lambda i: (i['fix_rate'] if i['fix_rate'] is not None else 2,
                              -i['fired']))

    if args.json:
        print(json.dumps({'total_events': len(rows), 'rules': items,
                          'linters': linters}, ensure_ascii=False, indent=2))
        return 0

    print('규칙 건강도  (이벤트 %d건, 로그 %s)\n' % (len(rows), args.log))
    print('%-42s %-6s %5s %6s %8s %5s  %s'
          % ('규칙', '강도', '발동', '표시', '수정률', '기각', '판정'))
    print('-' * 108)
    for item in items:
        rate = '%.0f%% (%d/%d)' % (item['fix_rate'] * 100, item['fixed'],
                                   item['followups']) if item['fix_rate'] is not None else '-'
        print('%-42s %-6s %5d %6d %8s %5d  %s'
              % (item['rule_id'], item['severity'], item['fired'],
                 item['shown'], rate, item['dismissed'], item['verdict']))
    weak = [i for i in items
            if (i['followups'] >= 3 and i['fix_rate'] < 0.3) or i['dismissed'] >= 2]
    if weak:
        print('\n손봐야 할 규칙 %d개:' % len(weak))
        for item in weak:
            print('  %s — 자주 걸린 파일: %s%s'
                  % (item['rule_id'], ', '.join(item['top_files']) or '-',
                     '  (기각 %d건)' % item['dismissed'] if item['dismissed'] else ''))
    if linters:
        print('\n린터  (실패 / 그중 차단 / 출력 파싱 성공)')
        for cmd, entry in sorted(linters.items()):
            print('  %-60s %4d / %4d / %4d'
                  % (cmd[:60], entry['failed'], entry['blocking'], entry['anchored']))
        print('  파싱 성공 건수가 실패 건수보다 적으면 그 린터는 변경 줄로 좁혀지지 '
              '않아 통째로 차단합니다 — stacks/*.yaml 의 parse 설정을 보세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
