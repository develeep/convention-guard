"""Which rules apply where: globs, stack/version gates, supersede markers."""

import functools
import os
import re

from ..stack import version_ok

SEVERITIES = ('error', 'warn', 'info')

REPO_DIRNAME = '.claude/convention-guard'

# convention-guard's own config and generated context are never content to
# check: an uncommitted config reads as a "new file", and its plain-language
# comments would trip the very rules they explain.
SELF_PATHS = ['%s/**' % REPO_DIRNAME, '.claude/rules/**']


@functools.lru_cache(maxsize=4096)
def glob_re(pattern):
    """`**/` spans directories, `*` and `?` stay inside one, `{a,b}` alternates
    (each alternative a glob of its own), `[abc]`/`[!abc]` is one character.

    A leading `/` or `./` means the repo root and a trailing `/` the whole
    directory, as config files tend to write them. Rule files may not use
    either (schema.py refuses them) so a rule reads one way only. Matching is
    case-sensitive, like git paths (R22).
    """
    return re.compile('(?s)\\A' + _translate(_normalize(pattern)) + '\\Z')


@functools.lru_cache(maxsize=256)
def globs_re(patterns):
    """One regex for a tuple of globs: a list checked against every path by
    every rule (`generated` has dozens) costs one match, not one per glob."""
    return re.compile('(?s)\\A(?:%s)\\Z' % '|'.join(_translate(_normalize(p))
                                                    for p in patterns))


def _normalize(pattern):
    p = pattern.replace('\\', '/')
    if p.startswith('./'):
        p = p[2:]
    p = p.lstrip('/')
    if p.endswith('/'):
        p += '**'
    return p


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
    return bool(patterns) and globs_re(tuple(patterns)).match(relpath) is not None


def severity_rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)


def stack_ok(rule, tags, versions):
    """Stack/version gate, independent of any single file."""
    stack = rule.get('stack') or []
    if stack and '*' not in stack and not (set(stack) & set(tags)):
        return False
    return version_ok(rule.get('version'), versions, stack)


def path_reason(rule, relpath):
    """Why this rule does not read `relpath`, or None when it does. The one
    path test: the checks and `detect_stack.py --path` cannot disagree. When
    several reasons hold, the rule's own definition is named before the
    repo-wide lists, since that is the one a rule author can act on."""
    if match_any(rule.get('exclude'), relpath):
        return 'rule_exclude'
    if rule.get('files') and not match_any(rule['files'], relpath):
        return 'files'
    if not rule.get('include_generated') and match_any(rule.get('generated'), relpath):
        return 'generated'
    if match_any(SELF_PATHS, relpath):
        return 'self'
    if match_any(rule.get('repo_exclude'), relpath):
        return 'config_exclude'
    return None


def path_ok(rule, relpath):
    return path_reason(rule, relpath) is None


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
