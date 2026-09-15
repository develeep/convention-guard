"""Added lines only.

Checking whole files makes every rule fire on pre-existing code the moment a
file is touched, which is how these systems get turned off in week two.
Only lines the diff marks as added are ever scanned.
"""

import os
import re
import subprocess

HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip',
            '.gz', '.tar', '.lock', '.woff', '.woff2', '.ttf', '.mp4', '.svg'}
MAX_BYTES = 400_000


def _git(root, args, timeout=15):
    try:
        proc = subprocess.run(['git'] + args, cwd=root, capture_output=True,
                              text=True, errors='replace', timeout=timeout)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ''


def is_repo(root):
    code, out = _git(root, ['rev-parse', '--is-inside-work-tree'])
    return code == 0 and out.strip() == 'true'


def untracked(root):
    code, out = _git(root, ['ls-files', '--others', '--exclude-standard'])
    return set(out.splitlines()) if code == 0 else set()


def ignored(root, relpaths):
    if not relpaths:
        return set()
    try:
        proc = subprocess.run(['git', 'check-ignore', '--stdin'], cwd=root,
                              input='\n'.join(relpaths), capture_output=True,
                              text=True, errors='replace', timeout=15)
        return set(proc.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        return set()


def _whole_file(root, relpath):
    path = os.path.join(root, relpath)
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return []
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return [(i + 1, line.rstrip('\n')) for i, line in enumerate(fh)]
    except OSError:
        return []


def read_text(root, relpath):
    """Whole current contents of a working-tree file, or '' if unreadable."""
    path = os.path.join(root, relpath)
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return ''
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


def _parse_diff(text):
    out, lineno = [], 0
    for line in text.split('\n'):
        m = HUNK.match(line)
        if m:
            lineno = int(m.group(1))
            continue
        if line.startswith('+++') or line.startswith('---'):
            continue
        if line.startswith('+'):
            out.append((lineno, line[1:]))
            lineno += 1
    return out


def added_lines(root, relpaths, base_ref=None):
    """{relpath: [(lineno, text), ...]} for added lines only."""
    result = {}
    if not relpaths:
        return result
    new_files = untracked(root)
    skipped = ignored(root, list(relpaths))

    for rel in relpaths:
        if rel in skipped:
            continue
        if os.path.splitext(rel)[1].lower() in SKIP_EXT:
            continue
        if not os.path.isfile(os.path.join(root, rel)):
            continue
        if rel in new_files:
            lines = _whole_file(root, rel)
        else:
            code, out = _git(root, ['diff', '-U0', '--no-color', 'HEAD', '--', rel])
            lines = _parse_diff(out) if code == 0 else []
            if not lines and base_ref:
                code, out = _git(root, ['diff', '-U0', '--no-color', base_ref, '--', rel])
                if code == 0:
                    lines = _parse_diff(out)
        if lines:
            result[rel] = lines
    return result


def resolve_base_ref(root, configured):
    """configured may be a ref, or 'auto' to find a merge-base with the default branch."""
    if not configured:
        return None
    if configured != 'auto':
        code, _ = _git(root, ['rev-parse', '--verify', '--quiet', configured])
        return configured if code == 0 else None
    for candidate in ('origin/master', 'origin/main', 'master', 'main'):
        code, out = _git(root, ['merge-base', 'HEAD', candidate])
        if code == 0 and out.strip():
            return out.strip()
    return None
