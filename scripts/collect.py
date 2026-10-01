#!/usr/bin/env python3
"""Pre/PostToolUse(+Failure) hook adapter: the edit ledger (lib/ledger.py).

Pre remembers how the files looked before the call, Post attributes what
changed to the agent. Prints nothing, injects nothing, exits 0 -- and when it
fails it says so where the Stop hook will read it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ledger  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0            # not a hook payload; nothing to record
    try:
        ledger.collect(payload)
    except Exception as exc:  # a recording hook must never interrupt the agent
        ledger.record_failure(payload, 'internal_error:%s' % type(exc).__name__)
        print('[convention-guard] %s' % exc, file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
