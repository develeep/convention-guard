#!/usr/bin/env python3
"""Every check in one command. Put this in CI.

    python3 tests/run_all.py
    python3 tests/run_all.py --repo /path/to/repo   # include the repo's own rules
    python3 tests/run_all.py --quiet                # print failing suites only

Suites are discovered: every `test_*.py` under tests/, plus the rule fixture
runner. Each suite is a plain script whose exit code is the verdict.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def suites(repo=None):
    found = []
    for dirpath, dirnames, filenames in os.walk(HERE):
        dirnames[:] = sorted(d for d in dirnames if d not in ('helpers', '__pycache__'))
        for name in sorted(filenames):
            if name.startswith('test_') and name.endswith('.py'):
                path = os.path.join(dirpath, name)
                cmd = [path]
                if repo and name == 'test_rule_fixtures.py':
                    cmd += ['--repo', repo]
                found.append((os.path.relpath(path, HERE), cmd))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', help='레포 로컬 규칙까지 픽스처 테스트에 포함')
    parser.add_argument('--quiet', action='store_true', help='실패한 스위트만 출력')
    args = parser.parse_args()

    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    failed = []
    for label, cmd in suites(args.repo):
        proc = subprocess.run([sys.executable] + cmd, capture_output=True, text=True,
                              cwd=ROOT, env=env)
        status = 'PASS' if proc.returncode == 0 else 'FAIL'
        print('[%s] %s' % (status, label))
        if proc.returncode != 0:
            failed.append(label)
        if proc.returncode != 0 or not args.quiet:
            for line in (proc.stdout + proc.stderr).rstrip().split('\n'):
                if line:
                    print('   %s' % line)
    if failed:
        print('\n실패한 스위트: %s' % ', '.join(failed))
        return 1
    print('\n전체 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
