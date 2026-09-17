#!/usr/bin/env python3
"""Stop hook adapter. The policy lives in lib/hooks.py.

Reads the hook payload from stdin and prints the decision JSON (or nothing).
It never exits non-zero and never lets its own bug break the agent's turn.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import hooks, state  # noqa: E402


def main():
    state.remember_plugin_root()
    semantic = '--semantic-queue' in sys.argv
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = None
    try:
        if semantic:
            print(hooks.semantic_queue(payload))
            return 0
        state.gc_old_sessions()
        out = hooks.on_stop(payload)
    except Exception as exc:  # never break the agent on our own bug
        if semantic:
            print('EMPTY')
        print('[convention-guard] 내부 오류: %s' % exc, file=sys.stderr)
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
