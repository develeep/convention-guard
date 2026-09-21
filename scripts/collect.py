#!/usr/bin/env python3
"""PostToolUse hook adapter: record which files the agent touched.

Cost is a few milliseconds and zero context. The queue is what makes the Stop
check precise -- `git diff` alone also picks up the human's own edits.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import hooks  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0            # not a hook payload; nothing to record
    try:
        if isinstance(payload, dict) and payload.get('hook_event_name') == 'PreToolUse':
            hooks.on_pre_tool_use(payload)
        else:
            hooks.on_post_tool_use(payload)
    except Exception as exc:  # a recording hook must never interrupt the agent
        print('[convention-guard] %s' % exc, file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
