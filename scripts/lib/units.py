"""Judgment units: what a `when_code_added` rule asks a reviewer about.

A glob rule has no regex to say where to look, so every line the agent added
would be a candidate -- and a question per line asks about `namespace`, a
lone `}`, or the window around them. Instead added lines are grouped:

    function   the outermost function around the line; closures and arrow
               functions fold into the method that holds them
    header     every added line outside a function, one per file; its code
               is the file with function bodies left out
    file       the whole file, when its structure could not be read (or
               only partly: boundaries after a parse error are a guess)

A unit stands only on an added line with a word in it. Edit provenance pairs
identical lines by position, so a lone `}` can be credited to the agent in a
legacy function; that must not pull the function into review.
"""

import re

from . import structure

WORD = re.compile(r'\w')


def meaningful(text):
    return bool(WORD.search(text or ''))


class Unit:
    __slots__ = ('kind', 'start', 'end', 'lines', 'code', 'label', 'hidden')

    def __init__(self, kind, start, end, lines, code, label, hidden=()):
        self.kind, self.start, self.end = kind, start, end
        self.lines = tuple(lines)      # the meaningful added lines it stands on
        self.code, self.label = code, label
        self.hidden = tuple(hidden)    # header: the function bodies left out, 1-based

    def __repr__(self):
        return 'Unit(%s, %d-%d, %r)' % (self.kind, self.start, self.end, self.lines)


def _outermost_function(analysed, lineno):
    for node in analysed.scopes_at(lineno):
        if node.kind == 'function':
            return node
    return None


def _functions(analysed):
    """Top-level function nodes (not nested in another function), in order."""
    out = []

    def walk(node):
        for child in node.children:
            if child.kind == 'function':
                out.append(child)
            else:
                walk(child)
    walk(analysed.root)
    return out


def of(text, language, added):
    """[Unit] for the added lines [(lineno, text)] of one file, in file order."""
    linenos = sorted(n for n, line in added if meaningful(line))
    if not linenos:
        return []
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    analysed = structure.analyze(text, language) if language else None
    # past a region the parser could not read, function boundaries are a guess
    if analysed is None or not analysed.ok or not analysed.scope_supported or analysed.errors:
        return [Unit('file', 1, max(len(lines), 1), linenos, text, '(파일 전체)')]

    functions, header = {}, []
    for lineno in linenos:
        node = _outermost_function(analysed, lineno)
        if node is None:
            header.append(lineno)
        else:
            functions.setdefault((node.start_line, node.end_line), []).append(lineno)
    out = []
    if header:
        # the signature line stays: it says which functions the file has
        hidden = [(node.start_line + 1, node.end_line) for node in _functions(analysed)
                  if node.end_line > node.start_line]
        inside = {n for a, b in hidden for n in range(a, b + 1)}
        code = '\n'.join(line for n, line in enumerate(lines, 1) if n not in inside)
        out.append(Unit('header', 1, len(lines), header, code, '(파일 머리)', hidden))
    for (start, end), at in sorted(functions.items()):
        code = '\n'.join(lines[start - 1:end])
        out.append(Unit('function', start, end, at, code, lines[start - 1].strip()))
    return out
