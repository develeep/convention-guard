"""tree-sitter tree -> FileStructure: comments, literal text, error regions, scopes.

One walk over the tree. Offsets come back in characters of the text, the way
the rest of the layer counts (tree-sitter counts UTF-8 bytes). A region the
parser could not read (`ERROR`, a `MISSING` token, a literal it could not
close) is recorded; a match at or after the first one is judged UNKNOWN, a
match before it is judged as usual (model.FileStructure.in_error).
"""

from . import nodes
from .model import FileStructure, ScopeNode, Span

BODY_FIELDS = ('body', 'consequence')


class Offsets:
    """UTF-8 byte offset -> character offset."""

    def __init__(self, text, data):
        self.identity = len(data) == len(text)
        self.table = None
        if not self.identity:
            table, pos = [], 0
            for char in text:
                size = len(char.encode('utf-8', 'surrogatepass'))
                table.extend([pos] * size)
                pos += 1
            table.append(pos)
            self.table = table

    def __call__(self, byte):
        if self.identity:
            return byte
        return self.table[min(byte, len(self.table) - 1)]


class Collector:
    def __init__(self, row, text, data, offsets, base=0, line_base=0):
        self.row, self.text, self.data = row, text, data
        self.at = offsets
        self.base = base              # character offset of `data` in the whole file
        self.line_base = line_base    # line of `data`'s first line in the whole file, minus 1
        self.comments, self.strings, self.errors = [], [], []
        self.iteration = set(row['iteration_methods']) | set(row['iteration_functions'])

    def span(self, start_byte, end_byte):
        return Span(self.base + self.at(start_byte), self.base + self.at(end_byte))

    # -- the walk

    def walk(self, node, callbacks=frozenset()):
        """ScopeNodes found under `node` (exclusive), outermost first."""
        found = []
        for child in node.children:
            found.extend(self.visit(child, callbacks))
        return found

    def visit(self, node, callbacks=frozenset()):
        kind = node.type
        if kind == 'ERROR' or node.is_missing:
            self.errors.append(self.span(node.start_byte, max(node.end_byte, node.start_byte + 1)))
            if node.is_missing:
                return []
        literal = kind in self.row['comment'] or kind in self.row['string']
        if literal and node.has_error:
            # an unterminated string or comment: where text ends and code
            # starts is exactly what the parser could not tell
            self.errors.append(self.span(node.start_byte, node.end_byte))
        if kind in self.row['comment']:
            self.comments.append(self.span(node.start_byte, node.end_byte))
            return []
        if kind in self.row['string']:
            return self.literal(node)
        # the callback sits under `arguments` (PHP: `argument` too), so the
        # ids travel down until the function itself is reached
        inner = callbacks | self.callback_functions(node)
        scope_kind = nodes.kind_of(self.row, kind)
        children = self.walk(node, inner)
        if kind in self.row['decorated']:
            # `@dec` above a def is part of it: the pack shows it, the lines count
            line = self.line_base + node.start_point[0] + 1
            return [c._replace(start_line=min(c.start_line, line)) for c in children]
        if scope_kind is None:
            return children
        made = self.scope(scope_kind, node, children)
        if scope_kind == 'function' and node.id in callbacks:
            # iteration written as a call: the callback is a loop and a function
            return [made._replace(kind='loop', children=(made,))]
        return [made]

    def literal(self, node):
        """Literal text minus the code inside it; the code is walked as code."""
        holes = list(self.holes(node))
        cursor = node.start_byte
        found = []
        for hole in holes:
            if hole.start_byte > cursor:
                self.strings.append(self.span(cursor, hole.start_byte))
            found.extend(self.visit(hole))
            cursor = max(cursor, hole.end_byte)
        if node.end_byte > cursor:
            self.strings.append(self.span(cursor, node.end_byte))
        return found

    def holes(self, node):
        for child in node.named_children:
            if child.type in self.row['literal_parts']:
                continue
            if child.type in self.row['string_containers']:
                yield from self.holes(child)
            else:
                yield child

    def callback_functions(self, node):
        """ids of functions handed to an iteration call, when `node` is one."""
        fields = self.row['calls'].get(node.type)
        if not fields:
            return frozenset()
        callee = node.child_by_field_name(fields[0])
        name = self.call_name(callee)
        if name not in self.iteration:
            return frozenset()
        args = node.child_by_field_name(fields[1])
        found = set()
        for arg in (args.named_children if args is not None else ()):
            if arg.type in self.row['argument_wrappers'] and arg.named_children:
                arg = arg.named_children[-1]     # the value, after a name if any
            if arg.type in self.row['function']:
                found.add(arg.id)
        return frozenset(found)

    def call_name(self, callee):
        if callee is None:
            return None
        field = self.row['member_name'].get(callee.type)
        if field:
            callee = callee.child_by_field_name(field)
        if callee is None:
            return None
        return self.data[callee.start_byte:callee.end_byte].decode('utf-8', 'replace')

    def scope(self, kind, node, children):
        body = self.body_of(kind, node)
        return ScopeNode(kind, self.line_base + node.start_point[0] + 1,
                         self.line_base + node.end_point[0] + 1, body, tuple(children))

    def body_of(self, kind, node):
        body = None
        for field in BODY_FIELDS:
            body = node.child_by_field_name(field)
            if body is not None:
                break
        if body is None and kind in ('catch', 'class'):
            body = node.named_children[-1] if node.named_children else None
        if body is None:
            body = node                 # a comprehension: all of it runs per item
        start, end = body.start_byte, body.end_byte
        raw = self.data[start:end]
        if raw[:1] == b'{' and raw[-1:] == b'}' and end - start >= 2:
            start, end = start + 1, end - 1     # what `block_empty` judges: inside the braces
        return self.span(start, end)


def analyze(engine, text, language):
    row = nodes.row(language)
    data = text.encode('utf-8', 'surrogatepass')
    tree = engine.parse(data, nodes.grammar(language))
    collect = Collector(row, text, data, Offsets(text, data))
    found = collect.walk(tree.root_node)
    root = ScopeNode('file', 1, max(1, text.count('\n') + 1), Span(0, len(text)), tuple(found))
    return FileStructure(text, language=language, backend='tree-sitter',
                         comments=_merged(collect.comments), strings=_merged(collect.strings),
                         errors=_merged(collect.errors), root=root)


def _merged(spans):
    """Sorted, with touching or overlapping spans joined (the lookup needs
    disjoint spans)."""
    out = []
    for span in sorted(spans):
        if out and span.start <= out[-1].end:
            if span.end > out[-1].end:
                out[-1] = Span(out[-1].start, span.end)
            continue
        out.append(span)
    return tuple(out)
