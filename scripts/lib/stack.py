"""Repo-root stack detection.

One repo == one stack set (monorepos are out of scope by design choice).
Each stacks/*.yaml declares marker-file detection, the tags it contributes,
and the linters to delegate deterministic checks to.
"""

import os
import re

from .paths import project_dir, read_yaml


def _load_defs(plugin_root):
    defs = []
    stack_dir = os.path.join(plugin_root, 'stacks')
    if not os.path.isdir(stack_dir):
        return defs
    for name in sorted(os.listdir(stack_dir)):
        if not name.endswith(('.yaml', '.yml')):
            continue
        try:
            data = read_yaml(os.path.join(stack_dir, name))
        except Exception:
            continue
        if isinstance(data, dict) and data.get('id'):
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


def detect(plugin_root, cwd=None, forced=None):
    """Return {'tags': set, 'versions': dict, 'stacks': [id], 'lint': [...]}"""
    root = project_dir(cwd)
    result = {'root': root, 'tags': set(), 'versions': {}, 'stacks': [], 'lint': []}

    for spec in _load_defs(plugin_root):
        sid = spec['id']
        det = spec.get('detect') or {}
        matched = False

        if forced and sid in forced:
            matched = True
        else:
            markers = det.get('file')
            if isinstance(markers, str):
                markers = [markers]
            for marker in (markers or []):
                content = _read_marker(root, marker)
                if content is not None:
                    needle = det.get('contains')
                    if not needle:
                        matched = True
                    else:
                        try:
                            matched = re.search(needle, content, re.M) is not None
                        except re.error:
                            matched = needle in content
                    if matched:
                        vre = det.get('version_regex')
                        if vre:
                            try:
                                m = re.search(vre, content, re.M)
                                if m:
                                    result['versions'][sid] = m.group(1)
                            except re.error:
                                pass
                        break

        if not matched:
            continue

        result['stacks'].append(sid)
        for tag in (spec.get('tags') or [sid]):
            result['tags'].add(str(tag))
        for entry in (spec.get('lint') or []):
            if isinstance(entry, dict) and entry.get('cmd'):
                entry = dict(entry)
                entry['stack'] = sid
                result['lint'].append(entry)

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
