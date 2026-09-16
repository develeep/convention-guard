"""Paths, session state and the JSONL firing log."""

import json
import os
import tempfile
import time

if os.environ.get('CONVENTION_GUARD_NO_PYYAML'):
    _pyyaml = None  # forces the bundled parser; used by the self-test
else:
    try:
        import yaml as _pyyaml
    except Exception:  # pragma: no cover - optional dependency
        _pyyaml = None

from . import miniyaml


def yaml_load(text):
    if _pyyaml is not None:
        return _pyyaml.safe_load(text) or {}
    return miniyaml.load(text)


def read_yaml(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return yaml_load(fh.read()) or {}


def plugin_root():
    env = os.environ.get('CLAUDE_PLUGIN_ROOT')
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def project_dir(cwd=None):
    return os.path.abspath(os.environ.get('CLAUDE_PROJECT_DIR') or cwd or os.getcwd())


def user_option(key, default=None):
    """userConfig value, delivered to hooks as CLAUDE_PLUGIN_OPTION_<KEY>."""
    raw = os.environ.get('CLAUDE_PLUGIN_OPTION_' + key.upper())
    if raw is None or raw == '':
        return default
    low = raw.strip().lower()
    if low in ('true', '1', 'yes', 'on'):
        return True
    if low in ('false', '0', 'no', 'off'):
        return False
    return raw.strip()


def data_dir():
    env = os.environ.get('CLAUDE_PLUGIN_DATA')
    base = env if env else os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
        'convention-guard',
    )
    try:
        os.makedirs(base, exist_ok=True)
        return base
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), 'convention-guard')
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _safe(name):
    return ''.join(c if (c.isalnum() or c in '-_') else '_' for c in str(name))[:120]


def state_path(session_id, kind=''):
    """Per-session state. `kind` gives a concern its own file.

    The Stop event runs its hooks in parallel, so the deterministic check and
    the optional semantic review would otherwise read-modify-write one file
    and drop each other's counters -- including the block counter the loop
    guard depends on.
    """
    suffix = '-%s' % _safe(kind) if kind else ''
    return os.path.join(data_dir(),
                        'session-%s%s.json' % (_safe(session_id or 'unknown'), suffix))


DEFAULT_STATE = {
    'touched': [],
    'checked_prompt_ids': [],
    'fired_rules': [],
    'consecutive_blocks': 0,
    'blocks': 0,
    'pending': [],
    'unresolved': [],
}


def load_state(session_id, kind=''):
    path = state_path(session_id, kind)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, list(value) if isinstance(value, list) else value)
    return state


def save_state(session_id, state, kind=''):
    path = state_path(session_id, kind)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def remember_plugin_root():
    """Leave the plugin's install path where a subagent can find it.

    `${CLAUDE_PLUGIN_ROOT}` is substituted into hook `command`/`args`, not
    into an agent hook's prompt, and the subagent's own shell does not inherit
    it. The command hooks that do get the variable write it here.
    """
    root = os.environ.get('CLAUDE_PLUGIN_ROOT')
    if not root:
        return None
    target = os.path.join(data_dir(), 'plugin-root')
    try:
        if os.path.isfile(target):
            with open(target, 'r', encoding='utf-8') as fh:
                if fh.read().strip() == root:
                    return target
        with open(target, 'w', encoding='utf-8') as fh:
            fh.write(root)
    except OSError:
        return None
    return target


def log_path():
    """Where firings.jsonl lives. The log_dir option moves only this file --
    session state stays in the plugin data dir, so a shared team log never
    collides with another machine's in-flight session."""
    override = user_option('log_dir')
    if isinstance(override, str) and override:
        path = os.path.expanduser(override)
        try:
            os.makedirs(path, exist_ok=True)
            return os.path.join(path, 'firings.jsonl')
        except OSError:
            pass
    return os.path.join(data_dir(), 'firings.jsonl')


def log_event(record):
    """Append one firing record to the JSONL log used by the tuning cycle."""
    record = dict(record)
    record.setdefault('ts', time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    path = log_path()
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    except OSError:
        pass


def gc_old_sessions(max_age_days=7):
    cutoff = time.time() - max_age_days * 86400
    try:
        base = data_dir()
        for name in os.listdir(base):
            if not name.startswith('session-'):
                continue
            full = os.path.join(base, name)
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
    except OSError:
        pass
