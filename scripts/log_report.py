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

from lib.paths import log_path  # noqa: E402


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
                 'severity': '?', 'source': '?', 'files': collections.Counter(),
                 'downgraded': 0, 'queued': 0})
    for row in rows:
        rid = row.get('rule_id')
        if not rid:
            continue
        entry = stat[rid]
        event = row.get('event')
        if event == 'match':
            entry['fired'] += 1
            entry['shown'] += bool(row.get('shown'))
            entry['severity'] = row.get('severity', entry['severity'])
            entry['source'] = row.get('source', entry['source'])
            entry['downgraded'] += bool(row.get('downgraded'))
            for f in row.get('files') or []:
                entry['files'][f] += 1
        elif event == 'followup':
            entry['followups'] += 1
            entry['fixed'] += bool(row.get('fixed'))
        elif event == 'semantic_queued':
            entry['queued'] += 1
            entry['severity'] = row.get('severity', entry['severity'])
    return stat


def verdict(entry):
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
    parser.add_argument('--log', default=log_path())
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--min-fired', type=int, default=1)
    args = parser.parse_args()

    rows = load(args.log)
    if not rows:
        print('로그가 비어 있습니다: %s' % args.log)
        print('훅이 아직 돌지 않았거나 CLAUDE_PLUGIN_DATA 경로가 다릅니다.')
        return 0

    stat = build(rows)
    items = []
    for rid, entry in stat.items():
        if entry['fired'] < args.min_fired and not entry['queued']:
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
            'downgraded': entry['downgraded'],
            'top_files': [f for f, _ in entry['files'].most_common(3)],
            'verdict': verdict(entry),
        })
    items.sort(key=lambda i: (i['fix_rate'] if i['fix_rate'] is not None else 2,
                              -i['fired']))

    if args.json:
        print(json.dumps({'total_events': len(rows), 'rules': items},
                         ensure_ascii=False, indent=2))
        return 0

    print('규칙 건강도  (이벤트 %d건, 로그 %s)\n' % (len(rows), args.log))
    print('%-42s %-6s %5s %6s %8s  %s'
          % ('규칙', '강도', '발동', '표시', '수정률', '판정'))
    print('-' * 100)
    for item in items:
        rate = '%.0f%% (%d/%d)' % (item['fix_rate'] * 100, item['fixed'],
                                   item['followups']) if item['fix_rate'] is not None else '-'
        print('%-42s %-6s %5d %6d %8s  %s'
              % (item['rule_id'], item['severity'], item['fired'],
                 item['shown'], rate, item['verdict']))
    weak = [i for i in items if i['followups'] >= 3 and i['fix_rate'] < 0.3]
    if weak:
        print('\n손봐야 할 규칙 %d개:' % len(weak))
        for item in weak:
            print('  %s — 자주 걸린 파일: %s'
                  % (item['rule_id'], ', '.join(item['top_files']) or '-'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
