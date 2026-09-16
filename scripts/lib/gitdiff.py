"""Added lines only.

Checking whole files makes every rule fire on pre-existing code the moment a
file is touched, which is how these systems get turned off in week two.
Only lines the diff marks as added are ever scanned.

One `git diff` covers the whole touched set: a process per file is 20x slower
for no benefit, and on Windows the spawn cost dominates everything else here.
"""

import os
import re
import subprocess

HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip',
            '.gz', '.tar', '.lock', '.woff', '.woff2', '.ttf', '.mp4', '.svg'}
MAX_BYTES = 400_000
# argv ceiling is generous everywhere we run, but a 500-file touch list with
# long paths can still approach it, so the diff is chunked.
CHUNK = 200
DIFF_FLAGS = ['diff', '-U0', '--no-color', '--no-renames',
              '--src-prefix=a/', '--dst-prefix=b/']


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


def staged_added(root):
    """Files the index adds relative to HEAD.

    `git add` on a brand-new file makes it disappear from `ls-files --others`,
    and an absence rule ("this new file has no namespace") must still treat it
    as new -- otherwise staging silently switches those rules off.
    """
    code, out = _git(root, ['diff', '--cached', '--name-only',
                            '--diff-filter=A', 'HEAD'])
    if code != 0:      # no HEAD yet: everything in the index is new
        code, out = _git(root, ['diff', '--cached', '--name-only',
                                '--diff-filter=A'])
    return set(out.splitlines()) if code == 0 else set()


def new_files(root):
    """Everything this change created, however it is currently tracked."""
    return untracked(root) | staged_added(root)


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


def _header_path(raw):
    raw = raw.strip()
    if raw == '/dev/null':
        return None
    if raw.startswith('b/'):
        raw = raw[2:]
    return raw or None


def _parse_diff(text):
    """{relpath: [(lineno, added text)]} for a multi-file unified diff.

    The parser tracks whether it is inside a hunk before treating `+++`/`---`
    as headers. An added line whose own content starts with `++` produces a
    `+++...` diff line, and skipping it drops the line *and* shifts every
    line number after it in that hunk.
    """
    out, cur, lineno, in_hunk = {}, None, 0, False
    for line in text.split('\n'):
        if line.startswith('diff --git '):
            cur, lineno, in_hunk = None, 0, False
            continue
        if not in_hunk and (line.startswith('+++ ') or line.startswith('--- ')):
            if line.startswith('+++ '):
                cur = _header_path(line[4:])
            continue
        match = HUNK.match(line)
        if match:
            lineno, in_hunk = int(match.group(1)), True
            continue
        if not in_hunk or cur is None:
            continue
        if line.startswith('+'):
            out.setdefault(cur, []).append((lineno, line[1:]))
            lineno += 1
        elif line.startswith('-') or line.startswith('\\'):
            continue
        elif line.startswith(' '):
            lineno += 1       # -U0 emits none, but stay in sync if it ever does
    return out


def _merge(*groups):
    """Union added lines from several diffs. Line numbers all refer to the
    current working-tree file, so the earliest text for a line wins."""
    seen = {}
    for group in groups:
        for lineno, text in group or ():
            seen.setdefault(lineno, text)
    return [(n, seen[n]) for n in sorted(seen)]


def diff_lines(root, relpaths, diff_args):
    """{relpath: [(lineno, text)]} from one batched `git diff` per chunk."""
    result = {}
    rels = [r for r in dict.fromkeys(relpaths) if r]
    for start in range(0, len(rels), CHUNK):
        chunk = rels[start:start + CHUNK]
        code, out = _git(root, DIFF_FLAGS + list(diff_args) + ['--'] + chunk)
        if code != 0:
            continue
        for rel, lines in _parse_diff(out).items():
            result[rel] = _merge(result.get(rel), lines)
    return result


def added_lines(root, relpaths, base_ref=None):
    """{relpath: [(lineno, text), ...]} for added lines only.

    A file git does not know yet is read whole. For the rest the working-tree
    diff against HEAD is the baseline; when `base_ref` is set its diff is
    unioned in, so a change committed mid-session is still this change's
    responsibility even if the file also has uncommitted edits.
    """
    result = {}
    rels = [r for r in dict.fromkeys(relpaths) if r]
    if not rels:
        return result
    fresh = untracked(root)
    skipped = ignored(root, rels)

    diffable = []
    for rel in rels:
        if rel in skipped:
            continue
        if os.path.splitext(rel)[1].lower() in SKIP_EXT:
            continue
        if not os.path.isfile(os.path.join(root, rel)):
            continue
        if rel in fresh:
            lines = _whole_file(root, rel)
            if lines:
                result[rel] = lines
        else:
            diffable.append(rel)

    refs = ['HEAD'] + ([base_ref] if base_ref else [])
    for ref in refs:
        for rel, lines in diff_lines(root, diffable, [ref]).items():
            result[rel] = _merge(result.get(rel), lines)
    return {rel: lines for rel, lines in result.items() if lines}


def default_branch(root):
    """The upstream default branch, asked rather than guessed: a stale local
    `master` next to a live `main` would otherwise pick the wrong base."""
    code, out = _git(root, ['symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD'])
    if code == 0 and out.strip():
        return out.strip().split('refs/remotes/')[-1]
    return None


def resolve_base_ref(root, configured):
    """configured may be a ref, or 'auto' to find a merge-base with the default branch."""
    if not configured:
        return None
    if configured != 'auto':
        code, _ = _git(root, ['rev-parse', '--verify', '--quiet', configured])
        return configured if code == 0 else None
    candidates = [c for c in (default_branch(root),) if c]
    candidates += ['origin/main', 'origin/master', 'main', 'master']
    for candidate in candidates:
        code, out = _git(root, ['merge-base', 'HEAD', candidate])
        if code == 0 and out.strip():
            return out.strip()
    return None
