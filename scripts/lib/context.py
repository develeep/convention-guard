"""Minimum sufficient context for judging one candidate.

A reviewer needs the candidate's surroundings, not the repository. Each rule
names the pieces it needs (`semantic_review.context`), and every piece is cut
to a line budget:

    snippet            the candidate line ±5            (always included)
    current_function   the enclosing function/method    (the usual unit of judgment)
    imports            use/import/require lines at the top of the file
    changed_hunks      other lines this change added in the same file
    related_files      files named by a symbol in the function, e.g. the Model
                       a query uses: {symbol: '\\b([A-Z]\\w+)::', glob: 'app/Models/{1}.php'}

What was cut is marked `… N줄 생략`, so the reviewer knows to Read further
only when the pack is genuinely not enough.

`context_hash` fingerprints the primary region (the function, or the snippet
window when no function is found) and `related_hash` the context around it the
reviewer was shown (related files, imports). A verdict is cached under both:
rewriting any line of the function -- e.g. adding the eager load a VIOLATION
asked for -- or changing the Model the pack carried makes the old verdict stale
and the candidate is judged again.
"""

import hashlib
import os
import re

from .rules.select import match_any

SNIPPET_RADIUS = 5
# A function longer than this is shown as its head, the part around the
# candidate and its tail; the middle of a 300-line method rarely decides a
# verdict about one loop.
FUNCTION_MAX_LINES = 80
FUNCTION_AROUND = 30
IMPORT_SCAN_LINES = 150
IMPORT_MAX_LINES = 30
HUNKS_MAX_LINES = 20
RELATED_MAX_FILES = 2
RELATED_MAX_LINES = 60
FALLBACK_RADIUS = 30
# one parameter per line is common in Go and TypeScript; a dozen covers it
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
IMPORT_RE = re.compile(r'^\s*(?:use\s+[\w\\]|import\b|from\s+\S+\s+import\b|package\b|'
                       r'#include\b|require(?:_once)?\s*[\s(]|'
                       r'(?:const|let|var)\s+.*=\s*require\()')


def language(relpath):
    ext = os.path.splitext(relpath)[1].lower()
    if ext == '.py':
        return 'py'
    return BRACE_LANGS.get(ext)


def number(lines, start):
    """'  42| code' lines, start is 1-based."""
    width = len(str(start + len(lines)))
    return '\n'.join('%*d| %s' % (width, start + i, line) for i, line in enumerate(lines))


# ---------------------------------------------------------------- functions

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


def _clip_region(lines, start, end, focus, max_lines):
    """Numbered text for [start, end], elided around `focus` when too long."""
    if end - start + 1 <= max_lines:
        return number(lines[start:end + 1], start + 1), end - start + 1, False
    half = FUNCTION_AROUND // 2
    head = (start, min(start + 4, end))
    mid = (max(head[1] + 1, focus - half), min(end - 3, focus + half))
    tail = (max(mid[1] + 1, end - 2), end)
    parts, shown = [], 0
    prev_end = None
    for a, b in (head, mid, tail):
        if a > b:
            continue
        if prev_end is not None and a > prev_end + 1:
            parts.append('     … %d줄 생략 — 필요하면 Read' % (a - prev_end - 1))
        parts.append(number(lines[a:b + 1], a + 1))
        shown += b - a + 1
        prev_end = b
    return '\n'.join(parts), shown, True


# ---------------------------------------------------------------- pack

def _fingerprint(text):
    return hashlib.sha1(' '.join(str(text).split()).encode('utf-8')).hexdigest()[:10]


class Pack:
    def __init__(self, relpath, line, lang):
        self.file, self.line, self.language = relpath, line, lang
        self.sections = []
        self.lines = 0
        self.truncated = False
        self.primary = ''

    def add(self, kind, title, text, count, truncated=False):
        if not text:
            return
        self.sections.append({'kind': kind, 'title': title, 'text': text})
        self.lines += count
        self.truncated = self.truncated or truncated

    @property
    def context_hash(self):
        return _fingerprint(self.primary)

    @property
    def related_hash(self):
        """Fingerprint of the context outside the primary region that the
        reviewer was actually shown -- the related files and the imports. A
        verdict read them, so a verdict has to expire when they change, even
        though the candidate's own function did not.

        `changed_hunks` is left out on purpose: it follows the change scope,
        not the code being judged, so it would expire verdicts for edits
        elsewhere in the file that the reviewer never reasoned about.
        """
        return _fingerprint('\n'.join(
            '%s\n%s' % (s['title'], s['text']) for s in self.sections
            if s['kind'] in ('related_files', 'imports')))

    def to_dict(self):
        return {'file': self.file, 'line': self.line, 'language': self.language,
                'lines': self.lines, 'truncated': self.truncated,
                'context_hash': self.context_hash, 'related_hash': self.related_hash,
                'sections': self.sections}


def build(scope, cand, review, list_files=None):
    """Context pack for one candidate under the rule's `semantic_review` spec."""
    text = scope.text(cand.file)
    lines = text.split('\n') if text else []
    lang = language(cand.file)
    pack = Pack(cand.file, cand.line, lang)
    budget = int(review.get('max_context_lines') or 150)
    idx = max(0, min(cand.line - 1, len(lines) - 1)) if lines else 0
    wanted = [item if isinstance(item, str) else next(iter(item)) for item in review['context']]
    specs = {next(iter(item)): item[next(iter(item))]
             for item in review['context'] if isinstance(item, dict)}

    region = enclosing_function(lines, idx, lang) if lines and 'current_function' in wanted \
        else None
    if region:
        body, shown, cut = _clip_region(lines, region[0], region[1], idx,
                                        min(FUNCTION_MAX_LINES, budget))
        pack.primary = '\n'.join(lines[region[0]:region[1] + 1])
        pack.add('current_function', '감싸는 함수 (%d-%d줄)' % (region[0] + 1, region[1] + 1),
                 body, shown, cut)
    elif lines:
        radius = FALLBACK_RADIUS if 'current_function' in wanted else SNIPPET_RADIUS
        a, b = max(0, idx - radius), min(len(lines) - 1, idx + radius)
        pack.primary = '\n'.join(lines[a:b + 1])
        pack.add('snippet', '후보 주변 (%d-%d줄)' % (a + 1, b + 1),
                 number(lines[a:b + 1], a + 1), b - a + 1)

    def room():
        return budget - pack.lines

    if 'imports' in wanted and lines and room() > 0:
        found = [(i, line) for i, line in enumerate(lines[:IMPORT_SCAN_LINES])
                 if IMPORT_RE.match(line)]
        found = found[:min(IMPORT_MAX_LINES, room())]
        if found:
            pack.add('imports', 'import / use',
                     '\n'.join(number([line], i + 1) for i, line in found), len(found))

    if 'changed_hunks' in wanted and room() > 0:
        skip = set(range(region[0] + 1, region[1] + 2)) if region else set()
        added = [(n, t) for n, t in scope.lines(cand.file) if n not in skip and n != cand.line]
        added = added[:min(HUNKS_MAX_LINES, room())]
        if added:
            pack.add('changed_hunks', '이번 변경이 같은 파일에 추가한 다른 줄',
                     '\n'.join(number([t], n) for n, t in added), len(added))

    if 'related_files' in specs and room() > 0 and list_files:
        spec = specs['related_files']
        source = pack.primary or '\n'.join(lines)
        symbols = []
        for match in re.finditer(spec['symbol'], source, re.M):
            name = match.group(1) if match.groups() else match.group(0)
            if name and name not in symbols:
                symbols.append(name)
        limit = int(spec.get('max') or RELATED_MAX_FILES)
        files = list_files()
        for name in symbols:
            if limit <= 0 or room() <= 0:
                break
            glob = spec['glob'].replace('{1}', name)
            for rel in files:
                if rel == cand.file or not match_any([glob], rel):
                    continue
                other = scope.text(rel) if hasattr(scope, 'text') else ''
                other_lines = other.split('\n') if other else []
                take = min(RELATED_MAX_LINES, room(), len(other_lines))
                if take <= 0:
                    continue
                pack.add('related_files', '%s (심볼 %s)' % (rel, name),
                         number(other_lines[:take], 1)
                         + ('\n     … %d줄 생략 — 필요하면 Read' % (len(other_lines) - take)
                            if len(other_lines) > take else ''),
                         take, len(other_lines) > take)
                limit -= 1
                break
    return pack
