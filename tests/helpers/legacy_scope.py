"""The 1.x scope heuristics, frozen for the parity check.

A verbatim copy of what `context.py` did before U1 moved the logic into
`scripts/lib/structure/`. It exists so the migration can be shown to be
behaviour-preserving over every file in this repository and in examples/,
and it is deleted once that check has been signed off -- keeping it would put
the same heuristic in two places, which is exactly what NFR-03.2 forbids.

Do not import this from anything but tests/structure/test_parity.py.
"""

import os
import re

SIGNATURE_MAX_LINES = 12

BRACE_LANGS = {'.php': 'php', '.js': 'js', '.jsx': 'js', '.mjs': 'js', '.cjs': 'js',
               '.ts': 'js', '.tsx': 'js', '.go': 'go', '.java': 'java', '.kt': 'java',
               '.cs': 'java', '.rs': 'rust', '.c': 'c', '.cc': 'c', '.cpp': 'c', '.h': 'c',
               '.swift': 'java', '.scala': 'java', '.dart': 'java'}

# `for (...) {` and `} else if (...) {` look exactly like a method header to a
# regex; these words are never a function name
NOT_A_NAME = r'(?!(?:if|for|foreach|while|switch|catch|with|return|else|do|try|synchronized)\b)'

NAMED_FUNCTION = {
    'php': re.compile(r'\bfunction\s+&?\s*\w+\s*\('),
    'js': re.compile(r'\bfunction\s*\*?\s*\w*\s*\(|^\s*(?:export\s+)?(?:default\s+)?'
                     r'(?:(?:public|private|protected|static|async|get|set|readonly)\s+)*'
                     + NOT_A_NAME +
                     r'[\w$]+\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^={;]+)?\s*\{\s*$'
                     r'|^\s*(?:export\s+)?(?:const|let|var)\s+[\w$]+\s*=\s*(?:async\s*)?'
                     r'(?:\([^)]*\)|[\w$]+)\s*(?::\s*[^=]+)?=>'),
    'go': re.compile(r'^\s*func\b'),
    'java': re.compile(r'^\s*(?:@\w+\s+)*(?:(?:public|private|protected|static|final|'
                       r'override|suspend|fun|async|internal)\s+)*' + NOT_A_NAME +
                       r'[\w<>\[\],.?]+(?:\s+[\w<>\[\],.?]+)*\s+' + NOT_A_NAME + r'\w+\s*'
                       r'\([^;]*\)\s*(?:throws [\w., ]+)?\s*\{?\s*$|\bfun\s+\w+\s*\('),
    'rust': re.compile(r'\bfn\s+\w+'),
    'c': re.compile(r'^[\w\*\s&:<>,]+\s+\**\w+\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$'),
}
PY_DEF = re.compile(r'^(\s*)(?:async\s+)?def\s+\w+|^(\s*)class\s+\w+')

def language(relpath):
    ext = os.path.splitext(relpath)[1].lower()
    if ext == '.py':
        return 'py'
    return BRACE_LANGS.get(ext)

def _strip_strings(line):
    """Braces inside strings and line comments must not count."""
    line = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '""', line)
    return re.split(r'//|(?<![\w$])#(?!\[)', line)[0]


def _brace_block(lines, header_idx, limit=2000):
    """(start, end) 0-based inclusive of the block opened at or after header_idx."""
    depth, opened = 0, False
    for i in range(header_idx, min(len(lines), header_idx + limit)):
        code = _strip_strings(lines[i])
        for ch in code:
            if ch == '{':
                depth += 1
                opened = True
            elif ch == '}':
                depth -= 1
                if opened and depth == 0:
                    return header_idx, i
        if not opened and i > header_idx + SIGNATURE_MAX_LINES:
            return None     # a declaration without a body, e.g. an interface method
    return None


def enclosing_function(lines, idx, lang):
    """(start, end) 0-based of the innermost named function containing line idx."""
    if lang == 'py':
        return _python_block(lines, idx)
    pattern = NAMED_FUNCTION.get(lang)
    if not pattern:
        return None
    for header in range(idx, -1, -1):
        if not pattern.search(lines[header]):
            continue
        block = _brace_block(lines, header)
        if block and block[0] <= idx <= block[1]:
            return block
    return None


def _python_block(lines, idx):
    for header in range(idx, -1, -1):
        match = PY_DEF.match(lines[header])
        if not match:
            continue
        indent = len(match.group(1) or match.group(2) or '')
        end = header
        for j in range(header + 1, len(lines)):
            text = lines[j]
            if text.strip() and len(text) - len(text.lstrip()) <= indent:
                break
            end = j
        if header <= idx <= end:
            return header, end
    return None
