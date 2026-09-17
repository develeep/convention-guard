"""Effective configuration: plugin defaults < userConfig (this install) < repo.

The team's committed repo config wins, so one person cannot quietly relax a
standard for everyone; where the repo is silent, the install preference
applies. Every entry point (hook, scan, dismiss) reads it through here, so a
CI run and a hook run of the same change use the same settings.
"""

from . import rules as rulelib
from .paths import user_option

DEFAULTS = {
    'max_rules': 4,
    'max_warns': 3,
    'max_consecutive_blocks': 3,
    'once_per_session': True,
    'run_linters': True,
    'lint_timeout': 90,
    'base_ref': '',
    'skip_if_question': True,
    'max_hits_per_rule': 3,
    'respect_supersede': True,
    'max_semantic_rules': 2,
    'max_semantic_reviews_per_session': 1,
    'block_level': 'error',
    'semantic_review': False,
    'stacks': [],
}

# keys that existed and no longer do -- silently ignoring them would leave a
# repo believing it had configured something
RETIRED = {'max_blocks_per_session': 'max_consecutive_blocks'}


class Config(dict):
    """The merged settings, plus where they came from."""

    def __init__(self, values, notes, repo):
        super().__init__(values)
        self.notes = notes          # [(level, text)]
        self.repo = repo            # the raw repo config (disable/severity/exclude live here)


def load(root, plugin_root=None):
    cfg = dict(DEFAULTS)
    notes = []
    plugin_cfg = rulelib.load_plugin_config(plugin_root) or {}
    repo_cfg = rulelib.load_repo_config(root) or {}
    if repo_cfg.get('_error'):
        notes.append(('error', 'config.yaml 파싱 실패: %s' % repo_cfg['_error']))
    for label, source in (('플러그인 config.yaml', plugin_cfg), ('레포 config.yaml', repo_cfg)):
        for key in source:
            if key in RETIRED:
                notes.append(('warn', '%s: %s 는 사라진 설정입니다 — %s 를 쓰세요'
                              % (label, key, RETIRED[key])))
    cfg.update({k: v for k, v in plugin_cfg.items() if k in DEFAULTS})
    report_only = user_option('report_only')
    if report_only is not None:
        cfg['block_level'] = 'report' if report_only else 'error'
    semantic_review = user_option('semantic_review')
    if semantic_review is not None:
        cfg['semantic_review'] = semantic_review
    cfg.update({k: v for k, v in repo_cfg.items() if k in DEFAULTS})
    return Config(cfg, notes, repo_cfg)
