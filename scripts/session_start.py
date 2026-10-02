"""SessionStart hook (async): get the structure engine in place, tidy the store.

Runs in the background (`async: true` in hooks.json), so the first answer of
the session never waits for a download. Prints nothing and exits 0 whatever
happens; a failed install is recorded in the engine's status.json, which the
Stop hook reads when it has to say why the engine is missing.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        json.load(sys.stdin)
    except Exception:       # noqa: BLE001 -- the payload is not needed
        pass
    try:
        from lib import state
        state.gc_old_sessions()
    except Exception:       # noqa: BLE001
        pass
    if os.environ.get('CONVENTION_GUARD_NO_ENGINE'):
        return 0
    try:
        from lib.engine import install
        install.ensure()
    except Exception:       # noqa: BLE001 -- recorded in status.json by ensure()
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
