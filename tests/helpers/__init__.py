"""Shared test plumbing: a tiny assertion recorder, throwaway git repos, and a
runner for the real hook scripts.

Tests stay plain scripts (no pytest) so the plugin keeps zero dependencies.
Each test file does:

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from helpers import ...
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

FAILED = []


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def finish(label):
    """Print the summary line and return the process exit code."""
    if FAILED:
        print('\n실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('\n통과 — %s' % label)
    return 0


@contextlib.contextmanager
def tempdir():
    path = tempfile.mkdtemp()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run_cases(cases, label, fresh_dir=True):
    """Run `case(tmp)` for each case in its own temp dir."""
    for case in cases:
        print('%s:' % case.__name__)
        if fresh_dir:
            with tempdir() as tmp:
                case(tmp)
        else:
            case()
    return finish(label)


# ---------------------------------------------------------------- git repos

def git(repo, *args, check_rc=True):
    return subprocess.run(['git', '-C', repo] + list(args), check=check_rc,
                          capture_output=True, text=True)


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(body)


def commit(repo, message='commit'):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '--allow-empty', '-m', message)


def make_repo(repo, files=None, message='init'):
    """git init + optional committed files. Returns the repo path."""
    os.makedirs(repo, exist_ok=True)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 't@t')
    git(repo, 'config', 'user.name', 't')
    git(repo, 'config', 'core.autocrlf', 'false')
    for rel, body in (files or {}).items():
        write(repo, rel, body)
    commit(repo, message)
    return repo


LARAVEL_COMPOSER = '{"require":{"laravel/framework":"^11.0"}}'


def isolated_env(data_dir, **extra):
    """Environment for a hook/CLI subprocess that cannot see this machine's
    own convention-guard state (user rules under ~, cache dirs)."""
    home = os.path.join(data_dir, 'home')
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('CLAUDE_PLUGIN_OPTION_'):
            del env[key]
    env.update({'HOME': home, 'XDG_CACHE_HOME': os.path.join(home, '.cache'),
                'CLAUDE_PLUGIN_ROOT': ROOT, 'CLAUDE_PLUGIN_DATA': data_dir,
                'PYTHONDONTWRITEBYTECODE': '1'})
    env.pop('CLAUDE_PROJECT_DIR', None)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def run_script(script, args=(), stdin=None, env=None, cwd=None):
    path = script if os.path.isabs(script) else os.path.join(SCRIPTS, script)
    return subprocess.run([sys.executable, path] + list(args),
                          input=stdin, capture_output=True, text=True,
                          env=env, cwd=cwd)


# ---------------------------------------------------------------- hook session

class Session:
    """Drives collect.py / check.py the way Claude Code does, one turn at a time."""

    def __init__(self, repo, data, name='s1', plugin_root=None, **env):
        self.repo, self.data, self.name = repo, data, name
        self.env = isolated_env(data, CLAUDE_PROJECT_DIR=repo, **env)
        if plugin_root:
            self.env['CLAUDE_PLUGIN_ROOT'] = plugin_root

    def _run(self, script, payload):
        return run_script(script, stdin=json.dumps(payload), env=self.env, cwd=self.repo)

    def touch(self, rel, tool='Edit'):
        return self._run('collect.py', {'session_id': self.name, 'cwd': self.repo,
                                        'hook_event_name': 'PostToolUse',
                                        'tool_name': tool,
                                        'tool_input': {'file_path': rel}})

    def stop(self, prompt_id, message='done.', stop_hook_active=False):
        proc = self._run('check.py', {
            'session_id': self.name, 'cwd': self.repo, 'prompt_id': prompt_id,
            'hook_event_name': 'Stop', 'stop_hook_active': stop_hook_active,
            'last_assistant_message': message})
        try:
            out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except ValueError:
            out = {'_raw': proc.stdout}
        return {'decision': out.get('decision'), 'reason': out.get('reason') or '',
                'summary': out.get('systemMessage') or '', 'stderr': proc.stderr,
                'raw': out}

    def turn(self, rel, body, prompt_id, **kwargs):
        write(self.repo, rel, body)
        self.touch(rel)
        return self.stop(prompt_id, **kwargs)

    def state(self, kind=''):
        suffix = '-%s' % kind if kind else ''
        path = os.path.join(self.data, 'session-%s%s.json' % (self.name, suffix))
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)

    def events(self, kind=None):
        path = os.path.join(self.data, 'firings.jsonl')
        if not os.path.isfile(path):
            return []
        with open(path, encoding='utf-8') as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return [r for r in rows if kind is None or r.get('event') == kind]
