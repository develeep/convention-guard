#!/usr/bin/env python3
"""Stop hook adapter. The decision lives in lib/decide.py, its I/O in lib/stop.py.

Reads the hook payload from stdin and prints the decision JSON (or nothing).
It never exits non-zero and never lets its own bug break the agent's turn.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import log, state, stop  # noqa: E402


def main():
    started = time.time()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        state.gc_old_sessions()
        out = stop.on_stop(payload, started)
    except Exception as exc:  # never break the agent on our own bug -- but say so:
        # a silent skip looks exactly like a clean check, so a broken config or
        # a bug here would switch the plugin off for the whole session unnoticed
        first = str(exc).strip().split('\n')[0] or type(exc).__name__
        _log_error(payload, started, first)
        print(json.dumps({'systemMessage': 'convention-guard ✖ 건너뜀 — 내부 오류: %s' % first},
                         ensure_ascii=False))
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


def _log_error(payload, started, first):
    """A Stop that failed is still a Stop: every one leaves a record."""
    try:
        payload = payload if isinstance(payload, dict) else {}
        log.event({'event': 'stop', 'outcome': 'error', 'hook_ms': stop.hook_ms(started),
                   'prompt': payload.get('prompt_id') or payload.get('turn_number'),
                   'error': first, 'session': payload.get('session_id')})
    except Exception:  # noqa: BLE001 -- logging must not break the hook either
        pass


if __name__ == '__main__':
    sys.exit(main())
