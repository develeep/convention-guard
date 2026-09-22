"""Setting up a measurement: rules with conditions, a change to scan, a baseline.

Gate B asks "how many rules can carry a structure condition before the hook
gets slower than the budget", and the only honest way to answer is to run the
hook -- interpreter start, imports, rule loading and all (NR-U2-03). So the
rig builds a throwaway repository, copies the rule bundle, puts conditions on
the first N rules, and leaves the real `rules/` untouched.

Nothing here is committed anywhere: every path is a temporary directory and
the baseline is a `git worktree` that gets removed afterwards.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from helpers import isolated_env, make_repo, run_script  # noqa: E402
from lib import rules as rulelib  # noqa: E402
from lib.rules import schema  # noqa: E402
from lib.yamlio import read as read_yaml  # noqa: E402

CONDITION_LINE = 'detect:\n  not_in: [comment, string]\n'
# `absent` and `paired` cannot carry structure conditions at all, so they are
# not candidates for the injection (DR-04)
CONDITIONABLE = ('line', 'requires', 'file')


def conditionable_rules(limit=None):
    """Core rule files that could take a structure condition, id order."""
    out = []
    base = os.path.join(ROOT, 'rules')
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            if not name.endswith(('.yaml', '.yml')):
                continue
            path = os.path.join(dirpath, name)
            try:
                raw = read_yaml(path)
                rule = schema.normalize(raw, path, 'core')
            except Exception:                    # noqa: BLE001 -- skip what will not load
                continue
            if rule['kind'] in CONDITIONABLE:
                out.append((rule['id'], os.path.relpath(path, base)))
    out.sort()
    return out[:limit] if limit is not None else out


def rules_with_conditions(count, dest):
    """Copy the rule bundle into `dest`, conditioning the first `count` rules.

    Returns the number actually conditioned -- fewer than asked when the
    bundle does not have that many eligible rules.
    """
    bundle = os.path.join(dest, 'rules')
    shutil.copytree(os.path.join(ROOT, 'rules'), bundle)
    conditioned = 0
    for _rule_id, relpath in conditionable_rules(count):
        path = os.path.join(bundle, relpath)
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        if '\ndetect:\n' not in text:
            continue
        text = text.replace('\ndetect:\n', '\ndetect:\n  not_in: [comment, string]\n', 1)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        conditioned += 1
    return conditioned


def plugin_root_with(bundle_parent):
    """A plugin root whose `rules/` is the conditioned copy.

    Everything else (presets, stacks, skills) is symlinked from the real root
    so only the rules differ from a normal run.
    """
    root = os.path.join(bundle_parent, 'plugin')
    os.makedirs(root, exist_ok=True)
    for name in sorted(os.listdir(ROOT)):
        if name in ('rules', '.git', 'aidlc-docs', '.venv', 'venv', 'tests'):
            continue
        target = os.path.join(ROOT, name)
        link = os.path.join(root, name)
        if not os.path.exists(link):
            os.symlink(target, link)
    rules_link = os.path.join(root, 'rules')
    if not os.path.exists(rules_link):
        os.symlink(os.path.join(bundle_parent, 'rules'), rules_link)
    return root


# Lines that real core rules look for. Without them the generated corpus is
# syntactically plausible but touches no rule, every condition stays unused,
# and the measurement compares two idle hooks.
TRIGGERS = {
    'php': ['        dd($user);', '        var_dump($x);',
            '        // dd($cached);', '        $s = "dd($inert)";',
            '        Log::info("x");'],
    'js': ['    console.log(value);', '    // console.log(skipped);',
           '    const s = "console.log(inert)";', '    debugger;'],
}


def change_set(dest, files=60, seed=7):
    """A git repo with `files` changed but uncommitted -- what a turn looks like.

    The shape follows the baseline the performance note in
    docs/development.md was measured on: 60 touched files.
    """
    import random

    rng = random.Random(seed)
    sys.path.insert(0, os.path.join(ROOT, 'tests'))
    from helpers import corpus

    committed = {'composer.json': json.dumps({'require': {'laravel/framework': '^10.0'}}),
                 'artisan': '#!/usr/bin/env php\n'}
    for index in range(files):
        language = 'php' if index % 3 else 'js'
        name = 'app/Gen%02d.%s' % (index, 'php' if language == 'php' else 'js')
        committed[name] = corpus.make_file(language, seed=seed + index, lines=120,
                                           density='normal', broken=0.0)
    make_repo(dest, committed)

    for index in range(files):
        language = 'php' if index % 3 else 'js'
        name = 'app/Gen%02d.%s' % (index, 'php' if language == 'php' else 'js')
        body = corpus.make_file(language, seed=seed + 1000 + index, lines=120,
                                density='normal', broken=0.0)
        # a few real violations per file, including ones a structure condition
        # is supposed to filter (a commented and a quoted occurrence)
        body += '\n'.join(rng.sample(TRIGGERS[language], len(TRIGGERS[language]))) + '\n'
        with open(os.path.join(dest, name), 'w', encoding='utf-8') as handle:
            handle.write(body)
    return sorted('app/Gen%02d.%s' % (i, 'php' if i % 3 else 'js') for i in range(files))


def baseline_worktree(ref, dest):
    """Lay `ref` out in `dest` so its own check.py can be run. Caller removes it."""
    subprocess.run(['git', 'worktree', 'add', '--detach', dest, ref],
                   cwd=ROOT, capture_output=True, text=True, check=True)
    return dest


def remove_worktree(dest):
    subprocess.run(['git', 'worktree', 'remove', '--force', dest],
                   cwd=ROOT, capture_output=True, text=True)


def run_hook(repo, touched, data_dir, plugin_root=None, session='perf'):
    """One Stop-hook turn over `touched`, the way Claude Code drives it."""
    env = isolated_env(data_dir, CLAUDE_PROJECT_DIR=repo)
    if plugin_root:
        env['CLAUDE_PLUGIN_ROOT'] = plugin_root
    script = os.path.join(plugin_root or ROOT, 'scripts')
    for relpath in touched:
        run_script(os.path.join(script, 'collect.py'),
                   stdin=json.dumps({'session_id': session, 'cwd': repo,
                                     'hook_event_name': 'PostToolUse',
                                     'tool_name': 'Edit',
                                     'tool_input': {'file_path': relpath}}),
                   env=env, cwd=repo)
    return env, os.path.join(script, 'check.py'), session


def stop_payload(session, repo, prompt_id):
    return json.dumps({'session_id': session, 'cwd': repo, 'prompt_id': str(prompt_id),
                       'hook_event_name': 'Stop', 'stop_hook_active': False,
                       'last assistant message': 'done.'})


def scratch():
    return tempfile.mkdtemp(prefix='cg-perf-')


def clean(path):
    shutil.rmtree(path, ignore_errors=True)
