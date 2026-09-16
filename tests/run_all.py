#!/usr/bin/env python3
"""Every check in one command. Put this in CI.

    python3 tests/run_all.py
    python3 tests/run_all.py --repo /path/to/repo   # include the repo's rules

`scripts/test_rules.py` protects the rules (fixtures per rule); the files next
to this one protect the engine: what counts as "this change", where a linter
finding is allowed to block, and how a block is measured afterwards.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SUITES = [
    ('규칙 픽스처', [os.path.join(ROOT, 'scripts', 'test_rules.py')]),
    ('변경 앵커', [os.path.join(HERE, 'test_diff_anchor.py')]),
    ('린터 앵커링', [os.path.join(HERE, 'test_lint_anchor.py')]),
    ('세션 정책', [os.path.join(HERE, 'test_session_policy.py')]),
    ('규칙 후보 추천', [os.path.join(HERE, 'test_survey.py')]),
    ('에이전트 문서 생성', [os.path.join(HERE, 'test_agents_doc.py')]),
    ('자체 설정 제외', [os.path.join(HERE, 'test_self_exclude.py')]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', help='레포 로컬 규칙까지 픽스처 테스트에 포함')
    parser.add_argument('--quiet', action='store_true', help='실패한 스위트만 출력')
    args = parser.parse_args()

    failed = []
    for label, cmd in SUITES:
        argv = [sys.executable] + cmd
        if args.repo and cmd[0].endswith('test_rules.py'):
            argv += ['--repo', args.repo]
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
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
