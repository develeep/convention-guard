"""Verification cycle: Detect -> Block -> Fix -> Re-scan -> Verify, as one unit.

A cycle opens when the Stop hook blocks. Every later Stop that continues the
same request (stop_hook_active) re-scans the same change scope and compares it
with what the cycle opened with:

    FIXED       a flagged candidate is gone
    DISMISSED   a flagged candidate was recorded as a false positive
    STILL       a flagged candidate is still there
    NEW         a blocking candidate that did not exist when the cycle opened
                -- typically introduced by the fix itself

STILL or NEW (at blocking severity) earns one more block, up to
`limits.max_verify_attempts`; then the cycle closes and whatever is left is
reported without blocking. The cap on consecutive blocks bounds all of it, so
Detect -> Fix -> Verify cannot become a loop.

Identity is the candidate key (rule:file:code hash), so a line moving because
code was added above it is still the same candidate, and a rewritten line is
a different one.
"""

import time

FIXED, DISMISSED, STILL, NEW = 'fixed', 'dismissed', 'still', 'new'
BLOCKING = ('error',)


def new_cycle(prompt_id, opened, seen):
    return {
        'id': 'c%d' % int(time.time() * 1000),
        'prompt_id': str(prompt_id) if prompt_id is not None else None,
        'attempt': 0,
        'opened': opened,          # {key: meta} flagged to the agent, still being tracked
        'seen': sorted(seen),      # every candidate key present when flagged
        'review_batch': None,
    }


def entry(rule, cand):
    return {'rule_id': rule['id'], 'title': rule['title'], 'severity': rule['severity'],
            'file': cand.file, 'line': cand.line, 'snippet': cand.snippet}


def lint_key(fail):
    return 'lint:%s' % fail.get('key', fail['cmd'])


def lint_entry(fail):
    return {'rule_id': 'lint', 'title': fail['cmd'], 'severity': 'error',
            'file': '', 'line': 0, 'snippet': fail['output'].split('\n')[0][:120]}


class Outcome:
    def __init__(self):
        self.fixed, self.dismissed, self.still, self.new = {}, {}, {}, {}

    def counts(self):
        return {FIXED: len(self.fixed), DISMISSED: len(self.dismissed),
                STILL: len(self.still), NEW: len(self.new)}

    def blocking(self):
        """STILL and NEW entries that are worth another block."""
        return {k: v for k, v in list(self.still.items()) + list(self.new.items())
                if v['severity'] in BLOCKING}

    def remaining(self):
        return dict(self.still, **self.new)


def classify(cycle, current, is_dismissed):
    """current: {key: entry} for every candidate (and blocking lint failure)
    the re-scan found. is_dismissed(key) -> bool."""
    out = Outcome()
    for key, meta in cycle['opened'].items():
        if key in current:
            out.still[key] = current[key]
        elif not key.startswith('lint:') and is_dismissed(key):
            out.dismissed[key] = meta
        else:
            out.fixed[key] = meta
    seen = set(cycle.get('seen') or ())
    for key, meta in current.items():
        if key not in seen and key not in cycle['opened']:
            out.new[key] = meta
    return out
