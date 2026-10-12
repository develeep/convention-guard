"""Repo-root stack detection.

One repo == one stack set, read at the repo root or at one app root below it
(monorepos with several apps are out of scope for now).
Each stacks/*.yaml declares marker-file detection, the tags it contributes,
and the linters to delegate deterministic checks to.
"""

import os
import re

from .paths import project_dir
from .yamlio import read_cached as read_yaml


def load_defs(plugin_root, notes=None):
    defs = []
    notes = notes if notes is not None else []
    stack_dir = os.path.join(plugin_root, 'stacks')
    if not os.path.isdir(stack_dir):
        return defs
    for name in sorted(os.listdir(stack_dir)):
        if not name.endswith(('.yaml', '.yml')):
            continue
        try:
            data = read_yaml(os.path.join(stack_dir, name))
        except Exception as exc:
            notes.append(('error', '%s: 스택 파싱 실패 (%s)'
                          % (os.path.join(stack_dir, name), exc)))
            continue
        sid = data.get('id') if isinstance(data, dict) else None
        if not isinstance(sid, str) or not re.match(r'^[A-Za-z0-9_.-]+$', sid):
            notes.append(('error', '%s: 유효한 stack id 가 없습니다'
                          % os.path.join(stack_dir, name)))
            continue
        defs.append(data)
    return defs


def _read_marker(root, rel, limit=200000):
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read(limit)
    except OSError:
        return None


def _match_marker(det, content):
    needle = det.get('contains')
    if not needle:
        return True
    try:
        return re.search(needle, content, re.M) is not None
    except re.error:
        return needle in content


def _version(det, content):
    pattern = det.get('version_regex')
    if not pattern:
        return None
    try:
        match = re.search(pattern, content, re.M)
    except re.error:
        return None
    return match.group(1) if match else None


def _matches(spec, base):
    """(matched, version) for one stack definition's markers under `base`."""
    det = spec.get('detect') or {}
    markers = det.get('file')
    if isinstance(markers, str):
        markers = [markers]
    for marker in markers or []:
        content = _read_marker(base, marker)
        if content is not None and _match_marker(det, content):
            return True, _version(det, content)
    return False, None


# where an app below the repo root is looked for: one or two levels down, not
# in dependency, build or hidden directories
SKIP_DIRS = {'node_modules', 'vendor', 'dist', 'build', 'storage', 'logs'}


def _app_candidates(root, defs):
    """{dir: stack ids} for directories one or two levels below `root` that
    hold a stack marker."""
    found = {}
    level = [root]
    for _depth in (1, 2):
        nxt = []
        for base in level:
            try:
                names = sorted(os.listdir(base))
            except OSError:
                continue
            for name in names:
                path = os.path.join(base, name)
                if name.startswith('.') or name in SKIP_DIRS or not os.path.isdir(path):
                    continue
                ids = {spec['id'] for spec in defs if _matches(spec, path)[0]}
                if ids:
                    found[os.path.relpath(path, root).replace(os.sep, '/')] = ids
                nxt.append(path)
        level = nxt
    return found


def _pick_app(candidates):
    """The one candidate whose stacks cover every other's, or None. A shared
    composer.json next to the real Laravel app says only `php`; the app says
    `laravel, php` and is the one meant."""
    for path, ids in candidates.items():
        if all(other <= ids for p, other in candidates.items() if p != path) and \
                all(other != ids for p, other in candidates.items() if p != path):
            return path
    return None


def detect(plugin_root, cwd=None, forced=None, app_root=None):
    """Return {'root', 'app_root', 'tags': set, 'versions': dict, 'stacks': [id], 'lint': [...]}

    The markers are read at the repo root, or at `app_root` (repo-relative)
    when the app lives below it. With no app_root and no marker at the root,
    a single app one or two levels down is taken and said; several are not
    guessed between."""
    root = project_dir(cwd)
    result = {'root': root, 'app_root': '', 'tags': set(), 'versions': {}, 'stacks': [],
              'lint': [], 'notes': []}
    forced = set(forced or [])
    defs = load_defs(plugin_root, result['notes'])

    app = str(app_root or '').strip().strip('/')
    if not app and not any(_matches(spec, root)[0] for spec in defs):
        candidates = _app_candidates(root, defs)
        app = _pick_app(candidates) or ''
        if app:
            result['notes'].append(('info', '앱 루트 자동 감지: %s — 다르면 config 의 app_root 로 '
                                            '지정하세요' % app))
        elif candidates:
            result['notes'].append(('warn', '앱 루트 후보가 여럿이라 스택을 감지하지 않았습니다 (%s) — '
                                            'config 의 app_root 로 하나를 지정하세요'
                                    % ', '.join(sorted(candidates))))
    result['app_root'] = app
    base = os.path.join(root, app) if app else root

    for spec in defs:
        sid = spec['id']
        # Marker detection always runs, even for a forced stack: forcing says
        # "this stack is here", not "skip looking", and skipping would throw
        # away the version we could have read from the marker file.
        matched, version = _matches(spec, base)
        if version:
            result['versions'][sid] = version
        if not (matched or sid in forced):
            continue
        result['stacks'].append(sid)
        for tag in spec.get('tags') or [sid]:
            result['tags'].add(str(tag))
        for entry in spec.get('lint') or []:
            if isinstance(entry, dict) and entry.get('cmd'):
                result['lint'].append(dict(entry, stack=sid))
    return result


def _ver_tuple(value):
    parts = re.findall(r'\d+', str(value))[:3]
    return tuple(int(p) for p in parts) + (0,) * (3 - len(parts))


_CLAUSE = re.compile(r'(>=|<=|>|<|==|=)?(\d+(?:\.\d+){0,2})\Z')
_OPS = {'>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b,
        '<': lambda a, b: a < b, '==': lambda a, b: a == b, '=': lambda a, b: a == b}


def parse_constraint(text):
    """[(op, version tuple)] -- clauses split on spaces, every one must hold:
    `>=10 <12`. Anything else raises ValueError: `^10` used to read as `==10`
    and quietly switched a rule off (R23g)."""
    clauses = re.sub(r'(>=|<=|==|>|<|=)\s+', r'\1', str(text).strip()).split()
    if not clauses:
        raise ValueError(text)
    out = []
    for clause in clauses:
        match = _CLAUSE.match(clause)
        if not match:
            raise ValueError(clause)
        out.append((match.group(1) or '==', _ver_tuple(match.group(2))))
    return out


def version_ok(constraint, detected_versions, stacks):
    """constraint: ">=10", ">=10 <12", "10", or {stack: ">=10"}."""
    if not constraint:
        return True
    if isinstance(constraint, dict):
        return all(version_ok(v, detected_versions, [k]) for k, v in constraint.items())
    have = None
    for sid in stacks or []:
        if sid in detected_versions:
            have = detected_versions[sid]
            break
    if have is None:
        return True  # unknown version never suppresses a rule
    try:
        clauses = parse_constraint(constraint)
    except ValueError:
        return True  # the schema refuses these; never suppress on a misread
    have = _ver_tuple(have)
    return all(_OPS[op](have, want) for op, want in clauses)
