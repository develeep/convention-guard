#!/usr/bin/env python3
"""The performance harness still runs.

No timing is asserted -- a machine-dependent threshold in the per-turn suite
would fail for reasons that have nothing to do with the code. This only keeps
`tests/perf/run.py` from rotting between the U1 spike and the U2 re-measure
(NR-25).
"""
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
            [sys.executable, os.path.join(ROOT, 'tests', 'perf', 'run.py'),
             '--corpus', 'synthetic', '--max-lines', '100', '--json', out],
            capture_output=True, text=True, cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        check('the harness exits cleanly', proc.returncode == 0,
              proc.stderr.strip()[-300:])
        check('it writes a result file', os.path.exists(out))
        if os.path.exists(out):
            import json
            payload = json.load(open(out, encoding='utf-8'))
            check('the result carries the fields U2 compares against',
                  {'stage', 'env', 'budget', 'rows'} <= set(payload),
                  str(sorted(payload)))
            check('the environment is recorded',
                  {'python', 'platform', 'baseline_commit'} <= set(payload['env']))


def case_end_to_end_stage_exists():
    """The gate B path imports and parses; it is not run here (minutes long)."""
    print('case_end_to_end_stage_exists:')
    proc = subprocess.run(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, %r); import rig, run; '
         'print(hasattr(run, "end_to_end_rows"), hasattr(rig, "rules_with_conditions"))'
         % os.path.join(ROOT, 'tests', 'perf')],
        capture_output=True, text=True, cwd=ROOT,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    check('the end_to_end stage and its rig import cleanly',
          proc.returncode == 0 and 'True True' in proc.stdout,
          (proc.stdout + proc.stderr).strip()[-300:])


def main():
    case_harness_runs()
    case_end_to_end_stage_exists()
    return finish('perf harness smoke')


if __name__ == '__main__':
    sys.exit(main())
