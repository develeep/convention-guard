"""Effective configuration: plugin defaults < userConfig (this install) < repo.

The team's committed repo config wins, so one person cannot quietly relax a
standard for everyone; where the repo is silent, the install preference
applies. Every entry point (hook, scan, dismiss) reads it through here, so a
CI run and a hook run of the same change use the same settings.

    <plugin>/config.yaml                          defaults (also DEFAULTS below)
    CLAUDE_PLUGIN_OPTION_REPORT_ONLY / _SEMANTIC_REVIEW   userConfig
    <repo>/.claude/convention-guard/config.yaml   team settings
"""

import copy
import os

from .paths import user_option
from .rules.loader import deep_merge, repo_dir
from .yamlio import read as read_yaml

MODES = ('report', 'fix', 'auto-fix')

DEFAULTS = {
    'mode': 'report',
    'presets': 'auto',
    'stacks': [],
    'disable': [],
    'severity': {},
    'exclude': [],
    'scope': {'base_ref': ''},
    'limits': {
        'max_error_rules': 4,
        'max_warn_rules': 3,
        'max_locations_per_rule': 3,
        'max_consecutive_blocks': 3,
        'max_verify_attempts': 1,
    },
    'linters': {'enabled': True, 'timeout': 90},
    'collect': {'edit_tools': []},
    'semantic_review': {
        'enabled': False,
        'max_candidates': 5,
        'context_budget_lines': 400,
        'verdict_ttl_days': 30,
    },
    'skip_if_question': True,
    'respect_supersede': True,
    'once_per_session': True,
}

class Config(dict):
    """The merged settings, plus where they came from."""

    def __init__(self, values, notes, repo_path):
        super().__init__(values)
        self.notes = notes            # [(level, text)]
        self.repo_path = repo_path    # the repo config file, if any

    def limit(self, key):
        return int(self['limits'][key])

    @property
    def report_only(self):
        return self['mode'] == 'report'


def config_path(root):
    for name in ('config.yaml', 'config.yml'):
        path = os.path.join(repo_dir(root), name)
        if os.path.isfile(path):
            return path
    return None


def _read(path, label, notes):
    if not path or not os.path.isfile(path):
        return {}
    try:
        data = read_yaml(path) or {}
    except Exception as exc:
        notes.append(('error', '%s 파싱 실패: %s' % (label, exc)))
        return {}
    if not isinstance(data, dict):
        notes.append(('error', '%s: 최상위가 매핑이 아닙니다' % label))
        return {}
    return data


# `severity` maps rule ids the team picks, so its keys are not a closed set --
# checking them against DEFAULTS would drop every override the team wrote.
OPEN_MAPS = {'severity'}
# keys whose value may also take a second shape (loader.py accepts both)
ALSO = {'presets': list, 'exclude': str}


def _typed(label, path, value, default, notes, also=None):
    """False (and an error note) when `value` cannot stand in for `default`.

    A wrong type used to reach the engine and raise there, which check.py
    swallowed -- the hook then did nothing, every turn, with no way to tell.
    """
    if also and isinstance(value, also):
        return True
    if isinstance(default, bool):
        ok, want = isinstance(value, bool), 'true / false'
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        want = '0 이상의 정수'
    elif isinstance(default, list):
        ok, want = isinstance(value, list), '목록'
    elif isinstance(default, str):
        ok, want = isinstance(value, str), '문자열'
    else:
        return True
    if not ok:
        notes.append(('error', '%s: %s 는 %s 여야 합니다 (지금: %r)'
                      % (label, path, want, value)))
    return ok


def _validate(data, label, notes):
    """Drop what cannot be used and say why."""
    clean = {}
    for key, value in data.items():
        if key not in DEFAULTS:
            notes.append(('warn', '%s: 알 수 없는 설정 %s (무시)' % (label, key)))
            continue
        if isinstance(DEFAULTS[key], dict):
            if not isinstance(value, dict):
                notes.append(('error', '%s: %s 는 매핑이어야 합니다' % (label, key)))
                continue
            if key not in OPEN_MAPS:
                unknown = sorted(set(value) - set(DEFAULTS[key]))
                if unknown:
                    notes.append(('warn', '%s: 알 수 없는 설정 %s (무시)'
                                  % (label, ', '.join('%s.%s' % (key, u) for u in unknown))))
                value = {k: v for k, v in value.items()
                         if k in DEFAULTS[key]
                         and _typed(label, '%s.%s' % (key, k), v, DEFAULTS[key][k], notes)}
                if key == 'linters' and value.get('timeout') == 0:
                    notes.append(('error', '%s: linters.timeout 는 1 이상의 정수여야 합니다'
                                  % label))
                    del value['timeout']
        elif not _typed(label, key, value, DEFAULTS[key], notes, ALSO.get(key)):
            continue
        clean[key] = value
    if 'mode' in clean and clean['mode'] not in MODES:
        notes.append(('error', '%s: mode 는 %s 중 하나입니다 (지금: %s)'
                      % (label, ' / '.join(MODES), clean['mode'])))
        del clean['mode']
    return clean


def load(root, plugin_root=None):
    from .paths import plugin_root as default_plugin_root
    notes = []
    cfg = copy.deepcopy(DEFAULTS)

    plugin_file = os.path.join(plugin_root or default_plugin_root(), 'config.yaml')
    cfg = deep_merge(cfg, _validate(_read(plugin_file, '플러그인 config.yaml', notes),
                                    '플러그인 config.yaml', notes))

    report_only = user_option('report_only')
    if report_only is not None:
        cfg['mode'] = 'report' if report_only else 'fix'
    semantic_review = user_option('semantic_review')
    if isinstance(semantic_review, bool):
        cfg['semantic_review']['enabled'] = semantic_review

    repo_file = config_path(root)
    cfg = deep_merge(cfg, _validate(_read(repo_file, '레포 config.yaml', notes),
                                    '레포 config.yaml', notes))
    return Config(cfg, notes, repo_file)
