"""The output grammar of docs/output-format.md, in one place.

Every script builds its text from these pieces so a reader (a person or an
agent) meets one shape everywhere: a header line, `■` sections, finding heads,
`파일:줄` locations, `= 라벨:` aux lines, one `■ 다음` block with `$` commands,
and a summary line. Nothing here decides anything; it only draws.
"""

import json
import os
import sys
import unicodedata

from .paths import plugin_root

TOOL = 'convention-guard'

GLYPH = {'error': '✖', 'fail': '✖', 'warn': '⚠', 'info': 'ℹ', 'pass': '✔', 'on': '✔',
         'skip': '○', 'off': '○', 'manual': '?'}
# F14: TERM=dumb gets the same text with these swapped out
ASCII = {'■': '#', '✖': 'x', '⚠': '!', 'ℹ': 'i', '✔': 'v', '○': '-', '—': '-', '·': '.',
         '…': '...', '⏎': '/', '─': '-'}
ANSI = {'error': '31', 'fail': '31', 'warn': '33', 'manual': '33', 'info': '36', 'cmd': '36',
        'pass': '32', 'on': '32', 'skip': '2', 'off': '2', 'dim': '2', 'bold': '1'}
SEVERITIES = ('error', 'warn', 'info')
AUX_LABELS = ('안내', '참고', '이유', '조치')


class Style:
    """Colour and character set for one output stream (F13, F14)."""

    def __init__(self, color=False, ascii=False):
        self.color, self.ascii = bool(color), bool(ascii)

    @classmethod
    def for_stream(cls, stream=None, no_color=False):
        stream = stream or sys.stdout
        dumb = os.environ.get('TERM') == 'dumb'
        try:
            tty = stream.isatty()
        except (AttributeError, ValueError):
            tty = False
        color = tty and not no_color and not os.environ.get('NO_COLOR') and not dumb
        return cls(color=color, ascii=dumb)

    @classmethod
    def plain(cls):
        """Hook output, files, anything that is not a terminal."""
        return cls()

    def paint(self, text, role):
        if not self.color or not text or role not in ANSI:
            return text
        return '\033[%sm%s\033[0m' % (ANSI[role], text)

    def finish(self, text):
        """The last step before printing: swap glyphs when the terminal is dumb."""
        if not self.ascii:
            return text
        return ''.join(ASCII.get(ch, ch) for ch in text)


PLAIN = Style.plain()


# ---------------------------------------------------------------- widths

def width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in text)


def pad(text, size, align='l'):
    gap = ' ' * max(0, size - width(text))
    return gap + text if align == 'r' else text + gap


# ---------------------------------------------------------------- pieces

def attrs(parts):
    return ' · '.join(p for p in parts if p)


def header(command, parts, status=None, style=PLAIN):
    """F1. `convention-guard <command> — a · b`, or for the hook
    `convention-guard <icon> <status> — a · b` with status=(kind, word)."""
    lead = style.paint(TOOL, 'bold')
    if status:
        kind, word = status
        lead += ' ' + style.paint('%s %s' % (GLYPH[kind], word), kind)
    elif command:
        lead += ' ' + command
    tail = attrs(parts)
    return '%s — %s' % (lead, style.paint(tail, 'dim')) if tail else lead


def section(title, desc=None, style=PLAIN):
    """F2."""
    return style.paint('■ %s' % (title if not desc else '%s — %s' % (title, desc)), 'bold')


def finding_head(severity, rule_id, title, style=PLAIN):
    """F3. `✖ error[core/x]: 제목`."""
    return '%s%s %s' % (style.paint('%s %s' % (GLYPH.get(severity, '?'), severity), severity),
                        style.paint('[%s]:' % rule_id, 'dim'), style.paint(title, 'bold'))


def item_head(kind, text, style=PLAIN):
    """A head that is not a finding: `✔ core/x`, `⚠ 검사 경고 문장`."""
    return '%s %s' % (style.paint(GLYPH[kind], kind), text)


def location(file, line=None, snippet='', indent=2, style=PLAIN):
    """F4. `파일:줄  스니펫`; no line for file- and change-level candidates."""
    where = file if not line else '%s:%d' % (file, line)
    snippet = (snippet or '').strip()
    return ' ' * indent + where + ('  ' + style.paint(snippet, 'dim') if snippet else '')


def aux(label, text, indent=2, style=PLAIN):
    """F5. `= 라벨: 내용`; later lines line up under the content."""
    if label not in AUX_LABELS:
        raise ValueError('aux label: %s' % label)
    lead = '= %s: ' % label
    rows = [r for r in str(text).strip().split('\n')] or ['']
    out = [' ' * indent + style.paint(lead, 'dim') + rows[0]]
    cont = ' ' * (indent + width(lead))
    out += [cont + r.strip() for r in rows[1:] if r.strip()]
    return out


def more(count, unit='줄', indent=2, command=None):
    """F9. `… 12줄 더`, optionally ` — 전체: <cmd>`."""
    text = '%s… %d%s 더' % (' ' * indent, count, unit)
    return text + (' — 전체: %s' % command if command else '')


def clip_lines(lines, limit, indent=2, unit='줄'):
    """The first `limit` lines, and an F9 marker for the rest."""
    if len(lines) <= limit:
        return list(lines)
    return list(lines[:limit]) + [more(len(lines) - limit, unit, indent)]


class Step:
    """One `■ 다음` entry: a sentence, an optional command, optional notes."""

    def __init__(self, text, command=None, notes=()):
        self.text, self.command, self.notes = text, command, list(notes)

    def to_dict(self):
        return {'text': self.text, 'command': self.command}


def next_section(steps, style=PLAIN):
    """F6. [] when there is nothing to do."""
    steps = [s for s in steps if s]
    if not steps:
        return []
    out = [section('다음', style=style)]
    for step in steps:
        out.append('- %s' % step.text)
        if step.command:
            out.append(style.paint('  $ %s' % step.command, 'cmd'))
        for note in step.notes:
            out += aux('참고', note, style=style)
    return out


def worst(counts):
    return next((s for s in SEVERITIES if counts.get(s)), None)


def summary(counts, extra=(), style=PLAIN):
    """F7. `✖ 15건 (error 8 · warn 5 · info 2)` or `✔ 지적 없음`."""
    total = sum(counts.get(s, 0) for s in SEVERITIES)
    tail = ''.join(' · %s' % e for e in extra if e)
    if not total and not tail:
        return style.paint('%s 지적 없음' % GLYPH['pass'], 'pass')
    kind = worst(counts) or 'error'
    text = '%s %d건 (%s)%s' % (GLYPH[kind], total,
                              ' · '.join('%s %d' % (s, counts.get(s, 0)) for s in SEVERITIES), tail)
    return style.paint(text, kind)


def table(headers, rows, align=None, indent=2, style=PLAIN):
    """F10. Header, `─` rule, rows; columns sized by display width."""
    align = align or ['l'] * len(headers)
    cells = [[str(c) for c in row] for row in rows]
    sizes = [max([width(h)] + [width(r[i]) for r in cells]) for i, h in enumerate(headers)]
    lead = ' ' * indent

    def line(values, paint=None):
        text = lead + '  '.join(pad(v, sizes[i], align[i]) for i, v in enumerate(values)).rstrip()
        return style.paint(text, paint) if paint else text

    out = [line(headers, 'bold'), lead + '  '.join('─' * s for s in sizes)]
    out += [line(r) for r in cells]
    return out


def blocks(*groups):
    """Join blocks (lists of lines) with one blank line; empty blocks vanish."""
    return '\n\n'.join('\n'.join(g) for g in groups if g)


# ---------------------------------------------------------------- commands, stderr

def script(name):
    return os.path.join(plugin_root(), 'scripts', name).replace(os.sep, '/')


def command(name, *args):
    """A copyable command line: `python3 "<plugin>/scripts/x.py" args`."""
    return ' '.join(['python3 "%s"' % script(name)] + [a for a in args if a])


def diag(level, text):
    """F12. `convention-guard: error: 문장`; later lines of a multi-line note
    (a YAML parse error) are indented so they read as part of it."""
    first, _, rest = str(text).partition('\n')
    out = '%s: %s: %s' % (TOOL, 'error' if level == 'error' else 'warn', first)
    return out + ''.join('\n  ' + line for line in rest.split('\n') if line.strip()) if rest else out


def eprint(level, text):
    print(diag(level, text), file=sys.stderr)


# ---------------------------------------------------------------- JSON

def version():
    for root in (plugin_root(), os.path.join(os.path.dirname(__file__), '..', '..')):
        try:
            with open(os.path.join(root, '.claude-plugin', 'plugin.json'), encoding='utf-8') as fh:
                return json.load(fh).get('version')
        except (OSError, ValueError):
            continue
    return None


def envelope(name, summary_data, body=None, notes=(), steps=()):
    """F15. The one JSON shape every --json shares."""
    out = {'schema': '%s/%s@1' % (TOOL, name), 'tool': {'name': TOOL, 'version': version()},
           'summary': summary_data}
    out.update(body or {})
    out['notes'] = [{'level': lv, 'text': tx} for lv, tx in notes]
    out['next'] = [s.to_dict() for s in steps if s]
    return out


def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2)
