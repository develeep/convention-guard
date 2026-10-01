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
BINARY_PROBE = 8000
# The algorithm is pinned: which lines count as added -- the agent's
# responsibility -- must not depend on a user's diff.algorithm. histogram
# keeps braces and repeated lines with the code they belong to (R13).
# A moved file is not a written one: renames are detected, at the similarity
# git uses by default but pinned against config, so `git mv` adds no lines (R14).
RENAMES = '-M70%'
DIFF_FLAGS = ['diff', '-U0', '--no-color', RENAMES, '--no-ext-diff',
              '--diff-algorithm=histogram', '--src-prefix=a/', '--dst-prefix=b/']
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
    """stdout path lines, unquoted, or GitError with git's own message."""
    code, out, err = git(root, args)
    if code != 0:
        raise GitError('git %s: %s' % (' '.join(args), (err or out).strip() or 'failed'))
    return [unquote(line) for line in out.splitlines() if line]


_ESCAPES = {'a': 7, 'b': 8, 't': 9, 'n': 10, 'v': 11, 'f': 12, 'r': 13, '"': 34, '\\': 92}


def unquote(path):
    """A path as git prints it, back to the file name: core.quotePath=false
    keeps non-ASCII as is, but `"`, `\\` and control characters still come
    C-quoted (`"app/a\\"b.php"`), and read as written they name nothing (R23b)."""
    if len(path) < 2 or path[0] != '"' or path[-1] != '"':
        return path
    out, body, i = bytearray(), path[1:-1], 0
    while i < len(body):
        c = body[i]
        if c == '\\' and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if body[i + 1:i + 4].isdigit():
                out.append(int(body[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
        out += c.encode('utf-8')
        i += 1
    return out.decode('utf-8', errors='replace')


def is_repo(root):
    code, out, _ = git(root, ['rev-parse', '--is-inside-work-tree'])
    return code == 0 and out.strip() == 'true'


def ref_exists(root, ref):
    code, _, _ = git(root, ['rev-parse', '--verify', '--quiet', ref + '^{commit}'])
    return code == 0


def current_head(root):
    code, out, _ = git(root, ['rev-parse', '--verify', 'HEAD^{commit}'])
    return out.strip() if code == 0 and out.strip() else None


def untracked(root):
    code, out, _ = git(root, ['ls-files', '--others', '--exclude-standard'])
    return {unquote(line) for line in out.splitlines()} if code == 0 else set()


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


def name_status(root, args, strict=False):
    """(paths, added, renamed_from, deleted) for one `git diff --name-status`.

    paths: every new-side path. A rename is only found when both of its paths
    are in the diff, so the old sides travel with every later diff; the
    deleted ones let a plain `mv` be recognised by content (R14).
    """
    code, out, err = git(root, ['diff', '--name-status', '--no-color', RENAMES] + list(args))
    if code != 0:
        if strict:
            raise GitError('git diff --name-status %s: %s' % (' '.join(args), err.strip()))
        return [], set(), set(), set()
    paths, added, renamed, deleted = [], set(), set(), set()
    for line in out.splitlines():
        parts = line.split('\t')
        parts = parts[:1] + [unquote(p) for p in parts[1:]]
        status = parts[0][:1]
        if len(parts) < 2:
            continue
        if status == 'D':
            deleted.add(parts[1])
            continue
        if status == 'R' and len(parts) == 3:
            renamed.add(parts[1])
        elif status == 'A':
            added.add(parts[-1])
        paths.append(parts[-1])
    return paths, added, renamed, deleted


def moved_untracked(root, candidates, deleted):
    """Untracked files that are a deleted tracked file moved whole: the
    content hashes to the blob HEAD has for it. Only a byte-identical move is
    recognised; a moved and edited file still reads as new (R14)."""
    if not candidates or not deleted:
        return set()
    code, out, _ = git(root, ['ls-tree', '-r', 'HEAD', '--'] + sorted(deleted))
    blobs = set()
    for line in out.splitlines() if code == 0 else ():
        meta = line.partition('\t')[0].split()
        if len(meta) == 3 and meta[1] == 'blob':
            blobs.add(meta[2])
    if not blobs:
        return set()
    algorithm = 'sha256' if len(next(iter(blobs))) == 64 else 'sha1'
    moved = set()
    for rel in candidates:
        try:
            with open(os.path.join(root, rel), 'rb') as fh:
                data = fh.read()
        except OSError:
            continue
        if hashlib.new(algorithm, b'blob %d\0' % len(data) + data).hexdigest() in blobs:
            moved.add(rel)
    return moved


def new_files(root):
    """Everything this change created, however it is currently tracked."""
    return untracked(root) | staged_added(root)


def ignored(root, relpaths):
    if not relpaths:
        return set()
    code, out, _ = git(root, ['check-ignore', '--stdin'], stdin='\n'.join(relpaths))
    return {unquote(line) for line in out.splitlines()} if code in (0, 1) else set()


def too_large(root, rel):
    """A file left out for its size -- said out loud, never a silent pass (R20)."""
    if os.path.splitext(rel)[1].lower() in SKIP_EXT:
        return False
    path = os.path.join(root, rel)
    try:
        return os.path.isfile(path) and os.path.getsize(path) > MAX_BYTES
    except OSError:
        return False


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
        # -sig: a BOM is not text, and left in it breaks `^` on the first line
        # newline='': only CRLF becomes LF. A lone CR is no line break to git,
        # and reading it as one shifts every line number after it (R23b)
        with open(os.path.join(root, relpath), 'r', encoding='utf-8-sig',
                  errors='replace', newline='') as fh:
            text = fh.read().replace('\r\n', '\n')
    except OSError:
        return ''
    # git's own test: a NUL in the first 8KB is a binary, whatever its name (R20)
    return '' if '\x00' in text[:BINARY_PROBE] else text


def read_blobs(root, prefix, relpaths):
    """({relpath: text}, {too large}) for the blobs `<prefix><path>` -- `:`
    for the index, `REV:` for a revision -- in one `git cat-file --batch`.

    A gate on staged or committed code has to read that code, not whatever
    the working tree holds now (R15). Missing, binary and SKIP_EXT paths are
    left out exactly as read_text leaves them out of the working tree.
    """
    rels = [r for r in dict.fromkeys(relpaths)
            if r and '\n' not in r and os.path.splitext(r)[1].lower() not in SKIP_EXT]
    if not rels:
        return {}, set()
    request = ''.join('%s%s\n' % (prefix, rel) for rel in rels).encode('utf-8')
    try:
        # ponytail: every blob is read whole, oversized ones too, to keep the
        # stream in step; --batch-check first if huge blobs ever matter
        proc = subprocess.run(['git', 'cat-file', '--batch'], cwd=root, input=request,
                              capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return {}, set()
    out, pos, texts, big = proc.stdout, 0, {}, set()
    for rel in rels:
        end = out.find(b'\n', pos)
        if end < 0:
            break
        header = out[pos:end].split()
        pos = end + 1
        if len(header) != 3:
            continue                        # `<name> missing`
        size = int(header[2])
        data, pos = out[pos:pos + size], pos + size + 1
        if header[1] != b'blob':
            continue
        if size > MAX_BYTES:
            big.add(rel)
            continue
        text = data.decode('utf-8-sig', errors='replace').replace('\r\n', '\n')
        if '\x00' not in text[:BINARY_PROBE]:
            texts[rel] = text
    return texts, big


def read_lines(root, relpath):
    """[(lineno, text)] for the whole file -- every line counts as added."""
    text = read_text(root, relpath)
    if not text:
        return []
    # split('\n'), not splitlines(): \x0b and \x0c are not line breaks to git
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    return [(i + 1, line.rstrip('\r')) for i, line in enumerate(lines)]


def _header_path(raw):
    raw = unquote(raw.strip())
    if raw == '/dev/null':
        return None
    if raw.startswith('b/'):
        raw = raw[2:]
    return raw or None


def parse_diff(text, seams=None):
    """{relpath: [(lineno, added text)]} for a multi-file unified diff.

    The parser tracks whether it is inside a hunk before treating `+++`/`---`
    as headers. An added line whose own content starts with `++` produces a
    `+++...` diff line, and skipping it drops the line *and* shifts every
    line number after it in that hunk.

    `seams`, when given, collects {relpath: {n}} for every pure deletion
    (`+n,0`): lines n and n+1 now meet where code was removed. Such a file is
    then in the result even with no added lines -- emptying a block or
    trimming a test is a change too (R19).
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
            if seams is not None and cur is not None and match.group(2) == '0':
                seams.setdefault(cur, set()).add(lineno)
                out.setdefault(cur, [])
            continue
        if not in_hunk or cur is None:
            continue
        if line.startswith('+'):
            text = line[1:].rstrip('\r')
            if lineno == 1 and text.startswith('\ufeff'):
                text = text[1:]     # agrees with read_text (R6)
            out.setdefault(cur, []).append((lineno, text))
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


def diff_lines(root, relpaths, diff_args, strict=False, seams=None, companions=()):
    """{relpath: [(lineno, text)]} from one batched `git diff` per chunk.

    strict=True raises GitError instead of treating a failed diff as "no
    change" -- a CI gate that reads a typo'd range as clean is worse than none.
    `seams` as in parse_diff. `companions` (the old side of renames) join
    every chunk, so a chunk boundary never splits a rename from its source.
    """
    result = {}
    rels = [r for r in dict.fromkeys(relpaths) if r]
    for start in range(0, len(rels), CHUNK):
        chunk = rels[start:start + CHUNK]
        chunk += sorted(set(companions) - set(chunk))
        code, out, err = git(root, DIFF_FLAGS + list(diff_args) + ['--'] + chunk)
        if code != 0:
            if strict:
                raise GitError('git diff %s: %s' % (' '.join(diff_args), err.strip()))
            continue
        for rel, lines in parse_diff(out, seams).items():
            result[rel] = merge(result.get(rel), lines)
    return result


def arrived_lines(root, old, new, before, relpaths):
    """{relpath: [(lineno, text)]} added by the commits in old..new that were
    made before `before` (unix seconds) -- other people's work a pull, merge or
    checkout brought in. A commit made during the call (the agent's own
    `git commit`, a rebase replaying its commits) is newer and stays out; merge
    commits stay out too, so a conflict resolution is still the agent's.

    Line numbers refer to each commit's own version: only the text is meaningful.
    """
    result = {}
    rels = [r for r in dict.fromkeys(relpaths) if r]
    if not (old and new and before and rels):
        return result
    # git dates are whole seconds: a commit in the same second as the call is
    # counted as the agent's, so the doubt falls on the side of checking
    args = (['log', '--no-merges', '--format=', '-p', '--before=@%d' % (int(before) - 1)]
            + DIFF_FLAGS[1:] + ['%s..%s' % (old, new), '--'])
    for start in range(0, len(rels), CHUNK):
        code, out, _ = git(root, args + rels[start:start + CHUNK])
        if code != 0:
            continue
        for rel, lines in parse_diff(out).items():
            result.setdefault(rel, []).extend(lines)
    return result


def added_lines(root, relpaths, base_ref=None, seams=None, oversized=None, new=None,
                with_untracked=False):
    """{relpath: [(lineno, text), ...]} for added lines only.

    A file git does not know yet is read whole. For the rest the working-tree
    diff against HEAD is the baseline; when `base_ref` is set its diff is
    unioned in, so a change committed mid-session is still this change's
    responsibility even if the file also has uncommitted edits. With `seams`
    (see parse_diff) a file that only lost lines is kept, with no lines.
    `oversized`, when given, collects the files left out for their size, and
    `new` the files this change created, against HEAD and every base (R14).
    with_untracked adds every untracked file to `relpaths`.
    """
    result = {}
    fresh = untracked(root)
    rels = [r for r in dict.fromkeys(list(relpaths) + (sorted(fresh) if with_untracked else []))
            if r]
    if not rels:
        return result
    skipped = ignored(root, rels)
    has_head = ref_exists(root, 'HEAD')
    extras = (list(base_ref) if isinstance(base_ref, (list, tuple, set))
              else ([base_ref] if base_ref else []))
    refs = list(dict.fromkeys((['HEAD'] if has_head else []) + extras))
    statuses = {ref: name_status(root, [ref]) for ref in refs}
    renamed = set().union(*(status[2] for status in statuses.values()))
    moved = moved_untracked(root, [r for r in rels if r in fresh and r not in skipped],
                            statuses['HEAD'][3] if has_head else set())
    if new is not None:
        new.update(fresh - moved)
        for status in statuses.values():
            new.update(status[1])
        if not has_head:
            new.update(staged_added(root))

    diffable = []
    for rel in rels:
        if rel in skipped:
            continue
        if not scannable(root, rel):
            if oversized is not None and too_large(root, rel):
                oversized.add(rel)
            continue
        if rel in moved:
            continue            # a plain `mv`: nothing in it was written
        if rel in fresh:
            lines = read_lines(root, rel)
            if lines:
                result[rel] = lines
        else:
            diffable.append(rel)

    for ref in refs:
        for rel, lines in diff_lines(root, diffable, [ref], seams=seams,
                                     companions=renamed).items():
            result[rel] = merge(result.get(rel), lines)
    if not has_head:          # empty repo: staged files are all new
        for rel in diffable:
            lines = read_lines(root, rel)
            if lines:
                result[rel] = lines
    result = {rel: lines for rel, lines in result.items() if lines or rel in (seams or ())}
    return result


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
