"""Repo-root stack detection.

One repo == one stack set (monorepos are out of scope for now).
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


def detect(plugin_root, cwd=None, forced=None):
    """Return {'root', 'tags': set, 'versions': dict, 'stacks': [id], 'lint': [...]}"""
    root = project_dir(cwd)
    result = {'root': root, 'tags': set(), 'versions': {}, 'stacks': [], 'lint': [],
              'notes': []}
    forced = set(forced or [])

    for spec in load_defs(plugin_root, result['notes']):
        sid = spec['id']
        det = spec.get('detect') or {}
        markers = det.get('file')
        if isinstance(markers, str):
            markers = [markers]

        # Marker detection always runs, even for a forced stack: forcing says
        # "this stack is here", not "skip looking", and skipping would throw
        # away the version we could have read from the marker file.
        matched = False
        for marker in markers or []:
            content = _read_marker(root, marker)
            if content is None or not _match_marker(det, content):
                continue
            matched = True
            version = _version(det, content)
            if version:
                result['versions'][sid] = version
            break

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


def version_ok(constraint, detected_versions, stacks):
    """constraint: ">=10", "<11", "10", or {stack: ">=10"}."""
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
    m = re.match(r'\s*(>=|<=|>|<|==|=)?\s*(.+)$', str(constraint))
    if not m:
        return True
    op, want = m.group(1) or '==', m.group(2)
    a, b = _ver_tuple(have), _ver_tuple(want)
    return {
        '>=': a >= b, '<=': a <= b, '>': a > b,
        '<': a < b, '==': a == b, '=': a == b,
    }[op]
