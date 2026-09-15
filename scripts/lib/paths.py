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


def state_path(session_id):
    return os.path.join(data_dir(), 'session-%s.json' % _safe(session_id or 'unknown'))


DEFAULT_STATE = {
    'touched': [],
    'checked_prompt_ids': [],
    'fired_rules': [],
    'blocks': 0,
    'pending': [],
}


def load_state(session_id):
    path = state_path(session_id)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            state = json.load(fh)
    except Exception:
        return dict(DEFAULT_STATE, touched=[], checked_prompt_ids=[],
                    fired_rules=[], pending=[])
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, value if not isinstance(value, list) else [])
    return state


def save_state(session_id, state):
    path = state_path(session_id)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


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
