#!/usr/bin/env python3
"""What the bundled rules report on four fixture repos, pinned.

A refactor of the engine must not quietly change which (rule, file, line)
the checker reports. When a change is intentional, regenerate and review the
diff of the golden file in the same commit:

    python3 tests/integration/test_parity.py --update
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, isolated_env, run_script, tempdir  # noqa: E402
from helpers.fixtures import BUILDERS  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden', 'parity.json')
MODES = {'working-tree': [], 'all': ['--all']}


def findings(repo, data, extra):
    proc = run_script('scan.py', ['--cwd', repo, '--json', '--no-lint', '--max-hits', '50',
                                  '--fail-on', 'never'] + extra,
                      env=isolated_env(data), cwd=repo)
    if proc.returncode != 0:
        return ['<exit %d> %s' % (proc.returncode, proc.stderr.strip())]
    report = json.loads(proc.stdout)
    return sorted('%s %s:%d' % (f['rule_id'], loc['file'], loc['line'])
                  for f in report['findings'] for loc in f['locations'])


def collect():
    out = {}
    for name, build in sorted(BUILDERS.items()):
        for mode, extra in MODES.items():
            with tempdir() as tmp:
                repo = build(os.path.join(tmp, 'repo'))
                out['%s/%s' % (name, mode)] = findings(repo, os.path.join(tmp, 'data'), extra)
    return out


def main():
    current = collect()
    if '--update' in sys.argv:
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, 'w', encoding='utf-8') as fh:
            json.dump(current, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write('\n')
        print('golden 갱신: %s' % GOLDEN)
        return 0
    with open(GOLDEN, encoding='utf-8') as fh:
        golden = json.load(fh)
    for key in sorted(set(golden) | set(current)):
        want, got = golden.get(key, []), current.get(key, [])
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        check('%s matches golden' % key, not missing and not extra,
              'missing=%r extra=%r' % (missing, extra))
    # A repo-wide audit that reports less than a change scan is a scope bug,
    # not a golden update: --all once read `git ls-files` and skipped every
    # file the change had just created.
    for name in sorted({key.split('/')[0] for key in current}):
        whole = set(current.get('%s/all' % name, []))
        change = set(current.get('%s/working-tree' % name, []))
        check('%s: --all covers what --working-tree finds' % name, change <= whole,
              'working-tree only: %r' % sorted(change - whole))
    return finish('규칙 발동 패리티')


if __name__ == '__main__':
    sys.exit(main())
