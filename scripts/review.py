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

from lib import fmt, semantic  # noqa: E402
from lib.candidate import FALSE_POSITIVE, VALID, VERDICTS, VIOLATION  # noqa: E402

# the order counts are read in: what the main agent acts on first
ORDER = (VIOLATION, VALID, FALSE_POSITIVE)
HAND_BACK = '메인 에이전트에게 돌려줄 것'


def record_command(path):
    return fmt.command('review.py', 'record', '"%s"' % path.replace(os.sep, '/'))


def where(item):
    return '%s:%d' % (item['file'], item['line']) if item.get('line') else item['file']


def show(batch, path):
    """A Markdown document for the reviewer, so its headings stay Markdown
    (docs/output-format.md 6); the pieces inside follow the common grammar."""
    items = batch['items']
    out = ['# ' + fmt.header('review show', ['후보 %d건' % len(items), 'repo %s' % batch['repo']]),
           '']
    by_rule = {}
    for item in items:
        by_rule.setdefault(item['rule_id'], []).append(item)
    for rule_id, found in by_rule.items():
        rule = batch['rules'][rule_id]
        out += ['## ' + fmt.finding_head(rule['severity'], rule_id, rule['title']), '',
                '#### 판정 기준', rule['instruction'].strip(), '']
        for item in found:
            out += ['### 후보 %d — %s' % (item['id'], where(item)),
                    '    %s' % item['snippet'], '']
            for section in item['context']['sections']:
                out += ['#### %s' % section['title'], section['text'], '']
    # ponytail: a fence, not the 4-space block: an indented `JSON` would not
    # end the heredoc if the reviewer pasted it as shown
    out += ['## 다음', '판정을 모두 적어 한 번에 기록하세요:', '', '```bash',
            "%s <<'JSON'" % record_command(path),
            '[' + ',\n '.join('{"id": %d, "verdict": "…", "reason": "…"}' % item['id']
                              for item in items) + ']',
            'JSON', '```', '',
            '- verdict: VIOLATION (실제 위반) · VALID (위반 아님) · FALSE_POSITIVE (게이트가 잘못 잡음)',
            '- 확신이 없으면 VALID 입니다.']
    return '\n'.join(out)


def show_json(batch, path):
    return fmt.envelope('review-show', {'candidates': len(batch['items']),
                                        'rules': len(batch['rules'])},
                        {'path': path.replace(os.sep, '/'), 'batch': batch},
                        steps=[fmt.Step('판정을 모두 적어 한 번에 기록', record_command(path))])


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


def summary(batch, verdicts, command='summary', style=fmt.PLAIN):
    """`record` and `summary` text: the counts, then only the violations,
    grouped by rule, for the reviewer to hand back as they are."""
    counts = {v: 0 for v in VERDICTS}
    for v in verdicts.values():
        counts[v['verdict']] = counts.get(v['verdict'], 0) + 1
    lead = '판정 %d건%s' % (len(verdicts), ' 기록' if command == 'record' else '')
    head = [fmt.header('review ' + command, [lead] + ['%s %d' % (k, counts[k]) for k in ORDER],
                       style=style)]
    violations = sorted((v for v in verdicts.values() if v['verdict'] == VIOLATION),
                        key=lambda v: (v['file'], v['line'] or 0))
    if not violations:
        return style.finish(fmt.blocks(head, [fmt.section(HAND_BACK, style=style),
                                              fmt.item_head('pass', '위반 없음', style)]))
    by_rule = {}
    for v in violations:
        by_rule.setdefault(v['rule_id'], []).append(v)
    groups = []
    for rule_id, found in by_rule.items():
        rule = batch['rules'].get(rule_id) or {}
        lines = [fmt.finding_head(rule.get('severity') or 'error', rule_id,
                                  rule.get('title') or rule_id, style)]
        for v in found:
            lines.append(fmt.location(v['file'], v['line'], style=style))
            lines += fmt.aux('이유', v['reason'], style=style)
        groups.append(lines)
    groups[0] = [fmt.section(HAND_BACK, 'VIOLATION 만', style)] + groups[0]
    return style.finish(fmt.blocks(head, *groups))


def main():
    parser = argparse.ArgumentParser(description='convention-guard 의미 판정 배치 도구')
    parser.add_argument('command', choices=['show', 'record', 'summary'])
    parser.add_argument('batch', help='배치 파일 경로 (Stop 훅이나 scan.py --review 가 알려준 경로)')
    parser.add_argument('--json', action='store_true', help='show: 배치를 JSON 봉투로 출력')
    parser.add_argument('--no-color', action='store_true', help='record, summary: 색을 끔')
    args = parser.parse_args()

    path = os.path.abspath(args.batch)
    try:
        batch = semantic.read_batch(path)
    except (OSError, ValueError) as exc:
        fmt.eprint('error', '배치를 읽을 수 없습니다: %s' % exc)
        return 2

    if args.command == 'show':
        print(fmt.dumps(show_json(batch, path)) if args.json else show(batch, path))
        return 0

    if args.command == 'record':
        raw = sys.stdin.read()
        try:
            answers = json.loads(raw)
        except ValueError as exc:
            fmt.eprint('error', 'JSON 으로 읽을 수 없습니다: %s' % exc)
            return 2
        problems = record(batch, path, answers)
        if problems:
            fmt.eprint('error', '기록하지 않았습니다 — 고친 뒤 전체를 다시 기록하세요')
            for problem in problems:
                print('  - %s' % problem, file=sys.stderr)
            return 2

    verdicts = semantic.read_verdicts(path)
    if verdicts is None:
        fmt.eprint('error', '아직 기록된 판정이 없습니다: %s' % semantic.verdicts_path(path))
        return 2
    print(summary(batch, verdicts, args.command,
                  fmt.Style.for_stream(no_color=args.no_color)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
