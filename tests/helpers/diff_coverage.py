"""How much of what this branch changed is covered by the tests.

`coverage` reports per-file executed lines; `git diff -U0` says which lines
are new. The overlap is what U2 is judged on -- the unit modifies four files
that predate it, and dragging their untouched parts up to a line target is a
different job from this one (NR-U2-16).

    python3 -m coverage json -o coverage.json
    python3 tests/helpers/diff_coverage.py coverage.json --base <unit-start>
"""

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')


def added_lines(base_ref, root=ROOT, include=('scripts/', 'tests/perf/')):
    """{path: {line numbers this branch added}}"""
    # against the working tree, not just HEAD: the unit is measured before it
    # is committed, and after the commit the two are the same thing
    diff = subprocess.run(['git', 'diff', '-U0', base_ref],
                          cwd=root, capture_output=True, text=True)
    out, path = {}, None
    for line in diff.stdout.split('\n'):
        if line.startswith('+++ b/'):
            path = line[6:]
        elif line.startswith('@@') and path:
            match = HUNK.match(line)
            if match and any(path.startswith(prefix) for prefix in include):
                start = int(match.group(1))
                count = int(match.group(2) or 1)
                out.setdefault(path, set()).update(range(start, start + count))
    return out


def executed_lines(coverage_json):
    """{path: {line numbers coverage saw run}}"""
    with open(coverage_json, encoding='utf-8') as handle:
        data = json.load(handle)
    return {os.path.relpath(path, ROOT) if os.path.isabs(path) else path:
            set(entry.get('executed_lines') or [])
            for path, entry in (data.get('files') or {}).items()}


def ratio(coverage_json, base_ref='master', root=ROOT):
    """(covered, total, ratio, per-file misses) over the changed lines."""
    added = added_lines(base_ref, root)
    executed = executed_lines(coverage_json)
    covered = total = 0
    misses = {}
    for path, lines in sorted(added.items()):
        seen = executed.get(path, set())
        # only lines coverage knows about count: blanks, comments and deleted
        # lines are in the diff but are not statements
        known = {n for n in lines if n in seen} | {
            n for n in lines if n in _statements(coverage_json, path)}
        hit = {n for n in known if n in seen}
        covered += len(hit)
        total += len(known)
        if known - hit:
            misses[path] = sorted(known - hit)
    return covered, total, (covered / total if total else 1.0), misses


_STATEMENTS = {}


def _statements(coverage_json, path):
    if not _STATEMENTS:
        with open(coverage_json, encoding='utf-8') as handle:
            data = json.load(handle)
        for name, entry in (data.get('files') or {}).items():
            key = os.path.relpath(name, ROOT) if os.path.isabs(name) else name
            _STATEMENTS[key] = set(entry.get('executed_lines') or []) | set(
                entry.get('missing_lines') or [])
    return _STATEMENTS.get(path, set())


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('coverage_json')
    parser.add_argument('--base', default='master')
    parser.add_argument('--target', type=float, default=0.80)
    args = parser.parse_args(argv)

    covered, total, fraction, misses = ratio(args.coverage_json, args.base)
    print('변경분 커버리지: %d/%d = %.1f%% (목표 %.0f%%)'
          % (covered, total, fraction * 100, args.target * 100))
    for path, lines in misses.items():
        print('  %s: %s' % (path, ', '.join(str(n) for n in lines)))
    return 0 if fraction >= args.target else 1


if __name__ == '__main__':
    sys.exit(main())
