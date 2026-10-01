#!/usr/bin/env python3
"""Pre/PostToolUse hook adapter: record what the agent touched and what it did not write.

Pre remembers the lines a file already had before the agent changed it; Post
records the file. Zero context. Together they are what makes the Stop check
precise -- `git diff` alone also picks up the human's own edits.
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
