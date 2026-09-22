#!/usr/bin/env python3
"""On Python 3.8 the plugin has to say so, and still not break the agent.

3.0 raised the floor to 3.9 (NFR-04.1). Someone on 3.8 who upgrades would
otherwise meet a SyntaxError from whichever module happens to be imported
first, which says nothing about what to do. The guard runs before any of our
own modules are read, and it stays quiet on a supported interpreter.
"""
import ast
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish  # noqa: E402

GUARD = os.path.join(ROOT, 'scripts', 'lib', '__init__.py')
# the guard is read by the interpreter it is warning about, so it may only use
# syntax that 3.8 can parse -- 3.9+ constructs would fail before it can speak
PRE39_SYNTAX = (getattr(ast, 'Match', None), getattr(ast, 'TypeAlias', None))


def run(script, argv0=None, version=(3, 8, 0)):
    """The entry point, with sys.version_info faked to `version`."""
    stub = (
        'import sys, collections\n'
        'V = collections.namedtuple("V", "major minor micro releaselevel serial")\n'
        'sys.version_info = V(%d, %d, %d, "final", 0)\n'
        'sys.argv = [%r]\n'
        'sys.path.insert(0, %r)\n'
        'exec(open(%r, encoding="utf-8").read(), {"__name__": "__main__", "__file__": %r})\n'
        % (version[0], version[1], version[2], argv0 or script,
           os.path.join(ROOT, 'scripts'),
           os.path.join(ROOT, 'scripts', script), os.path.join(ROOT, 'scripts', script))
    )
    return subprocess.run([sys.executable, '-c', stub], input='{}',
                          capture_output=True, text=True,
                          cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))


def main():
    with open(GUARD, encoding='utf-8') as fh:
        source = fh.read()
    check('가드가 비어 있지 않다', 'version_info' in source, source[:200])

    tree = ast.parse(source)
    used = {type(node) for node in ast.walk(tree)}
    check('가드는 3.8 이 읽을 수 있는 구문만 쓴다',
          not any(kind and kind in used for kind in PRE39_SYNTAX), sorted(map(str, used)))

    cli = run('scan.py')
    check('CLI 는 원인을 말한다', 'Python 3.9' in (cli.stdout + cli.stderr),
          cli.stdout + cli.stderr)
    check('CLI 는 현재 버전을 말한다', '3.8' in (cli.stdout + cli.stderr),
          cli.stdout + cli.stderr)
    check('CLI 는 무엇을 하면 되는지 말한다',
          'migration-3.0' in (cli.stdout + cli.stderr), cli.stdout + cli.stderr)

    for script in ('check.py', 'collect.py'):
        hook = run(script)
        check('%s 는 에이전트를 막지 않는다 (종료 코드 0)' % script, hook.returncode == 0,
              (hook.returncode, hook.stdout, hook.stderr))
        try:
            payload = json.loads(hook.stdout or '{}')
        except ValueError:
            payload = None
        check('%s 는 조용히 건너뛰지 않는다' % script,
              isinstance(payload, dict) and 'Python 3.9' in payload.get('systemMessage', ''),
              hook.stdout)

    ok = run('scan.py', version=(3, 9, 0))
    check('3.9 에서는 가드가 끼어들지 않는다', 'Python 3.9 이상' not in (ok.stdout + ok.stderr),
          (ok.stdout + ok.stderr)[:400])

    return finish('Python 버전 가드')


if __name__ == '__main__':
    sys.exit(main())
