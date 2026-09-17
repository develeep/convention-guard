#!/usr/bin/env python3
"""PostToolUse hook adapter: record which files the agent touched.

Cost is a few milliseconds and zero context. The queue is what makes the Stop
check precise -- `git diff` alone also picks up the human's own edits.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import hooks, state  # noqa: E402


def main():
    try:
        state.remember_plugin_root()
        hooks.on_post_tool_use(json.load(sys.stdin))
    except Exception as exc:  # a recording hook must never interrupt the agent
        print('[convention-guard] %s' % exc, file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
