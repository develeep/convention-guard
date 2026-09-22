"""Package entry: refuse an interpreter this release cannot run on.

3.0 needs Python 3.9 (NFR-04.1). Without this, an upgrade on 3.8 shows a
SyntaxError from whichever module was imported first -- true, but it tells
nobody what to do. This module is read before any of ours, so it is the last
place that can still speak; for the same reason it may only use syntax 3.8
can parse.

A hook must never break the agent, so it exits 0 either way. It does say
something, though: a silent skip is indistinguishable from a clean check, and
switching the plugin off for a whole session unnoticed is worse than noise.
"""

import os
import sys

MINIMUM = (3, 9)
HOOK_ENTRY_POINTS = ('check.py', 'collect.py')

_MESSAGE = ('convention-guard 3.0 은 Python %d.%d 이상이 필요합니다 (현재 %d.%d). '
            '1.x 를 계속 쓰거나 Python 을 올리세요 — docs/migration-3.0.md')


def _refuse():
    text = _MESSAGE % (MINIMUM[0], MINIMUM[1],
                       sys.version_info[0], sys.version_info[1])
    if os.path.basename(sys.argv[0] or '') in HOOK_ENTRY_POINTS:
        # the hook protocol's only channel to the user, and json is in the
        # standard library of every version this could possibly be running on
        import json
        sys.stdout.write(json.dumps({'systemMessage': text}, ensure_ascii=False) + '\n')
    else:
        sys.stderr.write(text + '\n')
    raise SystemExit(0)


if sys.version_info < MINIMUM:
    _refuse()
