"""Where Claude Code keeps this plugin: install records, the settings scopes
that enable it and hold its userConfig, and the data directory its hooks write.

Read by readiness.py (checklist section B). Nothing here writes anything, and
none of it trusts the shape of a JSON file it did not write.
"""

import glob
import json
import os
import time

from .paths import parse_option, plugin_root

PLUGIN = 'convention-guard'
CLAUDE = os.path.expanduser('~/.claude')
# Claude Code settings, lowest to highest precedence
SCOPES = [('user', os.path.join(CLAUDE, 'settings.json')),
          ('project', '.claude/settings.json'),
          ('local', '.claude/settings.local.json')]
# Past this the "hooks are firing" evidence is too old to say anything about now
HOOK_EVIDENCE_DAYS = 7


def as_dict(value):
    return value if isinstance(value, dict) else {}


def read_json(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return as_dict(json.load(fh))
    except (OSError, ValueError):
        return {}


def market_of(key):
    return (key or '').partition('@')[2]


# ---------------------------------------------------------------- 설치 기록 · 활성 범위

def plugin_keys():
    """Installed `convention-guard@<marketplace>` entries, each a list of records."""
    data = read_json(os.path.join(CLAUDE, 'plugins', 'installed_plugins.json'))
    plugins = as_dict(data.get('plugins', data))
    out = {}
    for key, entries in plugins.items():
        if str(key).split('@')[0] == PLUGIN:
            entries = entries if isinstance(entries, list) else [entries]
            out[key] = [e for e in entries if isinstance(e, dict)]
    return out


def scope_settings(session_dir):
    """Settings are keyed on the directory the session was opened in, not the git root."""
    out = []
    for scope, path in SCOPES:
        full = path if os.path.isabs(path) else os.path.join(session_dir, path)
        out.append((scope, read_json(full)))
    return out


def enabled_in(data, key):
    """True / False as written, None when this scope says nothing (or nonsense)."""
    value = as_dict(data.get('enabledPlugins')).get(key)
    return value if isinstance(value, bool) else None


def effective_enabled(settings, key):
    value, where = None, None
    for scope, data in settings:
        said = enabled_in(data, key)
        if said is not None:
            value, where = said, scope
    return value, where


def pick_key(keys, settings):
    """The install this repo actually runs: the one that ends up enabled."""
    enabled = [k for k in sorted(keys) if effective_enabled(settings, k)[0]]
    return (enabled or sorted(keys))[0], enabled


def installs_for(entries, session_dir):
    """Records that apply here: no projectPath (user scope), or this project."""
    here = os.path.realpath(session_dir)
    return [e for e in entries
            if not e.get('projectPath') or os.path.realpath(str(e['projectPath'])) == here]


def marketplace_version(market):
    path = os.path.join(CLAUDE, 'plugins', 'marketplaces', market, '.claude-plugin',
                        'marketplace.json')
    plugins = read_json(path).get('plugins')
    for plugin in plugins if isinstance(plugins, list) else []:
        if as_dict(plugin).get('name') == PLUGIN:
            return plugin.get('version')
    return None


def check_install(rep, session_dir, running_version):
    keys = plugin_keys()
    if not keys:
        rep.add('B1', 'WARN', 'Claude Code 에 설치된 기록이 없습니다 (체크아웃에서 직접 실행 중)',
                '/plugin 으로 설치하세요 — 훅은 설치된 플러그인에서만 돕니다')
        return None
    settings = scope_settings(session_dir)
    key, enabled = pick_key(keys, settings)
    if len(enabled) > 1:
        rep.add('B1', 'WARN', '여러 마켓플레이스의 설치가 함께 켜져 있습니다: %s — 훅이 두 번 돕니다'
                % ', '.join(enabled), '/plugin 에서 하나만 남기세요')
    mine = installs_for(keys[key], session_dir)
    versions = sorted({str(e.get('version', '?')) for e in mine})
    latest = marketplace_version(market_of(key))
    text = '%s — 이 레포에 적용되는 설치 %s (%s)' % (
        key, ', '.join('%s:%s' % (e.get('scope'), e.get('version')) for e in mine) or '없음',
        '마켓플레이스 최신 %s' % latest if latest else '마켓플레이스 버전 모름')
    if not mine:
        rep.add('B1', 'FAIL', text, '이 레포에 적용되는 범위(user/project/local)로 설치하세요')
    elif not latest:
        rep.add('B1', 'WARN', text, '최신 여부를 확인하지 못했습니다 — /plugin 에서 마켓플레이스를 갱신하세요')
    elif any(v != latest for v in versions):
        rep.add('B1', 'WARN', text, '/plugin 에서 업데이트하세요 — 설치본이 최신이 아닙니다')
    else:
        rep.add('B1', 'PASS', text)
    if mine and running_version not in versions:
        rep.add('B1', 'WARN', '지금 실행 중인 점검 스크립트는 %s, 훅이 쓰는 설치본은 %s'
                % (running_version, ', '.join(versions)), '설치본의 readiness.py 로 다시 점검하세요')
    return key


def check_scopes(rep, session_dir, key):
    """enabledPlugins: user < project < local. Only project scope reaches teammates."""
    if not key:
        return
    settings = scope_settings(session_dir)
    value, where = effective_enabled(settings, key)
    if not value:
        rep.add('B2', 'FAIL', '이 레포에서 플러그인이 꺼져 있습니다 (%s)'
                % ('%s 범위에서 false' % where if where else 'enabledPlugins 에 없음'),
                '/plugin 에서 enable 하세요')
        return
    project = settings[1][1]
    market = market_of(key)
    in_project = enabled_in(project, key)
    if in_project is not True:
        rep.add('B2', 'WARN', '켜짐 (%s 범위) — 하지만 팀원에게는 %s' % (
            where, '프로젝트 설정에서 false 라 꺼집니다' if in_project is False else '켜지지 않습니다'),
            '.claude/settings.json 에 enabledPlugins["%s"]: true 와 extraKnownMarketplaces'
            '["%s"] 를 커밋하세요' % (key, market or '<마켓플레이스>'))
    elif not market:
        rep.add('B2', 'WARN', '프로젝트 범위에서 켜짐 — 마켓플레이스가 없는 설치라 팀원이 같은 것을 '
                              '설치할 수 있는지 확인하지 못했습니다')
    elif market not in as_dict(project.get('extraKnownMarketplaces')):
        rep.add('B2', 'WARN', '프로젝트 범위에서 켜짐 — 하지만 마켓플레이스가 프로젝트 설정에 없어 '
                              '팀원이 설치할 수 없습니다',
                '.claude/settings.json 의 extraKnownMarketplaces 에 "%s" 를 추가하세요' % market)
    else:
        rep.add('B2', 'PASS', '프로젝트 범위에서 켜짐 (최종: %s) — 팀원에게도 적용됩니다' % where)


# ---------------------------------------------------------------- 훅 · 데이터 디렉터리

def hook_data_dir(key):
    """Where the installed hooks write: Claude Code gives them CLAUDE_PLUGIN_DATA,
    which is plugins/data/<name>-<marketplace>. A script run by hand without that
    variable falls back to ~/.cache/convention-guard -- a different directory."""
    if os.environ.get('CLAUDE_PLUGIN_DATA'):
        return os.environ['CLAUDE_PLUGIN_DATA']
    if market_of(key):
        return os.path.join(CLAUDE, 'plugins', 'data', '%s-%s' % (PLUGIN, market_of(key)))
    return None


def newest(pattern):
    return max((os.path.getmtime(p) for p in glob.glob(pattern)), default=None)


def check_hooks(rep, key):
    manifest = as_dict(read_json(os.path.join(plugin_root(), 'hooks', 'hooks.json')).get('hooks'))
    wired = (all(k in manifest for k in ('PreToolUse', 'PostToolUse', 'Stop'))
             and 'Write' in json.dumps(manifest['PostToolUse']))
    rep.add('B3', 'PASS' if wired else 'FAIL', 'hooks.json: PreToolUse·PostToolUse·Stop '
            + ('배선됨' if wired else '중 빠진 것이 있음'))
    data = hook_data_dir(key)
    if not data or not os.path.isdir(data):
        rep.add('B3', 'WARN', '훅 데이터 디렉터리가 없습니다 — 훅이 아직 한 번도 돌지 않았습니다',
                'Claude Code 세션에서 파일을 한 줄 고치고 턴을 끝낸 뒤 다시 점검하세요')
        return data
    touched = newest(os.path.join(data, 'touched-*.txt'))
    age_days = (time.time() - touched) / 86400 if touched else None
    if touched is None or age_days > HOOK_EVIDENCE_DAYS:
        rep.add('B3', 'WARN', '%s 에 최근 수집 기록(touched-*)이 없습니다%s' % (
            data, '' if touched is None else ' (마지막 %d일 전)' % age_days),
            '세션에서 파일을 한 줄 고친 뒤 다시 점검하세요')
    else:
        rep.add('B3', 'PASS', '수집 훅이 %d분 전에 동작 (%s — 어느 레포였는지는 구분하지 않음)'
                % (age_days * 1440, data))
    return data


def check_data_dirs(rep, hook_dir):
    """Hand-run log_report.py reads ~/.cache unless told otherwise."""
    fallback = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
                            PLUGIN)
    if not hook_dir:
        rep.add('B4', 'SKIP', '설치 기록이 없어 훅 데이터 디렉터리를 알 수 없습니다')
    elif os.path.realpath(hook_dir) == os.path.realpath(fallback):
        rep.add('B4', 'PASS', '데이터 디렉터리 하나: %s' % hook_dir)
    else:
        rep.add('B4', 'WARN', '훅은 %s 에, 손으로 돌린 스크립트는 %s 에 씁니다' % (hook_dir, fallback),
                'log_report.py·review.py 를 직접 돌릴 때는 CLAUDE_PLUGIN_DATA="%s" 를 앞에 붙이세요'
                % hook_dir)


# ---------------------------------------------------------------- userConfig

def user_options(session_dir, key):
    """{name: (scope, raw)} from pluginConfigs[key].options; later scopes win."""
    effective = {}
    for scope, data in scope_settings(session_dir):
        options = as_dict(as_dict(as_dict(data.get('pluginConfigs')).get(key)).get('options'))
        for name, value in options.items():
            effective[name] = (scope, value)
    return effective


def check_user_config(rep, session_dir, repo_root, key):
    if not key:
        return
    effective = user_options(session_dir, key)
    before = len(rep.items)
    for name in ('report_only', 'semantic_review'):
        if name in effective and not isinstance(parse_option(effective[name][1]), (bool, type(None))):
            rep.add('B5', 'FAIL', '%s=%r 는 참/거짓으로 읽히지 않아 기본값이 쓰입니다'
                    % (name, effective[name][1]), '/plugin 설정에서 true 또는 false 로')
    if 'log_dir' in effective:
        check_log_dir(rep, repo_root, parse_option(effective['log_dir'][1]))
    if len(rep.items) == before:
        shown = ', '.join('%s=%r(%s)' % (n, v, s) for n, (s, v) in sorted(effective.items()))
        rep.add('B5', 'PASS', 'userConfig: %s — 레포 config.yaml 의 mode·semantic_review 가 항상 우선'
                % (shown or '모두 기본값'))


def check_log_dir(rep, repo_root, raw):
    """A relative log_dir resolves against the hook's cwd, i.e. inside each repo."""
    if not isinstance(raw, str) or not raw:
        return                                  # unset: the engine uses the data dir
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        rep.add('B5', 'FAIL', 'log_dir=%r 는 상대경로입니다 — 훅이 레포마다 그 레포 안에 로그를 '
                '씁니다 (여기서는 %s)' % (raw, os.path.normpath(os.path.join(repo_root, path))),
                '레포 밖의 절대경로로 바꾸세요 (예: ~/convention-guard-logs)')
        return
    real, top = os.path.realpath(path), os.path.realpath(repo_root)
    if real == top or real.startswith(top + os.sep):
        rep.add('B5', 'FAIL', 'log_dir 이 이 레포 안입니다 (%s) — git 에 잡힙니다' % path,
                '레포 밖의 절대경로로 바꾸세요')
