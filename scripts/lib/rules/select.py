"""Which rules apply where: globs, stack/version gates, supersede markers."""

import functools
import os
import re

from ..stack import version_ok

SEVERITIES = ('error', 'warn', 'info')


@functools.lru_cache(maxsize=4096)
def glob_re(pattern):
    """`**/` spans directories, `*` and `?` stay inside one, `{a,b}` alternates
    (each alternative a glob of its own), `[abc]`/`[!abc]` is one character.

    A leading `/` or `./` means the repo root and a trailing `/` the whole
    directory, as config files tend to write them. Rule files may not use
    either (schema.py refuses them) so a rule reads one way only. Matching is
    case-sensitive, like git paths (R22).
    """
    p = pattern.replace('\\', '/')
    if p.startswith('./'):
        p = p[2:]
    p = p.lstrip('/')
    if p.endswith('/'):
        p += '**'
    return re.compile('(?s)\\A' + _translate(p) + '\\Z')


def _translate(p):
    out, i = [], 0
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
        elif c == '{' and _close(p, i, '{', '}') is not None:
            end = _close(p, i, '{', '}')
            out.append('(?:%s)' % '|'.join(_translate(a) for a in _alternatives(p[i + 1:end])))
            i = end + 1
        elif c == '[' and _class_end(p, i) is not None:
            end = _class_end(p, i)
            out.append(_char_class(p[i + 1:end]))
            i = end + 1
        else:                       # an unclosed `{` or `[` is just a character
            out.append(re.escape(c))
            i += 1
    return ''.join(out)


def _close(p, start, opening, closing):
    """Index of the bracket that closes the one at `start`, nesting counted."""
    depth = 0
    for j in range(start, len(p)):
        if p[j] == opening:
            depth += 1
        elif p[j] == closing:
            depth -= 1
            if depth == 0:
                return j
    return None


def _alternatives(body):
    """`a,{b,c},d` -> ['a', '{b,c}', 'd']: only top-level commas split."""
    alts, depth, last = [], 0, 0
    for j, c in enumerate(body):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == ',' and depth == 0:
            alts.append(body[last:j])
            last = j + 1
    return alts + [body[last:]]


def _class_end(p, start):
    j = start + 1
    if j < len(p) and p[j] in '!^':
        j += 1
    if j < len(p) and p[j] == ']':
        j += 1                      # `[]]` and `[!]]` hold a literal `]`
    end = p.find(']', j)
    return end if end != -1 else None


def _char_class(body):
    """One path character from the set; never `/`, which only `**` crosses."""
    negate = body[:1] in ('!', '^')
    if negate:
        body = body[1:]
    # `-` stays bare so ranges work; everything else is escaped
    items = ''.join(c if c == '-' else re.escape(c) for c in body.replace('/', ''))
    if not items:
        return '[^/]' if negate else '(?!)'     # `[!/]` is any character, `[/]` none
    return '[^/%s]' % items if negate else '[%s]' % items


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
