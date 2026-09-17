"""Which rules apply where: globs, stack/version gates, supersede markers."""

import functools
import os
import re

from ..stack import version_ok

SEVERITIES = ('error', 'warn', 'info')


@functools.lru_cache(maxsize=4096)
def glob_re(pattern):
    """`**/` spans directories, `*` stays inside one, `{a,b}` alternates."""
    out, i = ['(?s)\\A'], 0
    p = pattern.replace('\\', '/')
    if p.startswith('./'):
        p = p[2:]
    while i < len(p):
        c = p[i]
        if p.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif p.startswith('**', i):
            out.append('.*')
            i += 2
        elif c == '*':
            out.append('[^/]*')
            i += 1
        elif c == '?':
            out.append('[^/]')
            i += 1
        elif c == '{':
            end = p.find('}', i)
            if end == -1:
                out.append(re.escape(c))
                i += 1
            else:
                alts = p[i + 1:end].split(',')
                out.append('(?:%s)' % '|'.join(re.escape(a) for a in alts))
                i = end + 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append('\\Z')
    return re.compile(''.join(out))


def match_any(patterns, relpath):
    return any(glob_re(pat).match(relpath) for pat in patterns or ())


def severity_rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)


def stack_ok(rule, tags, versions):
    """Stack/version gate, independent of any single file."""
    stack = rule.get('stack') or []
    if stack and '*' not in stack and not (set(stack) & set(tags)):
        return False
    return version_ok(rule.get('version'), versions, stack)


def path_ok(rule, relpath):
    if match_any(rule.get('repo_exclude'), relpath):
        return False
    if match_any(rule.get('exclude'), relpath):
        return False
    return not rule.get('files') or match_any(rule['files'], relpath)


def applies(rule, relpath, tags, versions):
    return path_ok(rule, relpath) and stack_ok(rule, tags, versions)


def superseded(rule, root):
    """A formatting rule steps aside when the repo already runs a formatter.
    Returns the marker that matched, or None."""
    for marker in rule.get('superseded_by') or []:
        if os.path.exists(os.path.join(root, marker)):
            return marker
    return None


def applicable(rules, stacks, paths, root=None, respect_supersede=True):
    """Rule filtering before any detector runs: stack/version gate, supersede
    markers, and whether any changed path could possibly be in the rule's
    reach. A rule that cannot fire costs nothing afterwards."""
    out = []
    for rule in rules:
        if not stack_ok(rule, stacks.tags, stacks.versions):
            continue
        if respect_supersede and root and superseded(rule, root):
            continue
        reach = rule['when_changed'] if rule['kind'] == 'paired' else None
        if reach is not None:
            if not any(match_any(reach, p) for p in paths):
                continue
        elif not any(path_ok(rule, p) for p in paths):
            continue
        out.append(rule)
    return out
