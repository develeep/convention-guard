"""Turning a pipeline result into words: the Stop hook's reason, the CLI
report, and the JSON form. No decisions are made here."""

import os

from .paths import plugin_root

# Hook output past 10k characters is spilled to a file and replaced by a
# preview, which would hide the actual findings.
REASON_LIMIT = 8000


def script_path(name):
    return os.path.join(plugin_root(), 'scripts', name).replace(os.sep, '/')


def dismiss_hint(key):
    """The exact command for one candidate: the key pins the code, no re-scan."""
    return ('python3 "%s" --key %s --by agent --reason "<한 줄 이유>"'
            % (script_path('dismiss.py'), key))


def _lint_block(out, failures, max_lines, header):
    out.append(header)
    for fail in failures:
        out.append('  $ %s' % fail['cmd'])
        for line in fail['output'].split('\n')[:max_lines]:
            out.append('    %s' % line)
        if fail.get('carried'):
            out.append('    (같은 파일의 기존 코드에 %d건 더 있지만 이번 변경이 '
                       '아니라 차단하지 않았습니다)' % fail['carried'])
    out.append('')


def review_section(review, skipped=False):
    """Ask the main agent to delegate judgment -- one line to hand over."""
    counts = {}
    for item in review['items']:
        counts[item['rule_id']] = counts.get(item['rule_id'], 0) + 1
    out = ['■ 심층 판정 필요 — 후보 %d건 (%s)'
           % (len(review['items']), ', '.join('%s %d' % kv for kv in sorted(counts.items())))]
    if skipped:
        out.append('  지난번 판정 요청이 실행되지 않았습니다. 이번에는 꼭 판정을 맡기세요.')
    out += ['  정규식만으로는 위반인지 알 수 없는 후보입니다. convention-guard:convention-reviewer',
            '  에이전트에게 아래 명령 한 줄을 그대로 전달해 판정을 맡기세요:',
            '    python3 "%s" show "%s"' % (script_path('review.py'),
                                           review['batch'].replace(os.sep, '/')),
            '  에이전트가 돌려준 VIOLATION 만 고치세요. 후보 파일을 직접 다시 판정할 필요는 없습니다.']
    if review.get('deferred'):
        out.append('  (나머지 %d건은 예산 때문에 다음 판정으로 미뤘습니다)' % review['deferred'])
    out.append('')
    return out


def hook_reason(lint_failures, lint_notes, errors, warns, repeats=frozenset(), review=None,
                warnings=()):
    """errors/warns: [(rule, [Candidate])]. repeats: rule ids raised last turn."""
    out = []
    if lint_failures:
        _lint_block(out, lint_failures, 20, '■ 린터 실패 — 확정 위반입니다. 먼저 고치세요.')

    def render(title, hits):
        out.append(title)
        for rule, cands in hits:
            mark = ' ← 지난 턴에 지적했는데 그대로입니다' if rule['id'] in repeats else ''
            label = ' (리뷰어 판정: 위반)' if rule.get('review') else ''
            out.append('  [%s] %s%s%s' % (rule['id'], rule['title'], label, mark))
            for cand in cands:
                out.append('    %s:%d  %s' % (cand.file, cand.line, cand.snippet))
            for line in (rule.get('message') or '').strip().split('\n'):
                if line:
                    out.append('    > %s' % line)
            out.append('')

    if errors:
        render('■ 규칙 후보 (error)', errors)
    if warns:
        render('■ 참고 (warn — 이것만으로는 차단하지 않습니다)', warns)
    if lint_notes:
        out.append('■ 참고 — 린터가 이번 변경 밖에서 찾은 것 (차단하지 않습니다)')
        for fail in lint_notes:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:5]:
                out.append('    %s' % line)
        out.append('')
    if review:
        out += review_section(review)
    if warnings:
        out.append('■ 검사 경고')
        for warning in warnings[:5]:
            out.append('  %s' % warning)
        out.append('')

    first = (errors or warns or [None])[0]
    if first:
        out.append('위 규칙 후보는 정규식으로 좁힌 것이라 오탐이 있을 수 있습니다.')
        out.append('각 항목이 실제 위반인지 코드를 보고 판단하세요. 위반이면 고치세요.')
        out.append('오탐이면 고치지 말고 아래 명령으로 남기세요. 그 코드가 그대로인 동안')
        out.append('다시 지적하지 않고, 로그에는 "기각"으로 기록됩니다.')
        out.append('  %s' % dismiss_hint(first[1][0].key))
        out.append('  다른 위치는 --key 대신 --rule <규칙id> --file <파일> --line <줄> 로 지정합니다.')
    out.append('처리한 뒤 완료하면 같은 범위를 다시 검사해, 남았거나 수정하면서 새로 생긴 것만 알려드립니다.')
    return clip_reason('\n'.join(out))


def verify_reason(outcome, last_chance, review=None, skipped=False):
    """The re-scan after a block: what is left, and what the fix introduced."""
    counts = outcome.counts()
    out = ['■ 재검증 — 고쳐짐 %d / 기각 %d / 그대로 %d / 새로 생김 %d'
           % (counts['fixed'], counts['dismissed'], counts['still'], counts['new']), '']

    def render(title, items):
        if not items:
            return
        out.append(title)
        by_rule = {}
        for meta in items.values():
            by_rule.setdefault((meta['rule_id'], meta['title']), []).append(meta)
        for (rule_id, title_text), metas in sorted(by_rule.items()):
            if rule_id == 'lint':
                out.append('  $ %s' % title_text)
                for meta in metas:
                    out.append('    %s' % meta['snippet'])
                continue
            out.append('  [%s] %s' % (rule_id, title_text))
            for meta in sorted(metas, key=lambda m: (m['file'], m['line'])):
                out.append('    %s:%d  %s' % (meta['file'], meta['line'], meta['snippet']))
        out.append('')

    blocking = outcome.blocking()
    render('■ 아직 그대로입니다', {k: v for k, v in outcome.still.items() if k in blocking})
    render('■ 수정하면서 새로 생겼습니다', {k: v for k, v in outcome.new.items() if k in blocking})
    if review:
        out += review_section(review, skipped)
    first = next((k for k in blocking if not k.startswith('lint:')), None)
    if blocking:
        out.append('위반이면 고치고, 오탐이면 고치지 말고 기각으로 남기세요.')
    if first:
        out.append('  %s' % dismiss_hint(first))
    if last_chance:
        out.append('이번이 마지막 재검증입니다. 다음 완료 때는 남은 항목을 기록만 하고 차단하지 않습니다.')
    return clip_reason('\n'.join(out))


def autofix_section(fixes):
    out = ['■ 자동 수정 %d건 — 아래 줄을 규칙대로 고쳤습니다. 이 파일들은 편집 전에 다시 읽으세요.'
           % len(fixes)]
    for fix in fixes:
        out.append('  %s:%d  [%s]  %s' % (fix.file, fix.line, fix.rule_id, fix.after.strip()))
    return '\n'.join(out) + '\n\n'


def clip_reason(text):
    if len(text) > REASON_LIMIT:
        text = text[:REASON_LIMIT] + '\n… (이하 생략 — 위 항목부터 처리하세요)'
    return text


# ---------------------------------------------------------------- CLI

class Palette:
    def __init__(self, color=True):
        on = bool(color)
        self.sev = {'error': '\033[31m' if on else '', 'warn': '\033[33m' if on else '',
                    'info': '\033[36m' if on else ''}
        self.dim = '\033[2m' if on else ''
        self.bold = '\033[1m' if on else ''
        self.reset = '\033[0m' if on else ''


def findings(hits):
    return [{'rule_id': rule['id'], 'title': rule['title'], 'severity': rule['severity'],
             'source': rule['source'], 'guidance': rule.get('message') or '',
             'locations': [c.to_dict() for c in cands]}
            for rule, cands in hits]


def render_text(report, palette, show_guidance=True):
    p = palette
    out = []
    head = report['head']
    out.append('%sconvention-guard%s  %s' % (p.bold, p.reset, head['label']))
    out.append('%s%s  |  스택: %s  |  검사 대상 %d개 파일%s'
               % (p.dim, head['root'], ', '.join(head['stacks']) or '감지 실패',
                  head['file_count'], p.reset))
    if head['lint_failures']:
        out.append('')
        out.append('%s린터 실패 — 이번 변경 줄에서 확정 위반%s' % (p.sev['error'], p.reset))
        for fail in head['lint_failures']:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:15]:
                out.append('    %s%s%s' % (p.dim, line, p.reset))
            if fail.get('carried'):
                out.append('    %s(기존 코드에 %d건 더 — 차단 대상 아님)%s'
                           % (p.dim, fail['carried'], p.reset))
    if head.get('lint_notes'):
        out.append('')
        out.append('%s린터가 이번 변경 밖에서 찾은 것 (차단하지 않음)%s' % (p.dim, p.reset))
        for fail in head['lint_notes']:
            out.append('  $ %s' % fail['cmd'])
            for line in fail['output'].split('\n')[:5]:
                out.append('    %s%s%s' % (p.dim, line, p.reset))
    out.append('')

    if not report['findings']:
        out.append('  지적 사항 없음')
    for finding in report['findings']:
        sev = finding['severity']
        out.append('%s%-5s%s %s  %s%s%s' % (p.sev.get(sev, ''), sev, p.reset,
                                            finding['title'], p.dim, finding['rule_id'],
                                            p.reset))
        for loc in finding['locations']:
            out.append('      %s:%d  %s%s%s' % (loc['file'], loc['line'], p.dim,
                                                loc['snippet'], p.reset))
        if show_guidance and finding.get('guidance'):
            for line in finding['guidance'].split('\n'):
                out.append('      %s→ %s%s' % (p.dim, line, p.reset))
        out.append('')

    counts = report['counts']
    out.append('%s요약%s  error %d / warn %d / info %d   (규칙 %d개 중 %d개 적용)'
               % (p.bold, p.reset, counts['error'], counts['warn'], counts['info'],
                  head['rules_total'], head['rules_applicable']))
    if head.get('semantic'):
        out.append('%s      semantic 규칙 후보 %d건은 이 명령으로 판정되지 않습니다%s'
                   % (p.dim, head['semantic'], p.reset))
    return '\n'.join(out)
