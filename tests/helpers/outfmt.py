"""Checks for docs/output-format.md, one function per rule (F1..F16).

Each check returns a list of problems (empty = conforms), so a test can show
exactly which line broke which rule.
"""

import json
import os
import re
import unicodedata

from . import ROOT

ICON = {'error': '✖', 'warn': '⚠', 'info': 'ℹ'}
SEVERITY_HEAD = re.compile(r'^(✖ error|⚠ warn|ℹ info)\[[^\]\s]+\]: \S')
OLD_SYMBOLS = ('→', '←', '●', '[PASS', '[FAIL', '[WARN', '[SKIP', '[MANUAL', '[error]', '[warn]')
OLD_TERMS = (re.compile(r'그대로 \d'), re.compile('심층 판정'), re.compile('판정 대기 후보'),
             re.compile(r'신규'))
AUX = re.compile(r'^\s+= (안내|참고|이유|조치): ')
LOCATION = re.compile(r'^  (?P<file>[^\s:]+?)(?::(?P<line>\d+))?(?:  .*)?$')
SUMMARY = re.compile(r'^(?:(?P<icon>[✖⚠ℹ]) (?P<total>\d+)건 \(error (?P<error>\d+) · '
                     r'warn (?P<warn>\d+) · info (?P<info>\d+)\)(?: · 린터 실패 \d+)?'
                     r'|✔ 지적 없음)$')
HOOK_HEAD = re.compile(r'^convention-guard [✖⚠ℹ✔] (차단|재검증 차단|재검증 통과|재검증 종료|기록|건너뜀) — \S')
STDERR = re.compile(r'^convention-guard: (error|warn): \S')


def plugin_version():
    with open(os.path.join(ROOT, '.claude-plugin', 'plugin.json'), encoding='utf-8') as fh:
        return json.load(fh)['version']


def width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in text)


def at_width(text, col):
    """The character that starts at display column `col` (None past the end)."""
    pos = 0
    for ch in text:
        if pos == col:
            return ch
        pos += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        if pos > col:
            return None
    return None


# ---------------------------------------------------------------- F1 header

def header(text, command):
    first = text.split('\n', 1)[0]
    if not re.match(r'^convention-guard %s(?: --?[a-z-]+)? — \S' % re.escape(command), first):
        return ['F1 머리말이 아님: %r' % first]
    return []


def hook_header(line):
    return [] if HOOK_HEAD.match(line or '') else ['F1 훅 머리말이 아님: %r' % line]


# ---------------------------------------------------------------- F2 sections

def sections(text):
    """[(title, [lines])] for every '■ ' block."""
    out, current = [], None
    for line in text.split('\n'):
        if line.startswith('■ '):
            current = (line[2:], [])
            out.append(current)
        elif current is not None:
            current[1].append(line)
    return out


def section(text, title):
    for name, lines in sections(text):
        if name == title or name.startswith(title + ' — '):
            return lines
    return None


def section_titles(text):
    problems = []
    lines = text.split('\n')
    for index, line in enumerate(lines):
        if line.startswith('■') and not re.match(r'^■ \S', line):
            problems.append('F2 섹션 제목 모양: %r' % line)
        if line.startswith('■ ') and index and lines[index - 1] != '':
            problems.append('F2 섹션 앞에 빈 줄 없음: %r' % line)
        if re.match(r'^#{1,4} ', line):
            problems.append('F2 Markdown 제목(■ 이어야 함): %r' % line)
    return problems


# ---------------------------------------------------------------- F3-F6 items

def findings(text):
    """[(head, [body lines])] for every finding head."""
    out, current = [], None
    for line in text.split('\n'):
        if re.match(r'^[✖⚠ℹ] (error|warn|info)\[', line):
            current = (line, [])
            out.append(current)
        elif current is not None:
            if line.startswith('  '):
                current[1].append(line)
            else:
                current = None
    return out


def items(text):
    """F3 heads, F4 locations, F5 aux lines, and no old severity-first lines."""
    problems = []
    for line in text.split('\n'):
        if re.match(r'^(error|warn |info ) \S', line):
            problems.append('F3 옛 강도 줄: %r' % line)
        if re.match(r'^[✖⚠ℹ] (error|warn|info)(?! {2})', line) and not SEVERITY_HEAD.match(line):
            problems.append('F3 항목 머리 모양: %r' % line)
        if re.match(r'^\s+= ', line) and not AUX.match(line):
            problems.append('F5 보조 줄 라벨: %r' % line)
        if re.search(r'^\s+[>→] ', line):
            problems.append('F5 옛 보조 줄 기호: %r' % line)
    for head, body in findings(text):
        for line in body:
            if AUX.match(line) or line.startswith('    '):
                continue
            match = LOCATION.match(line)
            if not match:
                problems.append('F4 위치 줄 모양: %r (%s)' % (line, head))
            elif match.group('line') == '0':
                problems.append('F4 줄 0: %r' % line)
    return problems


def file_level_location(text, rel):
    """A candidate with no line reads `path  snippet`, never `path:1`."""
    for _, body in findings(text):
        for line in body:
            if line.startswith('  %s:1  (' % rel):
                return ['F4 파일 단위 후보에 줄 번호: %r' % line]
    return []


def next_section(text):
    """F6: commands to run live only under '■ 다음', as `  $ cmd` lines."""
    problems = []
    for name, lines in sections(text):
        is_next = name == '다음'
        for line in lines:
            if not is_next and re.match(r'^  \$ (python3|python) ', line):
                problems.append('F6 다음 밖의 명령: %r (섹션 %s)' % (line, name))
            if is_next and line and not SUMMARY.match(line) and \
                    not re.match(r'^(- \S|  \$ \S|  = |\s{4,}\S)', line):
                problems.append('F6 다음 섹션 줄 모양: %r' % line)
    for line in text.split('\n'):
        if re.search(r'python3 "[^"]+" ', line) and not re.match(r'^\s*\$ ', line):
            if not line.startswith('    python3'):
                problems.append('F6 명령이 $ 줄이 아님: %r' % line)
    return problems


def has_command(text, fragment):
    lines = section(text, '다음') or []
    return any(line.startswith('  $ ') and fragment in line for line in lines)


# ---------------------------------------------------------------- F7 summary

def summary(text):
    last = text.rstrip('\n').split('\n')[-1]
    match = SUMMARY.match(last)
    if not match:
        return ['F7 요약 줄이 아님: %r' % last]
    if match.group('icon'):
        counts = {k: int(match.group(k)) for k in ('error', 'warn', 'info')}
        worst = next((k for k in ('error', 'warn', 'info') if counts[k]), None)
        if worst and ICON[worst] != match.group('icon'):
            return ['F7 요약 아이콘이 가장 높은 강도와 다름: %r' % last]
        if int(match.group('total')) != sum(counts.values()):
            return ['F7 합계가 맞지 않음: %r' % last]
    return []


# ---------------------------------------------------------------- F9 F10 F11 F14

def truncation(text):
    problems = []
    for line in text.split('\n'):
        if re.search(r'생략|\.\.\. \(', line) and not re.search(r'… (\d+(줄|건) 더|이하 생략)', line):
            problems.append('F9 잘림 표시 모양: %r' % line)
    return problems


def table(lines):
    """F10: header, a '─' rule, rows; every column starts at the same display column."""
    rule_at = next((i for i, line in enumerate(lines) if line.strip().startswith('─')), None)
    if rule_at is None or rule_at == 0:
        return ['F10 구분선 없음']
    rule = lines[rule_at]
    starts = [m.start() for m in re.finditer(r'─+', rule)]
    starts = [width(rule[:s]) for s in starts]
    problems = []
    header_line = lines[rule_at - 1]
    rows = [header_line]
    for line in lines[rule_at + 1:]:
        if not line.strip() or AUX.match(line):
            break
        rows.append(line)
    for row in rows:
        for col in starts[1:]:
            before = at_width(row, col - 1)
            if before not in (None, ' '):
                problems.append('F10 열 어긋남 (%d칸): %r' % (col, row))
                break
    for col in starts:
        if at_width(header_line, col) in (None, ' '):
            problems.append('F10 머리행 열 시작이 비어 있음 (%d칸): %r' % (col, header_line))
    return problems


def terms(text):
    return ['F11 쓰지 않을 말 %r: %r' % (p.pattern, line)
            for line in text.split('\n') for p in OLD_TERMS if p.search(line)]


def symbols(text):
    return ['F14 옛 기호 %r: %r' % (sym, line)
            for line in text.split('\n') for sym in OLD_SYMBOLS if sym in line]


# ---------------------------------------------------------------- F12 F13 F15

def stderr_lines(text):
    problems = []
    for line in text.split('\n'):
        if not line.strip() or line.startswith(('  ', 'usage:')) or ': error: argument' in line:
            continue
        if not STDERR.match(line):
            problems.append('F12 stderr 모양: %r' % line)
    return problems


def no_color(text):
    return ['F13 색 코드가 있음'] if '\x1b[' in text else []


def envelope(raw, command):
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return ['F15 JSON 아님: %s' % exc], None
    problems = []
    if data.get('schema') != 'convention-guard/%s@1' % command:
        problems.append('F15 schema: %r' % data.get('schema'))
    if data.get('tool') != {'name': 'convention-guard', 'version': plugin_version()}:
        problems.append('F15 tool: %r' % data.get('tool'))
    for key in ('summary', 'notes', 'next'):
        if key not in data:
            problems.append('F15 %s 없음' % key)
    for note in data.get('notes') or []:
        if set(note) != {'level', 'text'}:
            problems.append('F15 notes 항목: %r' % note)
    for step in data.get('next') or []:
        if not {'text', 'command'} <= set(step):
            problems.append('F15 next 항목: %r' % step)
    return problems, data


def text_output(text, command=None):
    """The rules every human/agent text output shares."""
    problems = []
    if command:
        problems += header(text, command)
    problems += section_titles(text) + items(text) + next_section(text)
    problems += truncation(text) + terms(text) + symbols(text) + no_color(text)
    return problems
