"""Blade: a template with islands of PHP, read as such.

There is no Blade grammar to install, and Blade's own syntax is small, so it
is read here and only the PHP inside is handed to tree-sitter:

    {{-- ... --}}                  a comment
    {{ expr }}  {!! expr !!}       PHP expressions
    @php ... @endphp, <?php ?>     PHP statements
    @name(args)                    the arguments are a PHP expression
    @foreach ... @endforeach       a loop (also @for, @while, @forelse)
    @if ... @endif                 a branch (and the other paired directives)
    everything else                template text -- literal text, not code

Each PHP island is parsed on its own (the `php_only` grammar) and its
comments, strings, errors and functions are put back at their place in the
template.
"""

import re

from . import nodes
from .model import FileStructure, ScopeNode, Span, line_starts
from .treesitter import Collector, Offsets, _merged

LOOPS = ('foreach', 'for', 'while', 'forelse')
BRANCHES = ('if', 'unless', 'isset', 'switch', 'auth', 'guest', 'can', 'cannot', 'env',
            'production', 'error', 'push', 'once', 'canany')
TOKEN = re.compile(r'\{\{--|\{!!|@?\{\{|<\?(?:php|=)|@@|(?<![\w@])@(\w+)')


def _paren_end(text, start):
    """Index after the `)` matching the `(` at `start`, skipping PHP strings."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in '\'"':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


class Island:
    __slots__ = ('start', 'end', 'prefix', 'suffix')

    def __init__(self, start, end, prefix='', suffix=''):
        self.start, self.end, self.prefix, self.suffix = start, end, prefix, suffix


def scan(text):
    """(islands, comments, code spans, blocks) of a Blade template.
    blocks: [(kind, start, body_start, body_end, end)]."""
    islands, comments, code, blocks, stack = [], [], [], [], []
    i = 0
    while True:
        match = TOKEN.search(text, i)
        if match is None:
            break
        token, at = match.group(0), match.start()
        if token == '{{--':
            end = text.find('--}}', at + 4)
            end = len(text) if end < 0 else end + 4
            comments.append(Span(at, end))
            i = end
        elif token in ('{!!', '{{'):
            close = '!!}' if token == '{!!' else '}}'
            end = text.find(close, at + len(token))
            if end < 0:
                end = len(text)
            islands.append(Island(at + len(token), end, 'echo ', ';'))
            code.append(Span(at, min(len(text), end + len(close))))
            i = end + len(close)
        elif token.startswith('<?'):
            end = text.find('?>', at)
            end = len(text) if end < 0 else end
            islands.append(Island(at + len(token), end))
            code.append(Span(at, min(len(text), end + 2)))
            i = end + 2
        elif token in ('@{{', '@@'):
            i = at + len(token)         # escaped: literal text
        else:
            name = match.group(1)
            i = _directive(text, match, name, islands, code, blocks, stack)
    return islands, comments, code, blocks


def _directive(text, match, name, islands, code, blocks, stack):
    at, after = match.start(), match.end()
    if name == 'verbatim':
        end = text.find('@endverbatim', after)
        end = len(text) if end < 0 else end
        code.append(Span(at, after))
        return end
    if name == 'php' and not text[after:after + 1] == '(' \
            and not text[after:].lstrip(' ')[:1] == '(':
        end = text.find('@endphp', after)
        end = len(text) if end < 0 else end
        islands.append(Island(after, end))
        code.append(Span(at, min(len(text), end + len('@endphp'))))
        return end + len('@endphp')
    head_end = after
    rest = text[after:]
    stripped = rest.lstrip(' ')
    if stripped[:1] == '(':
        open_at = after + (len(rest) - len(stripped))
        close = _paren_end(text, open_at)
        if close > 0:
            wrapper = ('foreach(', '){}') if name in ('foreach', 'forelse') else ('__blade(', ');')
            islands.append(Island(open_at + 1, close - 1, wrapper[0], wrapper[1]))
            head_end = close
    code.append(Span(at, head_end))
    if name in LOOPS or name in BRANCHES:
        stack.append((name, at, head_end))
    elif name.startswith('end'):
        opener = name[3:]
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == opener:
                _name, start, body_start = stack[depth]
                del stack[depth:]
                kind = 'loop' if opener in LOOPS else 'branch'
                blocks.append((kind, start, body_start, at, after))
                break
    return head_end


def analyze(engine, text, language='blade'):
    row = nodes.row('blade')
    starts = line_starts(text)
    islands, comments, code, blocks = scan(text)
    strings, errors, scopes = [], [], []
    comment_spans = list(comments)
    for island in islands:
        source = island.prefix + text[island.start:island.end] + island.suffix
        data = source.encode('utf-8', 'surrogatepass')
        tree = engine.parse(data, 'php_only')
        line = _line_of(starts, island.start)
        collect = Collector(row, source, data, Offsets(source, data),
                            base=island.start - len(island.prefix), line_base=line - 1)
        found = collect.walk(tree.root_node)
        lo, hi = island.start, island.end
        comment_spans += _clip(collect.comments, lo, hi)
        strings += _clip(collect.strings, lo, hi)
        errors += _clip(collect.errors, lo, hi)
        scopes += [(s.body.start if s.body else lo, s) for s in _inside(found, lo, hi)]
    # template text: what is neither code nor a comment
    taken = sorted(code + comments)
    cursor = 0
    for span in taken:
        if span.start > cursor:
            strings.append(Span(cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < len(text):
        strings.append(Span(cursor, len(text)))
    for kind, start, body_start, body_end, end in blocks:
        node = ScopeNode(kind, _line_of(starts, start), _line_of(starts, max(start, end - 1)),
                         Span(body_start, body_end), ())
        scopes.append((start, node))
    root = ScopeNode('file', 1, len(starts), Span(0, len(text)), _nest(scopes))
    return FileStructure(text, language=language, backend='tree-sitter+blade',
                         comments=_merged(comment_spans), strings=_merged(strings),
                         errors=_merged(errors), root=root, starts=starts)


def _line_of(starts, offset):
    import bisect
    return bisect.bisect_right(starts, offset)


def _clip(spans, lo, hi):
    return [Span(max(s.start, lo), min(s.end, hi)) for s in spans if s.end > lo and s.start < hi]


def _inside(found, lo, hi):
    """Scopes of an island, without the wrapper the island was parsed in."""
    out = []
    for scope in found:
        body = scope.body
        if body is not None and lo <= body.start and body.end <= hi:
            out.append(scope)
        else:
            out.extend(_inside(scope.children, lo, hi))
    return out


def _nest(items):
    """[(offset, ScopeNode)] -> top-level nodes, each block holding the scopes
    whose offset falls in its body."""
    items = sorted(items, key=lambda pair: (pair[1].body.start if pair[1].body else pair[0],
                                            -(pair[1].body.end if pair[1].body else pair[0])))
    top, stack = [], []

    def attach(node):
        if stack:
            stack[-1][1].append(node)
        else:
            top.append(node)

    def close_until(offset):
        while stack and not (stack[-1][0].body.start <= offset < stack[-1][0].body.end
                             or offset == stack[-1][0].body.end == stack[-1][0].body.start):
            node, kids = stack.pop()
            attach(node._replace(children=tuple(node.children) + tuple(kids)))

    for offset, node in items:
        at = node.body.start if node.body else offset
        close_until(at)
        if node.kind in ('loop', 'branch') and not node.children:
            stack.append((node, []))
        else:
            attach(node)
    close_until(float('inf'))
    return tuple(top)
