"""The change a check is responsible for.

Every entry point builds one ChangeScope and hands it to the same pipeline:
the Stop hook from the files the agent touched, scan.py from a git selector.
The scope is the only thing that differs between them, so a manual run and a
hook run of the same change cannot disagree.

    ChangeScope.from_touched(root, touched, base_ref)   Stop hook
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
    def __init__(self, root, changed, new_files, label, base_ref=None):
        self.root = root
        # Every constructor funnels through here, so what counts as scannable
        # cannot differ between them. It used to: --staged and --range built
        # their file list straight from `git diff`, so a 500KB bundle or a
        # .svg was checked there and skipped by the hook and --all.
        self.changed = {rel: lines for rel, lines in changed.items()
                        if gitdiff.scannable(root, rel)}
        self.new_files = set(new_files)     # judged as "whole file is new"
        self.label = label
        self.base_ref = base_ref
        self._text = {}

    # -- queries used by detectors and linters

    def paths(self):
        return sorted(self.changed)

    def __bool__(self):
        return bool(self.changed)

    def __len__(self):
        return len(self.changed)

    def is_new(self, relpath):
        return relpath in self.new_files

    def text(self, relpath):
        if relpath not in self._text:
            self._text[relpath] = gitdiff.read_text(self.root, relpath)
        return self._text[relpath]

    def lines(self, relpath):
        return self.changed.get(relpath, ())

    def changed_linenos(self, relpath):
        return {lineno for lineno, _ in self.changed.get(relpath, ())}

    def added_body(self, relpath):
        return '\n'.join(text for _, text in self.changed.get(relpath, ()))

    # -- constructors

    @classmethod
    def from_touched(cls, root, touched, base_ref=None):
        _require_repo(root)
        changed = gitdiff.added_lines(root, touched, base_ref)
        return cls(root, changed, gitdiff.new_files(root) & set(changed), '이번 작업', base_ref)

    @classmethod
    def working_tree(cls, root, base_ref=None):
        _require_repo(root)
        paths = set()
        if gitdiff.ref_exists(root, 'HEAD'):
            paths |= set(_names(root, ['diff', 'HEAD', '--name-only']))
        fresh = gitdiff.new_files(root)
        if base_ref:
            paths |= set(_names(root, ['diff', base_ref, '--name-only']))
        changed = gitdiff.added_lines(root, sorted(paths | fresh), base_ref)
        return cls(root, changed, fresh & set(changed), '워킹 트리')

    @classmethod
    def staged(cls, root):
        _require_repo(root)
        paths = _names(root, ['diff', '--cached', '--name-only'])
        new = set(_names(root, ['diff', '--cached', '--name-only', '--diff-filter=A']))
        changed = _diff(root, paths, ['--cached'])
        return cls(root, changed, new & set(changed), '스테이지된 변경')

    @classmethod
    def git_range(cls, root, spec):
        _require_repo(root)
        paths = _names(root, ['diff', '--name-only', spec])
        new = set(_names(root, ['diff', '--name-only', '--diff-filter=A', spec]))
        changed = _diff(root, paths, [spec])
        return cls(root, changed, new & set(changed), spec)

    @classmethod
    def files(cls, root, raw_paths):
        """Whole files, each treated as new. Paths outside the repo are an error."""
        rels, bad = [], []
        for raw in raw_paths:
            path = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw))
            if not os.path.exists(path) and os.path.exists(os.path.join(root, raw)):
                path = os.path.join(root, raw)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            if rel.startswith('..') or not os.path.isfile(path):
                bad.append(raw)
            else:
                rels.append(rel)
        if bad:
            raise ScopeError('레포 안의 파일이 아닙니다: %s' % ', '.join(bad))
        changed = _whole(root, rels)
        return cls(root, changed, set(changed), '지정 파일 %d개' % len(rels))

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
        changed = _whole(root, list(dict.fromkeys(tracked + sorted(gitdiff.untracked(root)))))
        return cls(root, changed, set(changed), '전수조사 (%d개 파일)' % len(changed))


def _require_repo(root):
    if not gitdiff.is_repo(root):
        raise ScopeError('git 레포가 아닙니다: %s' % root)


def _names(root, args):
    try:
        return gitdiff.git_lines(root, args)
    except gitdiff.GitError as exc:
        raise ScopeError(str(exc))


def _diff(root, paths, args):
    try:
        return gitdiff.diff_lines(root, paths, args, strict=True)
    except gitdiff.GitError as exc:
        raise ScopeError(str(exc))


def _whole(root, rels):
    out = {}
    for rel in rels:
        if gitdiff.scannable(root, rel):
            lines = gitdiff.read_lines(root, rel)
            if lines:
                out[rel] = lines
    return out
