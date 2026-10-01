"""Python blocks from the standard library's own parser.

`ast` knows where a `for`, a comprehension or an `except` ends, which the
indent rules in scopes.py can only guess at. It reads the grammar of the
interpreter running the hook, so a file it cannot parse -- a `match`
statement under 3.9, a syntax error -- comes back as None and the caller
falls back to the indent rules.

A statement's block still ends where 1.x ended it: at the next line indented
no deeper than the header, trailing blanks included. `ast` only supplies the
last statement, so a block no longer stops early at a shallow comment or a
continuation line.
"""

import ast

from ..model import ScopeNode, Span

_LOOPS = (ast.For, ast.AsyncFor, ast.While,
          ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_STATEMENTS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
               ast.ExceptHandler, ast.For, ast.AsyncFor, ast.While)


def build(text, starts):
    """The children of the file node, or None when `ast` cannot read the text."""
    if '\r' in text.replace('\r\n', ''):
        return None                     # a lone CR is a line break to ast, not to us
    try:
        tree = ast.parse(text)
    except Exception:                   # noqa: BLE001 -- SyntaxError, ValueError, RecursionError
        return None
    return _Builder(text, starts).children(tree)


def _kind(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return 'function'
    if isinstance(node, ast.ClassDef):
        return 'class'
    if isinstance(node, ast.ExceptHandler):
        return 'catch'
    if isinstance(node, _LOOPS):
        return 'loop'
    return None


class _Builder:
    def __init__(self, text, starts):
        self.text = text
        self.starts = starts
        self.lines = text.split('\n')

    def children(self, node):
        out = []
        for child in ast.iter_child_nodes(node):
            kind = _kind(child)
            if kind is None:
                out.extend(self.children(child))
            else:
                out.append(self.node(kind, child))
        # field order puts decorators after the body; source order is the contract
        return tuple(sorted(out, key=lambda n: (n.start_line, n.body.start)))

    def node(self, kind, node):
        inner = self.children(node)
        if isinstance(node, _STATEMENTS):
            end_line = self.dedent(node.end_lineno, node.col_offset)
            first = node.body[0]
            body = Span(self.offset(first.lineno, first.col_offset), self.line_end(end_line))
        else:
            end_line = node.end_lineno
            body = Span(self.offset(node.lineno, node.col_offset),
                        self.offset(node.end_lineno, node.end_col_offset))
        # a decorator is part of the function it wraps: `@transaction.atomic`
        # decides as much as the body does (R21)
        start = min([d.lineno for d in getattr(node, 'decorator_list', ())] + [node.lineno])
        return ScopeNode(kind, start, end_line,
                         Span(body.start, max(body.start, body.end)), inner)

    def dedent(self, last, indent):
        end = last
        for index in range(last, len(self.lines)):
            line = self.lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            end = index + 1
        return end

    def offset(self, lineno, col):
        # ast columns count UTF-8 bytes
        line = self.lines[lineno - 1]
        return self.starts[lineno - 1] + len(line.encode('utf-8')[:col].decode('utf-8', 'ignore'))

    def line_end(self, lineno):
        return (self.starts[lineno] - 1 if lineno < len(self.starts) else len(self.text))
