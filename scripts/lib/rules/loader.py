"""Layered rule loading: core + user + local, presets, and repo config.

Precedence, lowest to highest:
  1. core   -- <plugin>/rules/**                          ids "core/..."
  2. user   -- ~/.claude/convention-guard/rules/          ids "user/..."
  3. local  -- <repo>/.claude/convention-guard/rules/     ids "local/..."

A file whose id is new adds a rule. A file with `override: core/<id>` is
deep-merged into that rule before it is validated, so a repo can relax one
field without copying the regex. Repo config then disables rules, changes
severities and excludes paths; presets decide which core rules are in play.
"""

import fnmatch
import os

from ..yamlio import read_cached
from . import schema
from .select import SEVERITIES

REPO_DIRNAME = '.claude/convention-guard'
LEGACY_DIRNAME = '.claude/convention-rules'

# convention-guard's own config and generated context are never content to
# check: an uncommitted config reads as a "new file", and its plain-language
# comments would trip the very rules they explain.
SELF_PATHS = ['%s/**' % REPO_DIRNAME, '%s/**' % LEGACY_DIRNAME, '.claude/rules/**']


def repo_dir(root):
    return os.path.join(root, *REPO_DIRNAME.split('/'))


def local_rules_dir(root):
    return os.path.join(repo_dir(root), 'rules')


def user_rules_dir():
    return os.path.expanduser(os.path.join('~', '.claude', 'convention-guard', 'rules'))


def legacy_layout(root):
    """A 0.x repo layout that has not been migrated yet."""
    return (os.path.isdir(os.path.join(root, *LEGACY_DIRNAME.split('/')))
            and not os.path.isdir(repo_dir(root)))


def iter_rule_files(base):
    if not base or not os.path.isdir(base):
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
        for name in sorted(filenames):
            if name.endswith(('.yaml', '.yml')):
                yield os.path.join(dirpath, name)


def deep_merge(base, patch):
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------- presets

class Preset:
    def __init__(self, name, description, stacks, patterns, path):
        self.name, self.description = name, description
        self.stacks, self.patterns, self.path = stacks, patterns, path

    def auto_for(self, tags):
        return '*' in self.stacks or bool(set(self.stacks) & set(tags))

    def includes(self, rid):
        return any(fnmatch.fnmatchcase(rid, pat) for pat in self.patterns)


def load_presets(plugin_root):
    presets, notes = {}, []
    base = os.path.join(plugin_root, 'presets')
    for path in iter_rule_files(base):
        try:
            raw = read_cached(path) or {}
            name = str(raw.get('name') or os.path.splitext(os.path.basename(path))[0])
            presets[name] = Preset(name, str(raw.get('description') or ''),
                                   [str(s) for s in raw.get('stacks') or []],
                                   [str(p) for p in raw.get('rules') or []], path)
        except Exception as exc:
            notes.append(('error', '%s: 프리셋 파싱 실패 (%s)' % (path, exc)))
    return presets, notes


def active_presets(presets, spec, tags):
    """spec: 'auto' | [names] where a list may itself contain 'auto'."""
    notes = []
    names = spec if isinstance(spec, list) else [spec or 'auto']
    active = []
    for name in names:
        name = str(name)
        if name == 'auto':
            active += [p for p in sorted(presets) if presets[p].auto_for(tags)]
        elif name in presets:
            active.append(name)
        else:
            notes.append(('error', 'config presets: 없는 프리셋 %s (가능: %s)'
                          % (name, ', '.join(sorted(presets)))))
    return list(dict.fromkeys(active)), notes


# ---------------------------------------------------------------- rules

class RuleSet:
    def __init__(self):
        self.rules = []       # enabled rules in play for this repo
        self.inactive = []    # [(rule, reason)] loaded but not in play
        self.notes = []       # [(level, text)]
        self.presets = []     # active preset names


def load(root, plugin_root, cfg, tags):
    result = RuleSet()
    if legacy_layout(root):
        result.notes.append(('error', '%s 는 0.x 레이아웃입니다 — scripts/migrate.py 로 '
                                      '%s 로 옮기세요' % (LEGACY_DIRNAME, REPO_DIRNAME)))

    raws, order = {}, []

    def ingest(base, source):
        items = []
        for path in iter_rule_files(base):
            try:
                raw = read_cached(path)
            except Exception as exc:
                result.notes.append(('error', '%s: 파싱 실패 (%s)' % (path, exc)))
                continue
            if not isinstance(raw, dict):
                result.notes.append(('error', '%s: 최상위가 매핑이 아님' % path))
                continue
            items.append((path, raw))

        # Definitions in one layer are collected before that layer's patches.
        # A local override must not depend on sorting after its local target.
        for path, raw in [item for item in items if not item[1].get('override')]:
            rid = schema.rule_id(raw, path, source)
            if rid in raws:
                result.notes.append(('warn', '%s: id 중복 %s (뒤에 온 것이 이김)' % (path, rid)))
            else:
                order.append(rid)
            raws[rid] = {'raw': raw, 'path': path, 'source': source}

        for path, raw in [item for item in items if item[1].get('override')]:
            target = raw.get('override')
            target = str(target)
            if target not in raws:
                result.notes.append(('warn', '%s: override 대상 %s 없음 (무시)'
                                     % (path, target)))
                continue
            entry = raws[target]
            patch = {k: v for k, v in raw.items() if k not in ('override', 'id')}
            entry.update(raw=deep_merge(entry['raw'], patch), path=path,
                         source='%s<-%s' % (entry['source'].split('<-')[0], source),
                         patched_from=entry.get('patched_from') or entry['path'],
                         base_severity=entry['raw'].get('severity'))

    ingest(os.path.join(plugin_root, 'rules'), 'core')
    ingest(user_rules_dir(), 'user')
    ingest(local_rules_dir(root), 'local')

    presets, preset_notes = load_presets(plugin_root)
    result.notes += preset_notes
    result.presets, preset_notes = active_presets(presets, cfg.get('presets'), tags)
    result.notes += preset_notes

    disabled = {str(r) for r in cfg.get('disable') or []}
    severity = {str(k): str(v).lower() for k, v in (cfg.get('severity') or {}).items()}
    exclude = cfg.get('exclude') or []
    exclude = ([exclude] if isinstance(exclude, str) else list(exclude)) + SELF_PATHS
    for rid in sorted((disabled | set(severity)) - set(raws)):
        result.notes.append(('warn', 'config: 없는 규칙 %s' % rid))
    for name in result.presets:
        # a literal id that matches nothing is a rule that was renamed or
        # deleted without its preset being updated; a glob matching nothing
        # is normal (stack presets list ids no other repo has)
        for pattern in presets[name].patterns:
            if not set(pattern) & set('*?[') and pattern not in raws:
                result.notes.append(('warn', 'preset %s: 없는 규칙 %s' % (name, pattern)))

    for rid in order:
        entry = raws[rid]
        try:
            rule = schema.normalize(entry['raw'], entry['path'], entry['source'].split('<-')[0])
        except schema.RuleError as exc:
            result.notes.append(('error', '%s: %s' % (entry['path'], exc)))
            continue
        rule['id'], rule['source'] = rid, entry['source']
        rule['repo_exclude'] = exclude
        if entry.get('patched_from'):
            rule['patched_from'] = entry['patched_from']
            base = str(entry.get('base_severity') or 'warn').lower()
            if base != rule['severity']:
                rule['base_severity'] = base
        if rid in severity:
            if severity[rid] not in SEVERITIES:
                result.notes.append(('warn', 'config severity: %s 의 값 %s 가 잘못됨'
                                     % (rid, severity[rid])))
            else:
                rule.setdefault('base_severity', rule['severity'])
                rule['severity'] = severity[rid]
                rule['severity_by'] = 'config'

        if rid in disabled:
            result.inactive.append((rule, 'disabled by config'))
        elif rule['disabled']:
            result.inactive.append((rule, 'disabled by %s' % rule['source']))
        elif rid.startswith('core/') and not any(presets[p].includes(rid)
                                                 for p in result.presets):
            result.inactive.append((rule, 'preset 비활성'))
        else:
            result.rules.append(rule)
    return result

