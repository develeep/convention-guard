#!/usr/bin/env python3
"""The performance harness still runs.

No timing is asserted -- a machine-dependent threshold in the per-turn suite
would fail for reasons that have nothing to do with the code (design §7 keeps
the numbers as targets). This only keeps `tests/perf/run.py` from rotting.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish, tempdir  # noqa: E402


def case_harness_runs():
    print('case_harness_runs:')
    with tempdir() as tmp:
        out = os.path.join(tmp, 'perf.json')
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'tests', 'perf', 'run.py'), '--quick',
             '--json', out],
            capture_output=True, text=True, cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        check('the harness exits cleanly', proc.returncode == 0, proc.stderr.strip()[-300:])
        check('it writes a result file', os.path.exists(out))
        if not os.path.exists(out):
            return
        payload = json.load(open(out, encoding='utf-8'))
        check('the four numbers are there',
              {'stop', 'edit_pre', 'edit_post', 'bash_pre', 'bash_post', 'gate'}
              <= set(payload['rows']), sorted(payload['rows']))
        check('the environment is recorded', {'python', 'platform', 'commit'} <= set(payload['env']))
        check('the gate turn found its candidate', 'php-no-debug-output' in payload['gate_output']
              or 'error' in payload['gate_output'], payload['gate_output'])


if __name__ == '__main__':
    case_harness_runs()
    sys.exit(finish('perf harness smoke'))
