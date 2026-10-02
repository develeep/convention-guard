"""Turning a pipeline result into words: the Stop hook's reason, the CLI
report, and the JSON form. No decisions are made here; the shapes come from
fmt.py (docs/output-format.md)."""

import os

from . import fmt
from .gitdiff import MAX_BYTES

# Hook output past 10k characters is spilled to a file and replaced by a
# preview, which would hide the actual findings.
REASON_LIMIT = 8000

# anchors that point at a file or a change set, not at a line (F4)
FILE_LEVEL = ('absent', 'paired')


def script_path(name):
    return fmt.script(name)


def dismiss_hint(key):
    """The exact command for one candidate: the key pins the code, no re-scan."""
    return fmt.command('dismiss.py', '--key', key, '--by', 'agent', '--reason', '"<한 줄 이유>"')


def cand_line(rule, cand):
    """The line to show: None for a file- or change-level candidate, whose
    detector line (1) is a placeholder. Keys and fingerprints never use it."""
    return None if rule.get('kind') in FILE_LEVEL else cand.line


def _lint_block(failures, max_lines, carried_text=None):
    out = []
    for fail in failures:
        out.append('  $ %s' % fail['cmd'])
        out += fmt.clip_lines(['    %s' % line for line in fail['output'].split('\n')],
                              max_lines, indent=4)
        if carried_text and fail.get('carried'):
            out += fmt.aux('참고', carried_text % fail['carried'])
    return out


def _lint_notes(notes, style=fmt.PLAIN):
    if not notes:
        return []
    return ([fmt.section('린터 참고', '이번 변경 밖에서 찾은 것 (차단하지 않음)', style)]
            + _lint_block(notes, 5))


def _warnings(warnings, limit=5, style=fmt.PLAIN):
    if not warnings:
        return []
    out = [fmt.section('검사 경고', style=style)]
    out += [fmt.item_head('warn', w, style) for w in warnings[:limit]]
    if len(warnings) > limit:
        out.append(fmt.more(len(warnings) - limit, '건', indent=0))
    return out


def _finding(rule, cands, notes=(), style=fmt.PLAIN, guidance=True, more=0):
    out = [fmt.finding_head(rule['severity'], rule['id'], rule['title'], style)]
    out += [fmt.location(c.file, cand_line(rule, c), c.snippet, style=style) for c in cands]
    if more:
        out.append(fmt.more(more, '곳'))
    if guidance and (rule.get('message') or '').strip():
        out += fmt.aux('안내', rule['message'], style=style)
    for note in notes:
        out += fmt.aux('참고', note, style=style)
    return out


def review_section(review, skipped=False):
    """(section lines, ■ 다음 step): hand one command to the reviewer agent."""
    counts = {}
    for item in review['items']:
        counts[item['rule_id']] = counts.get(item['rule_id'], 0) + 1
    out = [fmt.section('판정 대기', '후보 %d건 (%s)' % (
        len(review['items']), ', '.join('%s %d' % kv for kv in sorted(counts.items())))),
        '  정규식만으로는 위반인지 알 수 없는 후보입니다.']
    if skipped:
        out += fmt.aux('참고', '지난번 판정 요청이 실행되지 않았습니다. 이번에는 꼭 판정을 맡기세요.')
    notes = ['나머지 %d건은 예산 때문에 다음 판정으로 미뤘습니다' % review['deferred']] \
        if review.get('deferred') else []
    step = fmt.Step('convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 '
                    '전달해 판정을 맡기세요. 돌려준 VIOLATION 만 고치세요.',
                    fmt.command('review.py', 'show', '"%s"' % review['batch']),
                    notes)
    return out, step


def hook_header(word, parts, kind='error'):
    """F1 for the hook: `convention-guard ✖ 차단 — a · b`."""
    return fmt.header(None, parts, status=(kind, word))


def hook_reason(lint_failures, lint_notes, errors, warns, repeats=frozenset(), review=None,
                warnings=(), lint_count=None, info_count=0, more=None, hidden_rules=(0, 0)):
    """errors/warns: [(rule, [Candidate])]. repeats: rule ids raised last turn.
    more: {rule id: locations not shown}; hidden_rules: (error, warn) rules not shown."""
    more = more or {}
    lint_count = len(lint_failures) if lint_count is None else lint_count
    head = hook_header('차단', [
        '린터 실패 %d' % lint_count if lint_failures else '',
        'error %d' % len(errors), 'warn %d' % len(warns),
        'info %d' % info_count if info_count else '',
        '판정 대기 %d' % len(review['items']) if review else '',
        '검사 경고 %d' % len(warnings) if warnings else ''])
    groups = [[head]]
    if lint_failures:
        groups.append([fmt.section('린터 실패', '확정 위반입니다. 먼저 고치세요')] + _lint_block(
            lint_failures, 20, '같은 파일의 기존 코드에 %d건 더 있지만 이번 변경이 아니라 차단하지 않았습니다'))

    def render(title, desc, hits, hidden):
        for index, (rule, cands) in enumerate(hits):
            notes = ['지난 턴에도 지적했습니다'] if rule['id'] in repeats else []
            if rule.get('review'):
                notes.append('리뷰어 판정 VIOLATION')
            lines = _finding(rule, cands, notes, more=more.get(rule['id'], 0))
            groups.append(([fmt.section(title, desc)] if not index else []) + lines)
        if hits and hidden:
            groups[-1] = groups[-1] + [fmt.more(hidden, '개 규칙')]

    render('지적', '고치거나 기각하세요', errors, hidden_rules[0])
    render('참고', '차단하지 않습니다', warns, hidden_rules[1])
    step = None
    if review:
        lines, step = review_section(review)
        groups.append(lines)
    groups += [_lint_notes(lint_notes), _warnings(warnings)]

    steps = []
    first = (errors or warns or [None])[0]
    if first:
        steps += [fmt.Step('후보는 정규식으로 좁힌 것이라 오탐이 있을 수 있습니다. 코드를 보고 위반이면 고치세요.'),
                  fmt.Step('오탐이면 고치지 말고 기각으로 남기세요. 코드가 그대로인 동안 다시 지적하지 않습니다.',
                           dismiss_hint(first[1][0].key),
                           ['다른 위치는 --key 대신 --rule <규칙id> --file <파일> --line <줄>'])]
    steps += [step, fmt.Step('끝내면 같은 범위를 다시 검사해 남은 것과 새로 생긴 것만 알립니다.')]
    groups.append(fmt.next_section(steps))
    return clip_reason(fmt.blocks(*groups))


def verify_reason(outcome, last_chance, review=None, skipped=False, warnings=()):
    """The re-scan after a block: what is left, and what the fix introduced."""
    counts = outcome.counts()
    head = hook_header('재검증 차단', [
        '고쳐짐 %d' % counts['fixed'], '기각 %d' % counts['dismissed'],
        '남음 %d' % counts['still'], '새로 생김 %d' % counts['new'],
        '판정 대기 %d' % len(review['items']) if review else '',
        '검사 경고 %d' % len(warnings) if warnings else ''])
    groups = [[head]]

    def render(title, items):
        if not items:
            return
        by_rule = {}
        for meta in items.values():
            by_rule.setdefault((meta['rule_id'], meta['title']), []).append(meta)
        first = True
        for (rule_id, title_text), metas in sorted(by_rule.items()):
            lines = [fmt.section(title)] if first else []
            first = False
            if rule_id == 'lint':
                lines += [fmt.item_head('error', '린터 실패'), '  $ %s' % title_text]
                lines += ['    %s' % meta['snippet'] for meta in metas]
            else:
                lines.append(fmt.finding_head(metas[0]['severity'], rule_id, title_text))
                lines += [fmt.location(m['file'], m['line'], m['snippet'])
                          for m in sorted(metas, key=lambda m: (m['file'], m['line'] or 0))]
            groups.append(lines)

    blocking = outcome.blocking()
    render('남음', {k: v for k, v in outcome.still.items() if k in blocking})
    render('새로 생김', {k: v for k, v in outcome.new.items() if k in blocking})
    step = None
    if review:
        lines, step = review_section(review, skipped)
        groups.append(lines)
    groups.append(_warnings(warnings))

    first = next((k for k in sorted(blocking) if not k.startswith('lint:')), None)
    steps = []
    if first:
        steps.append(fmt.Step('위반이면 고치고, 오탐이면 고치지 말고 기각으로 남기세요.', dismiss_hint(first)))
    if any(k.startswith('lint:') for k in blocking):
        steps.append(fmt.Step('린터 실패는 기각할 수 없습니다. 고치세요.'))
    steps.append(step)
    if last_chance:
        steps.append(fmt.Step('이번이 마지막 재검증입니다. 다음에 끝낼 때는 남은 항목을 기록만 하고 '
                              '차단하지 않습니다.'))
    groups.append(fmt.next_section(steps))
    return clip_reason(fmt.blocks(*groups))


def autofix_section(fixes):
    """■ 자동 수정 lines: one `✔ rule` head per rule, the fixed lines under it."""
    out = [fmt.section('자동 수정', '%d건, 이 파일들은 편집 전에 다시 읽으세요' % len(fixes))]
    by_rule = {}
    for fix in fixes:
        by_rule.setdefault(fix.rule_id, []).append(fix)
    for rule_id, rule_fixes in by_rule.items():
        out.append(fmt.item_head('pass', rule_id))
        out += [fmt.location(f.file, f.line, f.after) for f in rule_fixes]
    return out


def with_section(reason, lines):
    """`reason` with a section right after its header line."""
    head, _, rest = reason.partition('\n\n')
    return clip_reason(fmt.blocks([head], lines, [rest] if rest else []))


def clip_reason(text):
    if len(text) > REASON_LIMIT:
        cut = text.rfind('\n', 0, REASON_LIMIT)
        text = text[:cut if cut > 0 else REASON_LIMIT] + '\n… 이하 생략 — 위 항목부터 처리하세요'
    return text


# ---------------------------------------------------------------- CLI

def findings(hits):
    return [{'rule_id': rule['id'], 'title': rule['title'], 'severity': rule['severity'],
             'source': rule['source'], 'guidance': rule.get('message') or '',
             'locations': [{'file': c.file, 'line': cand_line(rule, c), 'snippet': c.snippet,
                            'key': c.key} for c in cands]}
            for rule, cands in hits]


def scan_steps(data, rerun, review_requested):
    """■ 다음 for scan. rerun(*flags) -> the scan command with the user's scope."""
    steps = []
    if data['fixes'] and not data['fixes_applied']:
        steps.append(fmt.Step('자동 수정을 적용하려면:', rerun('--fix', '--write')))
    review, semantic = data['review'], data['scope']['semantic']
    if review and review['batch']:
        notes = ['나머지 %d건은 예산 때문에 다음 판정으로 미뤘습니다' % review['deferred']] \
            if review['deferred'] else []
        steps.append(fmt.Step('convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 '
                              '전달해 판정을 맡기세요. 돌려준 VIOLATION 만 고치세요.',
                              fmt.command('review.py', 'show', '"%s"' % review['batch']), notes))
    elif review and review['deferred']:
        steps.append(fmt.Step('판정 대기 %d건은 예산 때문에 미뤘습니다. 다시 실행하세요:'
                              % review['deferred'], rerun('--review')))
    elif semantic and not review_requested:
        steps.append(fmt.Step('semantic 규칙 후보 %d건은 판정하지 않았습니다. 판정하려면:' % semantic,
                              rerun('--review')))
    return steps


def _scan_lint(lint, style):
    groups = []
    if lint['failures']:
        groups.append([fmt.section('린터 실패', '이번 변경 줄에서 확정 위반', style)]
                      + _lint_block(lint['failures'], 15, '기존 코드에 %d건 더 — 차단 대상 아님'))
    return groups


def render_text(data, steps, style=fmt.PLAIN, fix_diff='', unchecked=None,
                show_guidance=True):
    """scan's text form of the --json envelope `data`."""
    scope, summary = data['scope'], data['summary']
    head = fmt.header('scan', [scope['label'], '파일 %d개' % scope['file_count'],
                               '스택 %s' % ', '.join(scope['stacks']) if scope['stacks']
                               else '스택 감지 실패',
                               '규칙 %d/%d' % (scope['rules_applicable'], scope['rules_total'])],
                      style=style)
    groups = [[head]] + _scan_lint(data['lint'], style)
    for index, f in enumerate(data['findings']):
        lines = [fmt.section('지적', style=style)] if not index else []
        lines.append(fmt.finding_head(f['severity'], f['rule_id'], f['title'], style))
        lines += [fmt.location(loc['file'], loc['line'], loc['snippet'], style=style)
                  for loc in f['locations']]
        if show_guidance and f['guidance'].strip():
            lines += fmt.aux('안내', f['guidance'], style=style)
        groups.append(lines)
    if data['lint']['notes']:
        groups.append(_lint_notes(data['lint']['notes'], style))
    if fix_diff:
        desc = ('%d건 적용함 (아래 결과는 적용 후 남은 것)' if data['fixes_applied']
                else '%d건 미리보기') % len(data['fixes'])
        groups.append([fmt.section('자동 수정', desc, style)] + fix_diff.split('\n'))
    warnings = [unchecked] if isinstance(unchecked, str) else list(unchecked or ())
    if warnings:
        groups.append(_warnings(warnings, style=style))
    groups.append(fmt.next_section(steps, style))
    counts = {s: summary[s] for s in fmt.SEVERITIES}
    extra = ['린터 실패 %d' % summary['lint_failures']] if summary['lint_failures'] else []
    groups.append([fmt.summary(counts, extra, style)])
    return fmt.blocks(*groups)


# ---------------------------------------------------------------- notices

ENGINE_MISSING = {'disabled': '꺼짐', 'unsupported': '미지원 플랫폼', 'installing': '설치 중',
                  'failed': '설치 실패', 'not_installed': '설치 전',
                  'import_failed': '불러오기 실패'}


def unchecked_note(unchecked, limit=None, short=False):
    """'구조 미확인 2개 파일 — a.php, b.php (...)', or None when there is none.
    short: the systemMessage form, '구조 미확인 2개 파일 (a.php, b.php)'.

    A file whose structure could not be read had its conditions skipped, so
    its candidates came through unfiltered. Saying nothing would let that read
    as a clean pass (NFR-02.2, US-06).
    """
    if not unchecked:
        return None
    shown, folded = unchecked.summary(limit)
    listed = ', '.join(shown) + (' 외 %d개' % folded if folded else '')
    missing = sorted({(unchecked.reason(f) or '').split(':', 1)[1] for f in unchecked.files()
                      if (unchecked.reason(f) or '').startswith('engine_missing:')})
    if missing:
        # the whole layer is missing, not one file: say what to do about it
        why = ENGINE_MISSING.get(missing[0], missing[0])
        if short:
            return '구조 엔진 없음 (%s) — 구조 미확인 %d개 파일 (%s)' % (why, len(unchecked), listed)
        return ('구조 엔진 없음 (%s) — 구조 미확인 %d개 파일 — %s (구조 조건을 적용하지 못해 후보를 '
                '그대로 올렸습니다. 설치는 scripts/engine.py ensure)' % (why, len(unchecked), listed))
    if short:
        return '구조 미확인 %d개 파일 (%s)' % (len(unchecked), listed)
    return ('구조 미확인 %d개 파일 — %s (구조 조건을 적용하지 못해 후보를 그대로 올렸습니다)'
            % (len(unchecked), listed))


def too_large_note(paths, limit=None, short=False):
    """'큰 파일 미검사 1개 파일 — big.php (…)', or None when there is none.

    A file past the size cap was not read at all, so no rule saw it. That is
    not a pass and must not read like one (R20).
    """
    if not paths:
        return None
    listed = _listed(paths, limit)
    if short:
        return '큰 파일 미검사 %d개 파일 (%s)' % (len(paths), listed)
    return ('큰 파일 미검사 %d개 파일 — %s (%dKB 를 넘어 규칙을 적용하지 않았습니다)'
            % (len(paths), listed, MAX_BYTES // 1000))


GAPS = (
    ('post_missing', '관찰 누락 %d개 파일 — 실행 후 기록 없음 (%s, 에이전트 변경으로 보고 검사)'),
    ('pre_missing', '관찰 누락 %d개 파일 — 실행 전 기록 없음 (%s, 그 사이 다른 변경과 구분 못 함)'),
    ('tree_failed', '작업 트리 관찰 실패 %d회 (%s — 바뀐 파일을 모름)'),
    ('unknown_change', '출처 미확인 변경 %d개 파일 — 에이전트 도구 밖에서 바뀜, 검사 안 함 (%s)'),
    ('outside_root', '검사되지 않음 %d개 파일 (레포 밖: %s)'),
    ('not_a_repo', 'git 레포가 아니라 검사하지 않음 %d곳 (%s)'),
    ('collect_error', '수집 훅 오류 %d회 (%s)'),
)


def gap_notes(issues, limit=3):
    """One note per kind of observation gap the ledger recorded (ledger.py).

    What the collect hooks did not see cannot be passed silently: a Stop that
    says nothing would read exactly like a clean check (design §2).
    """
    by_kind = {}
    for kind, path, detail in issues:
        by_kind.setdefault(kind, []).append(path or detail or '?')
    notes = []
    for kind, text in GAPS:
        found = by_kind.get(kind)
        if not found:
            continue
        counted = found if kind in ('tree_failed', 'collect_error') else list(dict.fromkeys(found))
        shown = list(dict.fromkeys(counted))
        notes.append(text % (len(counted), _listed(shown, limit)))
    return notes


def _listed(paths, limit):
    shown = list(paths[:limit]) if limit else list(paths)
    folded = len(paths) - len(shown)
    return ', '.join(shown) + (' 외 %d개' % folded if folded else '')
