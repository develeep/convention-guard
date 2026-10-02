"""The structure engine (tree-sitter): status, install, and the lock file.

    python3 engine.py status            # 설치 여부, 경로, 마지막 시도
    python3 engine.py ensure            # 없으면 설치하고 끝날 때까지 기다림 (CI)
    python3 engine.py ensure --dir D    # D 아래에 설치 (CONVENTION_GUARD_ENGINE_DIR 과 같음)
    python3 engine.py lock              # PyPI 에서 lock.json 다시 만들기 (개발용)
    python3 engine.py verify-lock       # lock 의 휠이 PyPI 와 같은지 (릴리스 검증)

Offline: put the wheels named in lock.json in a directory and set
CONVENTION_GUARD_WHEELS to it; the sha256 check is the same.

Exit codes: 0 ok, 1 the engine is not there / the lock does not match, 2 usage.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import fmt  # noqa: E402
from lib.engine import install, loader, tags  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description='convention-guard 구조 엔진')
    parser.add_argument('command', choices=['status', 'ensure', 'lock', 'verify-lock'])
    parser.add_argument('--dir', help='엔진 디렉터리 (기본: 플러그인 데이터 디렉터리/engine)')
    parser.add_argument('--quiet', action='store_true', help='ensure: 아무것도 출력하지 않음')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.dir:
        os.environ['CONVENTION_GUARD_ENGINE_DIR'] = os.path.abspath(args.dir)

    if args.command == 'lock':
        lock = install.build_lock()
        with open(install.LOCK, 'w', encoding='utf-8', newline='\r\n') as fh:
            json.dump(lock, fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        print('%s — %d개 패키지, id %s' % (install.LOCK, len(lock['packages']),
                                          install.lock_id(lock)))
        return 0

    if args.command == 'verify-lock':
        problems = install.verify_lock()
        for problem in problems:
            fmt.eprint('error', problem)
        if not problems:
            print('lock.json 의 휠이 모두 PyPI 와 같습니다')
        return 1 if problems else 0

    if args.command == 'ensure':
        try:
            path = install.ensure()
        except install.InstallError as exc:
            if not args.quiet:
                fmt.eprint('error', '구조 엔진을 설치하지 못했습니다 — %s' % exc)
            return 1
        if not args.quiet:
            print('구조 엔진: %s' % path)
        return 0

    engine = loader.get()
    info = {'ok': engine.ok, 'path': getattr(engine, 'path', None),
            'reason': None if engine.ok else engine.describe(),
            'platform': tags.describe(tags.Interpreter()),
            'dir': install.base_dir(), 'last': install.read_status()}
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=1))
    else:
        print('구조 엔진: %s' % (info['path'] if engine.ok else '없음 — %s' % info['reason']))
        print('플랫폼: %s' % info['platform'])
    return 0 if engine.ok else 1


if __name__ == '__main__':
    sys.exit(main())
