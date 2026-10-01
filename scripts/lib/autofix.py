"""Mechanical fixes for rules that declare one.

    fix:
      auto:
        replace: '\\(\\s*(int|string)\\s*\\)'    # Python regex, applied to the flagged line
        with: '(\\1)'                         # re.sub replacement

Only `when_line_added` rules can carry a fix, and a fix only ever touches the
exact line a candidate points at, and only while that line still reads what
detection saw. Legacy lines are never candidates, so they are never touched.
A fix that does not make the line pass its own rule is not applied: an
auto-fix that leaves the finding in place just edits code for nothing.
"""

import os

from .candidate import clip


class Fix:
    def __init__(self, rule_id, relpath, line, before, after):
        self.rule_id, self.file, self.line = rule_id, relpath, line
        self.before, self.after = before, after

    def to_dict(self):
        return {'rule_id': self.rule_id, 'file': self.file, 'line': self.line,
                'before': self.before, 'after': self.after}


def _read_lines(root, relpath):
    """([line text], [line ending]) from the bytes, or None when the file is not
    UTF-8 -- a file we cannot read is never written. Lines split on `\\n` only,
    as git counts them, and each keeps its own ending: a mixed file stays
    mixed (R16)."""
    with open(os.path.join(root, relpath), 'rb') as fh:
        data = fh.read()
    chunks = data.split(b'\n')
    lines, ends = [], []
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        if last and not chunk:
            break
        end = b'' if last else b'\n'
        if not last and chunk.endswith(b'\r'):
            chunk, end = chunk[:-1], b'\r\n'
        try:
            lines.append(chunk.decode('utf-8'))
        except UnicodeDecodeError:
            return None
        ends.append(end)
    return lines, ends


def plan(root, hits):
    """[Fix] for every candidate of a rule with fix.auto whose line can be fixed."""
    fixes, cache = [], {}
    for rule, cands in hits:
        spec = rule.get('fix')
        if not spec or rule['kind'] != 'line':
            continue
        for cand in cands:
            if cand.file not in cache:
                try:
                    read = _read_lines(root, cand.file)
                except OSError:
                    read = None
                cache[cand.file] = read[0] if read else None
            lines = cache[cand.file]
            if not lines or cand.line > len(lines):
                continue
            before = lines[cand.line - 1]
            # detection reads past a BOM (gitdiff.read_text); the write keeps it
            seen = before.lstrip('\ufeff') if cand.line == 1 else before
            if clip(seen) != cand.snippet:
                continue            # the line changed since detection
            after = spec['compiled'].sub(spec['with'], before)
            if after == before or rule['compiled_when'].search(after):
                continue            # no change, or the change does not resolve the finding
            fixes.append(Fix(rule['id'], cand.file, cand.line, before, after))
    return fixes


def apply(root, fixes):
    """Write fixes file by file. Returns the fixes actually applied."""
    applied = []
    by_file = {}
    for fix in fixes:
        by_file.setdefault(fix.file, []).append(fix)
    for relpath, file_fixes in by_file.items():
        try:
            read = _read_lines(root, relpath)
        except OSError:
            continue
        if read is None:
            continue            # not UTF-8: never written
        lines, ends = read
        changed = []
        for fix in file_fixes:
            if fix.line <= len(lines) and lines[fix.line - 1] == fix.before:
                lines[fix.line - 1] = fix.after
                changed.append(fix)
        if not changed:
            continue
        with open(os.path.join(root, relpath), 'wb') as fh:
            fh.write(b''.join(line.encode('utf-8') + end for line, end in zip(lines, ends)))
        applied += changed
    return applied


def diff(fixes):
    out = []
    for fix in fixes:
        out.append('  %s:%d  %s' % (fix.file, fix.line, fix.rule_id))
        out.append('    - %s' % fix.before.strip())
        out.append('    + %s' % fix.after.strip())
    return '\n'.join(out)
