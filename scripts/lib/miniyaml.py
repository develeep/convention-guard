"""Dependency-free YAML subset parser.

Covers exactly what convention-guard's rule/stack files need:
  - nested mappings (indent based)
  - block sequences ("- item", "- key: value" + indented continuation)
  - inline flow sequences ([a, b]) and flow mappings ({a: b})
  - single/double quoted and plain scalars
  - block scalars (|, |-, >, >-)
  - comments, blank lines, true/false/null/int/float coercion

Not supported (deliberately): anchors, aliases, tags, multi-doc, complex keys.
If PyYAML happens to be installed, loader.py prefers it; this is the fallback
so the hook never fails on a machine without pip packages.
"""

import re


class YamlError(Exception):
    pass


_BLOCK_RE = re.compile(r'^([|>])([-+]?)(\d*)$')


def load(text):
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    # expand leading tabs only -- tabs inside scalars (Go fixtures) must survive
    lines = [ln[:len(ln) - len(ln.lstrip('\t '))].expandtabs(2)
             + ln[len(ln) - len(ln.lstrip('\t ')):] for ln in lines]
    value, _ = _parse_block(lines, 0, -1)
    return value if value is not None else {}


# ---------------------------------------------------------------- helpers

def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _skippable(line):
    s = line.strip()
    return not s or s.startswith('#')


def _next_meaningful(lines, i):
    while i < len(lines) and _skippable(lines[i]):
        i += 1
    return i


def _strip_comment(s):
    out, quote, i = [], None, 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == '\\' and quote == '"' and i + 1 < len(s):
                out.append(c)
                out.append(s[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(c)
        else:
            if c in '"\'':
                quote = c
                out.append(c)
            elif c == '#' and (not out or out[-1] in ' \t'):
                break
            else:
                out.append(c)
        i += 1
    return ''.join(out).rstrip()


def _split_key(s):
    """Return (key, rest) if s is 'key: rest', else (None, None)."""
    quote, depth, i = None, 0, 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == '\\' and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        else:
            if c in '"\'':
                quote = c
            elif c in '[{':
                depth += 1
            elif c in ']}':
                depth -= 1
            elif c == ':' and depth == 0 and (i + 1 == len(s) or s[i + 1] in ' \t'):
                return s[:i].strip(), s[i + 1:].strip()
        i += 1
    return None, None


def _split_top(s, sep=','):
    parts, cur, quote, depth = [], [], None, 0
    for i, c in enumerate(s):
        if quote:
            cur.append(c)
            if c == quote and (i == 0 or s[i - 1] != '\\'):
                quote = None
            continue
        if c in '"\'':
            quote = c
            cur.append(c)
        elif c in '[{':
            depth += 1
            cur.append(c)
        elif c in ']}':
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
    tail = ''.join(cur).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p != '']


def _unescape_double(s):
    out, i = [], 0
    mapping = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', '/': '/', '0': '\0'}
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            out.append(mapping.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _scalar(s):
    s = s.strip()
    if s == '':
        return None
    if s[0] == '"' and s[-1] == '"' and len(s) >= 2:
        return _unescape_double(s[1:-1])
    if s[0] == "'" and s[-1] == "'" and len(s) >= 2:
        return s[1:-1].replace("''", "'")
    if s[0] == '[' and s[-1] == ']':
        return [_scalar(p) for p in _split_top(s[1:-1])]
    if s[0] == '{' and s[-1] == '}':
        out = {}
        for part in _split_top(s[1:-1]):
            k, v = _split_key(part)
            if k is None:
                raise YamlError('bad flow mapping entry: %r' % part)
            out[_scalar(k)] = _scalar(v)
        return out
    low = s.lower()
    if low in ('true', 'yes', 'on'):
        return True
    if low in ('false', 'no', 'off'):
        return False
    if low in ('null', '~', ''):
        return None
    if re.fullmatch(r'[-+]?\d+', s):
        return int(s)
    if re.fullmatch(r'[-+]?\d*\.\d+([eE][-+]?\d+)?', s):
        return float(s)
    return s


def _read_block_scalar(lines, i, parent_indent, style, chomp):
    body, j = [], i
    block_indent = None
    while j < len(lines):
        line = lines[j]
        if line.strip() == '':
            body.append('')
            j += 1
            continue
        ind = _indent(line)
        if ind <= parent_indent:
            break
        if block_indent is None:
            block_indent = ind
        body.append(line[block_indent:] if len(line) >= block_indent else line.lstrip(' '))
        j += 1
    while body and body[-1] == '':
        body.pop()
    if style == '|':
        text = '\n'.join(body)
    else:
        folded, buf = [], []
        for ln in body:
            if ln.strip() == '':
                folded.append(' '.join(buf))
                buf = []
                folded.append('')
            elif ln.startswith(' '):
                folded.append(' '.join(buf))
                buf = []
                folded.append(ln)
            else:
                buf.append(ln.strip())
        if buf:
            folded.append(' '.join(buf))
        text = '\n'.join(x for x in folded if x is not None)
    if chomp != '-':
        text += '\n'
    return text, j


# ---------------------------------------------------------------- parser

def _parse_block(lines, i, parent_indent):
    i = _next_meaningful(lines, i)
    if i >= len(lines):
        return None, i
    cur = _indent(lines[i])
    if cur <= parent_indent:
        return None, i
    content = _strip_comment(lines[i].strip())
    if content == '-' or content.startswith('- '):
        return _parse_seq(lines, i, cur)
    return _parse_map(lines, i, cur)


def _parse_seq(lines, i, cur):
    items = []
    lines = list(lines)
    while True:
        i = _next_meaningful(lines, i)
        if i >= len(lines):
            break
        if _indent(lines[i]) != cur:
            break
        content = _strip_comment(lines[i].strip())
        if not (content == '-' or content.startswith('- ')):
            break
        rest = content[1:].strip()
        if rest == '':
            value, i = _parse_block(lines, i + 1, cur)
            items.append(value)
            continue
        key, _ = _split_key(rest)
        if key is not None:
            rest_indent = lines[i].index('- ') + 2
            lines[i] = ' ' * rest_indent + rest
            value, i = _parse_block(lines, i, rest_indent - 1)
            items.append(value)
            continue
        items.append(_scalar(rest))
        i += 1
    return items, i


def _parse_map(lines, i, cur):
    out = {}
    while True:
        i = _next_meaningful(lines, i)
        if i >= len(lines):
            break
        if _indent(lines[i]) != cur:
            break
        content = _strip_comment(lines[i].strip())
        if content.startswith('- '):
            break
        key, rest = _split_key(content)
        if key is None:
            raise YamlError('line %d: expected "key: value", got %r' % (i + 1, content))
        key = _scalar(key)
        m = _BLOCK_RE.match(rest) if rest else None
        if m:
            value, i = _read_block_scalar(lines, i + 1, cur, m.group(1), m.group(2))
            out[key] = value
            continue
        if rest == '':
            nxt = _next_meaningful(lines, i + 1)
            if nxt < len(lines) and _indent(lines[nxt]) > cur:
                value, i = _parse_block(lines, i + 1, cur)
                out[key] = value
            else:
                out[key] = None
                i += 1
            continue
        out[key] = _scalar(rest)
        i += 1
    return out, i
