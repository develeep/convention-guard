"""Git primitives: added lines only.

Checking whole files makes every rule fire on pre-existing code the moment a
file is touched, which is how these systems get turned off in week two.
Only lines the diff marks as added are ever scanned.

One `git diff` covers the whole touched set: a process per file is 20x slower
for no benefit, and on Windows the spawn cost dominates everything else here.

Every call runs with core.quotePath=false. The default C-quotes non-ASCII
paths ("\\355\\225\\234.php"), and a quoted path matches no glob and no file.
"""

import hashlib
import os
import re
import subprocess

HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip',
            '.gz', '.tar', '.lock', '.woff', '.woff2', '.ttf', '.mp4', '.svg',
            '.jar', '.so', '.dll', '.exe', '.bin', '.pyc'}
# Files past this size are generated or vendored far more often than written
# by hand, and reading them whole on every Stop costs more than it finds.
MAX_BYTES = 400_000
# argv ceilings vary by platform, and long session path lists can approach
# them, so the diff is chunked.
CHUNK = 200
DIFF_FLAGS = ['diff', '-U0', '--no-color', '--no-renames', '--no-ext-diff',
              '--src-prefix=a/', '--dst-prefix=b/']
GIT_TIMEOUT = 30


class GitError(Exception):
    pass


def git(root, args, timeout=GIT_TIMEOUT, stdin=None):
    """(returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(['git', '-c', 'core.quotePath=false'] + list(args),
                              cwd=root, capture_output=True, text=True,
                              errors='replace', timeout=timeout, input=stdin)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, '', str(exc)


def git_lines(root, args):
    """stdout lines, or GitError with git's own message."""
    code, out, err = git(root, args)
    if code != 0:
        raise GitError('git %s: %s' % (' '.join(args), (err or out).strip() or 'failed'))
    return [line for line in out.splitlines() if line]


def is_repo(root):
    code, out, _ = git(root, ['rev-parse', '--is-inside-work-tree'])
    return code == 0 and out.strip() == 'true'


def ref_exists(root, ref):
    code, _, _ = git(root, ['rev-parse', '--verify', '--quiet', ref + '^{commit}'])
    return code == 0


def current_head(root):
    code, out, _ = git(root, ['rev-parse', '--verify', 'HEAD^{commit}'])
    return out.strip() if code == 0 and out.strip() else None


def changed_paths(root, base_ref=None):
    """Tracked and untracked paths changed from a known baseline."""
    paths = set(untracked(root))
    ref = base_ref or ('HEAD' if ref_exists(root, 'HEAD') else None)
    if ref:
        paths.update(git_lines(root, ['diff', ref, '--name-only']))
    return sorted(path for path in paths if path)


def file_fingerprint(root, relpath):
    path = os.path.join(root, relpath)
    try:
        digest = hashlib.sha1()
        with open(path, 'rb') as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def untracked(root):
    code, out, _ = git(root, ['ls-files', '--others', '--exclude-standard'])
    return set(out.splitlines()) if code == 0 else set()


def tracked(root):
    return git_lines(root, ['ls-files'])


def staged_added(root):
    """Files the index adds relative to HEAD.

    `git add` on a brand-new file makes it disappear from `ls-files --others`,
    and an absence rule ("this new file has no namespace") must still treat it
    as new -- otherwise staging silently switches those rules off.
    """
    code, out, _ = git(root, ['diff', '--cached', '--name-only', '--diff-filter=A', 'HEAD'])
    if code != 0:      # no HEAD yet: everything in the index is new
        code, out, _ = git(root, ['diff', '--cached', '--name-only', '--diff-filter=A'])
    return set(out.splitlines()) if code == 0 else set()


def new_files(root):
    """Everything this change created, however it is currently tracked."""
    return untracked(root) | staged_added(root)


def ignored(root, relpaths):
    if not relpaths:
        return set()
    code, out, _ = git(root, ['check-ignore', '--stdin'], stdin='\n'.join(relpaths))
    return set(out.splitlines()) if code in (0, 1) else set()


def scannable(root, rel):
    if os.path.splitext(rel)[1].lower() in SKIP_EXT:
        return False
    path = os.path.join(root, rel)
    try:
        return os.path.isfile(path) and os.path.getsize(path) <= MAX_BYTES
    except OSError:
        return False


def read_text(root, relpath):
    """Whole current contents of a working-tree file, or '' if unreadable."""
    if not scannable(root, relpath):
        return ''
    try:
        with open(os.path.join(root, relpath), 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


def read_lines(root, relpath):
    """[(lineno, text)] for the whole file -- every line counts as added."""
    text = read_text(root, relpath)
    if not text:
        return []
    return [(i + 1, line.rstrip('\r')) for i, line in enumerate(text.split('\n'))
            if not (i == text.count('\n') and line == '')]


def _header_path(raw):
    raw = raw.strip()
    if raw == '/dev/null':
        return None
    if raw.startswith('b/'):
        raw = raw[2:]
    return raw or None


def parse_diff(text):
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
            out.setdefault(cur, []).append((lineno, line[1:].rstrip('\r')))
            lineno += 1
        elif line.startswith(' '):
            lineno += 1       # -U0 emits none, but stay in sync if it ever does
    return out


def merge(*groups):
    """Union added lines from several diffs. Line numbers all refer to the
    current working-tree file, so the earliest text for a line wins."""
    seen = {}
    for group in groups:
        for lineno, text in group or ():
            seen.setdefault(lineno, text)
    return [(n, seen[n]) for n in sorted(seen)]


def diff_lines(root, relpaths, diff_args, strict=False):
    """{relpath: [(lineno, text)]} from one batched `git diff` per chunk.

    strict=True raises GitError instead of treating a failed diff as "no
    change" -- a CI gate that reads a typo'd range as clean is worse than none.
    """
    result = {}
    rels = [r for r in dict.fromkeys(relpaths) if r]
    for start in range(0, len(rels), CHUNK):
        chunk = rels[start:start + CHUNK]
        code, out, err = git(root, DIFF_FLAGS + list(diff_args) + ['--'] + chunk)
        if code != 0:
            if strict:
                raise GitError('git diff %s: %s' % (' '.join(diff_args), err.strip()))
            continue
        for rel, lines in parse_diff(out).items():
            result[rel] = merge(result.get(rel), lines)
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
        if rel in skipped or not scannable(root, rel):
            continue
        if rel in fresh:
            lines = read_lines(root, rel)
            if lines:
                result[rel] = lines
        else:
            diffable.append(rel)

    has_head = ref_exists(root, 'HEAD')
    extras = (list(base_ref) if isinstance(base_ref, (list, tuple, set))
              else ([base_ref] if base_ref else []))
    refs = list(dict.fromkeys((['HEAD'] if has_head else []) + extras))
    for ref in refs:
        for rel, lines in diff_lines(root, diffable, [ref]).items():
            result[rel] = merge(result.get(rel), lines)
    if not has_head:          # empty repo: staged files are all new
        for rel in diffable:
            lines = read_lines(root, rel)
            if lines:
                result[rel] = lines
    return {rel: lines for rel, lines in result.items() if lines}


def default_branch(root):
    """The upstream default branch, asked rather than guessed: a stale local
    `master` next to a live `main` would otherwise pick the wrong base."""
    code, out, _ = git(root, ['symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD'])
    if code == 0 and out.strip():
        return out.strip().split('refs/remotes/')[-1]
    return None


def resolve_base_ref(root, configured):
    """configured may be a ref, or 'auto' to find a merge-base with the default branch."""
    if not configured:
        return None
    if configured != 'auto':
        return configured if ref_exists(root, configured) else None
    candidates = [c for c in (default_branch(root),) if c]
    candidates += ['origin/main', 'origin/master', 'main', 'master']
    for candidate in candidates:
        code, out, _ = git(root, ['merge-base', 'HEAD', candidate])
        if code == 0 and out.strip():
            return out.strip()
    return None
