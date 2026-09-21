"""Where things live: the plugin, the project, and this install's data dir."""

import os
import subprocess
import tempfile


def plugin_root():
    env = os.environ.get('CLAUDE_PLUGIN_ROOT')
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def project_dir(cwd=None):
    """An explicit path wins over the environment.

    Skills export CLAUDE_PROJECT_DIR for every command they run, so letting the
    env win would make `--cwd /other/repo` silently act on the session's repo.
    """
    return os.path.abspath(cwd or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())


def hook_project_dir(payload):
    """Hooks get the project root from Claude Code; the payload cwd may be a subdir."""
    return os.path.abspath(os.environ.get('CLAUDE_PROJECT_DIR')
                           or (payload or {}).get('cwd') or os.getcwd())


def git_toplevel(path):
    """The work tree root containing `path`, or `path` itself outside git.

    Every relative path in the engine is relative to the work tree root, which
    is also what `git diff --name-only` prints -- starting from a subdirectory
    would make the two disagree.
    """
    try:
        # 5s, not 15: the PostToolUse hook that calls this gets 10s total from
        # hooks.json. Waiting longer than the caller is allowed to live means
        # the hook is killed mid-call, the touched file is never recorded, and
        # the Stop check silently skips that turn (_scan has no git fallback).
        proc = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=path,
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return path
    top = proc.stdout.strip()
    return os.path.abspath(top) if proc.returncode == 0 and top else path


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


def safe_name(name):
    return ''.join(c if (c.isalnum() or c in '-_') else '_' for c in str(name))[:120]


def atomic_write(path, text):
    """Write via a per-process temp file, so two writers never share one."""
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
