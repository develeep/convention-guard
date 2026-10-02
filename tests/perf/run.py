#!/usr/bin/env python3
"""What the hooks cost: the four numbers of docs/design-4.0.md §7.

    python3 tests/perf/run.py                    # all of it, prints a table
    python3 tests/perf/run.py --json out.json    # and writes the numbers
    python3 tests/perf/run.py --quick            # small and fast (the smoke test)

    stop        Stop hook, 60 changed files, no rule gate matches (median ms)
    stop_gated  the same, but every file has catch blocks a structure condition clears
    collect     one collect hook: Edit Pre / Post, Bash Pre / Post (median ms)
    engine      tree-sitter import, and analyze() of a 1,000-line file per language
    gate        Stop hook with one candidate whose rule has a structure condition

These are targets, not a gate (design §7): a measurement that depends on the
machine does not fail the test suite. Medians, because a mean follows
whatever the garbage collector did. The JSON records the interpreter, the
platform and the commit, so two runs are only compared on the same machine.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, HERE)

import rig  # noqa: E402
from helpers import corpus  # noqa: E402

TARGETS = {'stop': 60.0, 'edit_pre': 25.0, 'edit_post': 25.0, 'bash_pre': 35.0,
           'bash_post': 35.0}
NEUTRAL = {'php': ['        $total = 1;'], 'js': ['    const total = 1;']}


def median_ms(call, repeats):
    samples = []
    for _ in range(repeats):
        began = time.perf_counter()
        call()
        samples.append((time.perf_counter() - began) * 1000)
    return round(statistics.median(samples), 1)


def run(cmd, stdin, env, cwd):
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, cwd=cwd)


def turn(files, repeats, trigger=None, gated=False):
    """(Stop median, collect medians, last Stop output) over a fresh change set."""
    rig.TRIGGERS = dict(NEUTRAL)
    tmp = rig.scratch()
    try:
        repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
        os.makedirs(data)
        touched = rig.change_set(repo, files=files, gated=gated)
        if trigger:
            target = next(t for t in reversed(touched) if t.endswith('.php'))
            path = os.path.join(repo, target)
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(trigger)
        env, check, session = rig.run_hook(repo, touched, data)
        out = {}
        stop = lambda: run([sys.executable, check], rig.stop_payload(session, repo, 1), env, repo)
        run([sys.executable, check], rig.stop_payload(session, repo, 0), env, repo)   # warm
        out['stop'] = median_ms(stop, repeats)
        last = stop().stdout
        collect = os.path.join(os.path.dirname(check), 'collect.py')
        for name, tool, extra in (('edit', 'Edit', {'file_path': touched[0]}),
                                  ('bash', 'Bash', {'command': 'ls'})):
            for event in ('PreToolUse', 'PostToolUse'):
                payload = json.dumps({'session_id': session, 'cwd': repo, 'tool_name': tool,
                                      'tool_use_id': 'perf-%s' % name, 'tool_input': extra,
                                      'hook_event_name': event})
                key = '%s_%s' % (name, 'pre' if event == 'PreToolUse' else 'post')
                out[key] = median_ms(
                    lambda p=payload: run([sys.executable, collect], p, env, repo), repeats)
        return out, last
    finally:
        rig.clean(tmp)


def engine_numbers(repeats):
    """Import time in a fresh process, and analyze() of a 1,000-line file."""
    code = ('import sys, time; sys.path.insert(0, %r); t = time.perf_counter(); '
            'from lib.engine import loader; e = loader.get(); '
            'print(e.ok, (time.perf_counter() - t) * 1000)' % os.path.join(ROOT, 'scripts'))
    samples, ok = [], False
    for _ in range(repeats):
        proc = run([sys.executable, '-c', code], '', dict(os.environ), ROOT)
        parts = proc.stdout.split()
        if len(parts) == 2:
            ok = parts[0] == 'True'
            samples.append(float(parts[1]))
    out = {'engine': ok, 'engine_import': round(statistics.median(samples), 1) if samples else None}
    if not ok:
        return out
    from lib import structure
    for language in ('php', 'js', 'py'):
        text = corpus.make_file(language, seed=3, lines=1000, broken=0.0)

        def once(t=text, lang=language):
            structure.reset_cache()
            structure.analyze(t, lang)
        out['analyze_%s_1000' % language] = median_ms(once, repeats)
    return out


def environment():
    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    return {'python': platform.python_version(), 'platform': platform.platform(),
            'commit': commit}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', default=None)
    parser.add_argument('--quick', action='store_true', help='10개 파일, 반복 3회')
    args = parser.parse_args(argv)
    files, repeats = (10, 3) if args.quick else (60, 15)

    rows, _ = turn(files, repeats)
    rows['stop_gated'] = turn(files, repeats, gated=True)[0]['stop']
    gate, gate_out = turn(files, repeats, trigger='dd($x);\n')
    rows['gate'] = gate['stop']
    rows.update(engine_numbers(3 if args.quick else 10))
    result = {'stage': 'perf-4.0', 'files': files, 'env': environment(), 'targets': TARGETS,
              'rows': rows, 'gate_output': gate_out[:200]}

    for key in ('stop', 'stop_gated', 'edit_pre', 'edit_post', 'bash_pre', 'bash_post', 'gate',
                'engine_import', 'analyze_php_1000', 'analyze_js_1000', 'analyze_py_1000'):
        value = rows.get(key)
        target = TARGETS.get(key)
        mark = '' if target is None or value is None else ('  ✓' if value <= target else '  > 목표')
        print('%-18s %8s ms%s' % (key, '-' if value is None else value,
                                   ('  (목표 %.0f)' % target if target else '') + mark))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
