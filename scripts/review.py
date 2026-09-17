#!/usr/bin/env python3
"""Hand a semantic review batch to a reviewer and record what it decided.

    python3 review.py show BATCH                 # 판정할 후보와 컨텍스트 팩
    python3 review.py record BATCH < verdicts.json
    python3 review.py summary BATCH              # 기록된 판정 요약

`record` reads a JSON array from stdin, one entry per candidate id in the batch:

    [{"id": 1, "verdict": "VIOLATION", "reason": "orders 가 eager load 없이 반복됨"},
     {"id": 2, "verdict": "VALID", "reason": "with('items') 로 이미 로드됨"}]

    VIOLATION        실제 컨벤션 위반
    VALID            위반 아님
    FALSE_POSITIVE   정규식 게이트가 잘못 잡은 코드 (규칙을 좁힐 근거)

Every id must be answered and every answer needs a reason; an incomplete
record is refused with the list of what is missing, and nothing is written.

Exit codes: 0 ok, 2 invalid input or batch.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import semantic  # noqa: E402
from lib.candidate import VERDICTS, VIOLATION  # noqa: E402


def script_path():
    return os.path.abspath(__file__).replace(os.sep, '/')


def show(batch, path):
    out = ['# convention-guard 판정 배치 — 후보 %d건' % len(batch['items']),
           'repo: %s' % batch['repo'], '']
    by_rule = {}
    for item in batch['items']:
        by_rule.setdefault(item['rule_id'], []).append(item)
    for rule_id, items in by_rule.items():
        rule = batch['rules'][rule_id]
        out += ['## [%s] %s  (%s)' % (rule_id, rule['title'], rule['severity']), '',
                '판정 기준:']
        out += ['  %s' % line for line in rule['instruction'].split('\n')]
        out.append('')
        for item in items:
            ctx = item['context']
            out += ['### 후보 %d — %s:%d' % (item['id'], item['file'], item['line']),
                    '    %s' % item['snippet'], '']
            for section in ctx['sections']:
                out += ['%s:' % section['title'], section['text'], '']
            if ctx.get('truncated'):
                out.append('(일부 생략됨 — 판정에 꼭 필요할 때만 Read 로 더 보세요)')
                out.append('')
    ids = ', '.join(str(item['id']) for item in batch['items'])
    out += ['---', '모든 후보(%s)에 대한 판정을 한 번에 기록하세요:' % ids, '',
            "python3 \"%s\" record \"%s\" <<'JSON'" % (script_path(), path.replace(os.sep, '/')),
            '[' + ',\n '.join('{"id": %d, "verdict": "…", "reason": "…"}' % item['id']
                              for item in batch['items']) + ']',
            'JSON', '',
            'verdict: VIOLATION (실제 위반) / VALID (위반 아님) / FALSE_POSITIVE (게이트가 잘못 잡음)',
            '확신이 없으면 VALID 입니다.']
    return '\n'.join(out)


def validate(batch, answers):
    problems = []
    if not isinstance(answers, list):
        return None, ['JSON 배열이어야 합니다: [{"id": 1, "verdict": "VALID", "reason": "…"}]']
    items = {item['id']: item for item in batch['items']}
    seen = {}
    for n, answer in enumerate(answers, 1):
        if not isinstance(answer, dict):
            problems.append('%d번째 항목이 객체가 아닙니다' % n)
            continue
        ident = answer.get('id')
        if ident not in items:
            problems.append('없는 후보 id: %r (가능: %s)' % (ident, ', '.join(map(str, items))))
            continue
        if ident in seen:
            problems.append('후보 %d 가 두 번 기록됐습니다' % ident)
            continue
        verdict = str(answer.get('verdict') or '').strip().upper()
        if verdict not in VERDICTS:
            problems.append('후보 %d: verdict 는 %s 중 하나입니다 (받은 값: %r)'
                            % (ident, ' / '.join(VERDICTS), answer.get('verdict')))
            continue
        reason = str(answer.get('reason') or '').strip()
        if not reason:
            problems.append('후보 %d: reason 이 비어 있습니다 — 판단 근거를 한 줄 적으세요' % ident)
            continue
        seen[ident] = {'verdict': verdict, 'reason': reason}
    missing = [str(i) for i in items if i not in seen]
    if missing and not problems:
        problems.append('판정이 빠진 후보: %s' % ', '.join(missing))
    return seen, problems


def record(batch, path, answers):
    seen, problems = validate(batch, answers)
    if problems:
        return problems
    items = {item['id']: item for item in batch['items']}
    verdicts = {}
    for ident, answer in seen.items():
        item = items[ident]
        verdicts[item['review_key']] = dict(answer, rule_id=item['rule_id'], file=item['file'],
                                            line=item['line'], key=item['key'], id=ident)
    with open(semantic.verdicts_path(path), 'w', encoding='utf-8') as fh:
        json.dump(verdicts, fh, ensure_ascii=False, indent=1)
    semantic.store(semantic.cache_path(batch['data_dir']), batch['repo'], verdicts)
    try:
        with open(batch['log'], 'a', encoding='utf-8') as fh:
            for review_key, v in verdicts.items():
                fh.write(json.dumps({'event': 'verdict', 'schema': 2, 'source': 'reviewer',
                                     'session': batch.get('session'), 'repo': batch['repo'],
                                     'rule_id': v['rule_id'],
                                     'key': v['key'], 'review_key': review_key,
                                     'file': v['file'], 'verdict': v['verdict'],
                                     'reason': v['reason'],
                                     'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z')},
                                    ensure_ascii=False) + '\n')
    except OSError:
        pass
    return []


def summary(batch, verdicts):
    counts = {v: 0 for v in VERDICTS}
    for v in verdicts.values():
        counts[v['verdict']] = counts.get(v['verdict'], 0) + 1
    out = ['기록된 판정 — %s' % ' / '.join('%s %d' % (k, counts[k]) for k in VERDICTS)]
    violations = sorted((v for v in verdicts.values() if v['verdict'] == VIOLATION),
                        key=lambda v: (v['file'], v['line']))
    if violations:
        out.append('')
        out.append('메인 에이전트에게 돌려줄 내용 (VIOLATION 만):')
        for v in violations:
            out.append('[%s] %s:%d — %s' % (v['rule_id'], v['file'], v['line'], v['reason']))
    else:
        out.append('')
        out.append('메인 에이전트에게 돌려줄 내용: 위반 없음')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description='convention-guard 의미 판정 배치 도구')
    parser.add_argument('command', choices=['show', 'record', 'summary'])
    parser.add_argument('batch', help='배치 파일 경로 (Stop 훅이나 scan.py --review 가 알려준 경로)')
    parser.add_argument('--json', action='store_true', help='show: 배치 원본 JSON 출력')
    args = parser.parse_args()

    path = os.path.abspath(args.batch)
    try:
        batch = semantic.read_batch(path)
    except (OSError, ValueError) as exc:
        print('배치를 읽을 수 없습니다: %s' % exc, file=sys.stderr)
        return 2

    if args.command == 'show':
        print(json.dumps(batch, ensure_ascii=False, indent=1) if args.json else show(batch, path))
        return 0

    if args.command == 'record':
        raw = sys.stdin.read()
        try:
            answers = json.loads(raw)
        except ValueError as exc:
            print('JSON 으로 읽을 수 없습니다: %s' % exc, file=sys.stderr)
            return 2
        problems = record(batch, path, answers)
        if problems:
            print('기록하지 않았습니다. 고친 뒤 전체를 다시 기록하세요:', file=sys.stderr)
            for problem in problems:
                print('  - %s' % problem, file=sys.stderr)
            return 2

    verdicts = semantic.read_verdicts(path)
    if verdicts is None:
        print('아직 기록된 판정이 없습니다: %s' % semantic.verdicts_path(path), file=sys.stderr)
        return 2
    print(summary(batch, verdicts))
    return 0


if __name__ == '__main__':
    sys.exit(main())
