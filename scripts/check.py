#!/usr/bin/env python3
"""Stop hook adapter. The policy lives in lib/hooks.py.

Reads the hook payload from stdin and prints the decision JSON (or nothing).
It never exits non-zero and never lets its own bug break the agent's turn.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import hooks, semantic, state  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        state.gc_old_sessions()
        semantic.gc_batches()
        out = hooks.on_stop(payload)
    except Exception as exc:  # never break the agent on our own bug -- but say so:
        # a silent skip looks exactly like a clean check, so a broken config or
        # a bug here would switch the plugin off for the whole session unnoticed
        print(json.dumps({'systemMessage': 'convention-guard: 내부 오류로 이번 검사를 '
                                           '건너뜁니다 — %s' % exc}, ensure_ascii=False))
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
