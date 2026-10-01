"""The change a check is responsible for.

Every entry point builds one ChangeScope and hands it to the same pipeline:
the Stop hook from the files the agent touched, scan.py from a git selector.
The scope is the only thing that differs between them, so a manual run and a
hook run of the same change cannot disagree.

    ChangeScope.from_ledger(root, entries)              Stop hook
    ChangeScope.working_tree(root, base_ref)            scan.py (default)
    ChangeScope.staged(root)                            scan.py --staged
    ChangeScope.git_range(root, spec)                   scan.py --range A..B
    ChangeScope.files(root, paths)                      scan.py --files
    ChangeScope.everything(root)                        scan.py --all
"""

import os

from . import gitdiff


class ScopeError(Exception):
    """The scope could not be computed. Callers must not read this as "no change"."""


class ChangeScope:
    def __init__(self, root, changed, new_files, label, base_ref=None, seams=None,
                 too_large=(), blob=None):
        self.root = root
        # where the bodies come from: None the working tree, ':' the index,
        # 'REV:' a revision -- a gate reads the code it gates (R15)
        self.blob = blob
        self._text = {}
        if blob is None:
            # Every constructor funnels through here, so what counts as scannable
            # cannot differ between them. It used to: --staged and --range built
            # their file list straight from `git diff`, so a 500KB bundle or a
            # .svg was checked there and skipped by the hook and --all.
            self.changed = {rel: lines for rel, lines in changed.items()
                            if gitdiff.scannable(root, rel)}
            big = {rel for rel in changed
                   if rel not in self.changed and gitdiff.too_large(root, rel)}
        else:
            self._text, big = gitdiff.read_blobs(root, blob, changed)
            self.changed = {rel: lines for rel, lines in changed.items() if rel in self._text}
        # left out for their size: the caller names them (R20)
        self.too_large = tuple(sorted(set(too_large) | big))
        # where lines were only removed (gitdiff.parse_diff): a file that just
        # lost lines is in `changed` with none added (R19)
        self.seams = {rel: frozenset(found) for rel, found in (seams or {}).items()
                      if rel in self.changed}
        self.new_files = set(new_files)     # judged as "whole file is new"
        self.label = label
        self.base_ref = base_ref

    # -- queries used by detectors and linters

    def paths(self):
        return sorted(self.changed)

    def lint_paths(self):
        """Files with added lines. A linter finding in a file that only lost
        lines could never be this change's, so those are not linted."""
        return sorted(rel for rel, lines in self.changed.items() if lines)

    def __bool__(self):
        return bool(self.changed)

    def __len__(self):
        return len(self.changed)

    def is_new(self, relpath):
        return relpath in self.new_files

    def text(self, relpath):
        """The body of a changed file, from where the scope reads. A file outside
        the change (a related file for the reviewer) comes from the working tree."""
        if relpath not in self._text:
            self._text[relpath] = gitdiff.read_text(self.root, relpath)
        return self._text[relpath]

    def lines(self, relpath):
        return self.changed.get(relpath, ())

    def changed_linenos(self, relpath):
        return {lineno for lineno, _ in self.changed.get(relpath, ())}

    def seams_of(self, relpath):
        """{n}: lines n and n+1 meet where this change removed code."""
        return self.seams.get(relpath, frozenset())

    def added_body(self, relpath):
        return '\n'.join(text for _, text in self.changed.get(relpath, ()))

    # -- constructors

    @classmethod
    def from_ledger(cls, root, entries, ignored=()):
        """The lines the agent wrote, as the edit ledger recorded them
        (ledger.py): its `a` lines, the seams where it only removed code, the
        files it created. The file itself is still read whole for context."""
        changed, seams, new, big = {}, {}, set(), set()
        for entry in entries:
            if entry.path in ignored or not entry.owned():
                continue
            if entry.flag == 'too_large':
                big.add(entry.path)
                continue
            if entry.lines is None:
                continue                    # binary or unreadable: nobody's code
            changed[entry.path] = entry.agent_lines()
            if entry.seams():
                seams[entry.path] = entry.seams()
            if entry.created:
                new.add(entry.path)
        return cls(root, changed, new, '이번 작업', seams=seams, too_large=big)

    @classmethod
    def working_tree(cls, root, base_ref=None):
        _require_repo(root)
        paths = set()
        if gitdiff.ref_exists(root, 'HEAD'):
            paths |= set(_names(root, ['diff', 'HEAD', '--name-only']))
        if base_ref:
            paths |= set(_names(root, ['diff', base_ref, '--name-only']))
        seams, oversized, new = {}, set(), set()
        changed = gitdiff.added_lines(root, sorted(paths), base_ref, seams, oversized, new,
                                      with_untracked=True)
        return cls(root, changed, new & set(changed), '워킹 트리', seams=seams,
                   too_large=oversized)

    @classmethod
    def staged(cls, root):
        _require_repo(root)
        paths, new, renamed = _status(root, ['--cached'])
        seams = {}
        changed = _diff(root, paths, ['--cached'], seams, renamed)
        return cls(root, changed, new & set(changed), '스테이지된 변경', seams=seams, blob=':')

    @classmethod
    def git_range(cls, root, spec):
        _require_repo(root)
        paths, new, renamed = _status(root, [spec])
        seams = {}
        changed = _diff(root, paths, [spec], seams, renamed)
        right = _right_side(spec)
        return cls(root, changed, new & set(changed), spec, seams=seams,
                   blob='%s:' % right if right else None)

    @classmethod
    def files(cls, root, raw_paths):
        """Whole files, each treated as new. Paths outside the repo are an error."""
        rels, bad = [], []
        for raw in raw_paths:
            path = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw))
            if not os.path.exists(path) and os.path.exists(os.path.join(root, raw)):
                path = os.path.join(root, raw)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            if rel == '..' or rel.startswith('../') or not os.path.isfile(path):
                bad.append(raw)
            else:
                rels.append(rel)
        if bad:
            raise ScopeError('레포 안의 파일이 아닙니다: %s' % ', '.join(bad))
        changed = _whole(root, rels)
        return cls(root, changed, set(changed), '지정 파일 %d개' % len(rels),
                   too_large=_oversized(root, rels))

    @classmethod
    def everything(cls, root):
        """Every text file in the work tree, each treated as new -- a legacy audit.

        Untracked files count: a file the agent just created is the newest code
        in the repo, and an audit that silently leaves it out reports a
        compliance rate for a codebase nobody has.
        """
        _require_repo(root)
        try:
            tracked = gitdiff.tracked(root)
        except gitdiff.GitError as exc:
            raise ScopeError(str(exc))
        rels = list(dict.fromkeys(tracked + sorted(gitdiff.untracked(root))))
        changed = _whole(root, rels)
        return cls(root, changed, set(changed), '전수조사 (%d개 파일)' % len(changed),
                   too_large=_oversized(root, rels))


def _require_repo(root):
    if not gitdiff.is_repo(root):
        raise ScopeError('git 레포가 아닙니다: %s' % root)


def _names(root, args):
    try:
        return gitdiff.git_lines(root, args)
    except gitdiff.GitError as exc:
        raise ScopeError(str(exc))


def _right_side(spec):
    """The revision `git diff <spec>` compares *to*: B for A..B and A...B,
    HEAD for A.., None for a bare A (that one diffs against the working tree)."""
    for sep in ('...', '..'):
        if sep in spec:
            return spec.split(sep, 1)[1] or 'HEAD'
    return None


def _status(root, args):
    """(new-side paths, added files, rename sources) of one diff (R14)."""
    try:
        paths, added, renamed, _deleted = gitdiff.name_status(root, args, strict=True)
    except gitdiff.GitError as exc:
        raise ScopeError(str(exc))
    return paths, added, renamed


def _diff(root, paths, args, seams=None, companions=()):
    try:
        return gitdiff.diff_lines(root, paths, args, strict=True, seams=seams,
                                  companions=companions)
    except gitdiff.GitError as exc:
        raise ScopeError(str(exc))


def _oversized(root, rels):
    return {rel for rel in rels if gitdiff.too_large(root, rel)}


def _whole(root, rels):
    out = {}
    for rel in rels:
        if gitdiff.scannable(root, rel):
            lines = gitdiff.read_lines(root, rel)
            if lines:
                out[rel] = lines
    return out
