"""Looking at the work tree, cheaply: what the collect hooks and the Stop use.

    signature(root, rel)       'mtime_ns:size', or None when the file is gone
    read(root, rel)            Snapshot: exists, lines, signature, flag
    status(root)               (HEAD, {path: signature}) of every dirty path -- one git call
    blobs(root, rev, rels)     {path: lines} of a revision -- one git call
    ignored(root, rels)        the paths .gitignore covers -- one git call

Nothing here decides anything. Text is read the way git compares it: a BOM
is not text, CRLF is one break, a lone CR is not; a NUL in the first 8KB
makes a binary, and files past MAX_BYTES are not read (they are named).
"""

import os
import subprocess

from .gitdiff import BINARY_PROBE, MAX_BYTES, SKIP_EXT, read_blobs, unquote

GIT_TIMEOUT = 8          # the collect hook has 10s in all


class Snapshot:
    """One file as it is now. `lines` is None unless the text could be read;
    `flag` says why not: 'too_large', 'binary' or 'unreadable'."""

    __slots__ = ('exists', 'lines', 'sig', 'flag')

    def __init__(self, exists, lines=None, sig=None, flag=None):
        self.exists, self.lines, self.sig, self.flag = exists, lines, sig, flag


ABSENT = Snapshot(False)


def skipped(rel):
    """Images, archives, lock files: never anyone's code to check."""
    return os.path.splitext(rel)[1].lower() in SKIP_EXT


def signature(root, rel):
    try:
        st = os.stat(os.path.join(root, rel))
    except OSError:
        return None
    if not os.path.isfile(os.path.join(root, rel)):
        return None
    return '%d:%d' % (st.st_mtime_ns, st.st_size)


def split_lines(text):
    """git's lines: split on \\n only (\\x0b and \\x0c are not breaks), no
    trailing empty line for a final newline."""
    if not text:
        return []
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    return lines


def decode(data):
    """bytes -> (lines, flag)."""
    text = data.decode('utf-8-sig', errors='replace').replace('\r\n', '\n')
    if '\x00' in text[:BINARY_PROBE]:
        return None, 'binary'
    return split_lines(text), None


def read(root, rel):
    path = os.path.join(root, rel)
    sig = signature(root, rel)
    if sig is None:
        return ABSENT
    if int(sig.rsplit(':', 1)[1]) > MAX_BYTES:
        return Snapshot(True, None, sig, 'too_large')
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError:
        return Snapshot(True, None, sig, 'unreadable')
    lines, flag = decode(data)
    return Snapshot(True, lines, sig, flag)


def git(root, args, stdin=None):
    try:
        proc = subprocess.run(['git', '-c', 'core.quotePath=false'] + list(args), cwd=root,
                              capture_output=True, timeout=GIT_TIMEOUT, input=stdin)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc if proc.returncode == 0 else None


def toplevel(path):
    """The work tree root containing `path`, or None outside git."""
    proc = git(path, ['rev-parse', '--show-toplevel'])
    if proc is None:
        return None
    top = proc.stdout.decode('utf-8', 'replace').strip()
    return os.path.abspath(top) if top else None


def status(root):
    """(HEAD or None, {path: signature or None}) for every changed or
    untracked path, or None when git could not say.

    One `git status`: the branch header carries HEAD, so no second process.
    Renames are reported as a deletion and an addition -- the ledger pairs
    moved lines itself, and does so for a plain `mv` too.
    """
    proc = git(root, ['status', '--porcelain=v2', '-z', '--branch', '--no-renames',
                      '--untracked-files=all'])
    if proc is None:
        return None
    head, paths = None, {}
    for raw in proc.stdout.decode('utf-8', 'replace').split('\0'):
        if not raw:
            continue
        if raw.startswith('# branch.oid '):
            oid = raw[len('# branch.oid '):].strip()
            head = oid if oid and oid != '(initial)' else None
            continue
        kind = raw[:1]
        if kind == '?':
            rel = raw[2:]
        elif kind == '1':
            rel = raw.split(' ', 8)[-1]
        elif kind == 'u':
            rel = raw.split(' ', 10)[-1]
        else:
            continue
        if rel.endswith('/') or skipped(rel):
            continue                # a nested repository, or nobody's code
        paths[rel] = signature(root, rel)
    return head, paths


def changed_between(root, old, new):
    """Paths that differ between two revisions."""
    proc = git(root, ['diff', '--name-only', '--no-renames', '-z', old, new])
    if proc is None:
        return []
    # -z: paths come as they are, never C-quoted
    return [p for p in proc.stdout.decode('utf-8', 'replace').split('\0')
            if p and not skipped(p)]


def blobs(root, rev, rels):
    """{path: lines} as `rev` has them; a path it lacks is left out, so its
    absence reads as "the file did not exist". Too large and binary blobs are
    left out too -- `unreadable` collects them."""
    if not rev or not rels:
        return {}
    texts, _big = read_blobs(root, '%s:' % rev, rels)
    return {rel: split_lines(text) for rel, text in texts.items()}


def ignored(root, rels):
    if not rels:
        return set()
    try:
        proc = subprocess.run(['git', '-c', 'core.quotePath=false', 'check-ignore', '--stdin'],
                              cwd=root, capture_output=True, text=True, errors='replace',
                              input='\n'.join(rels), timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode not in (0, 1):
        return set()
    return {unquote(line) for line in proc.stdout.splitlines()}
