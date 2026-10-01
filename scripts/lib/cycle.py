"""Verification cycle: Detect -> Block -> Fix -> Re-scan -> Verify, as one unit.

A cycle opens when the Stop hook blocks. Every later Stop that continues the
same request (stop_hook_active) re-scans the same change scope and compares it
with what the cycle opened with:

    FIXED       a flagged candidate is gone (a reformat or a move pairs up as STILL)
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
        """STILL and NEW entries that are worth another block -- not one whose
        linter could not say (blocking on it again could only time out again)."""
        return {k: v for k, v in list(self.still.items()) + list(self.new.items())
                if v['severity'] in BLOCKING and not v.get('unconfirmed')}

    def unconfirmed(self):
        return [k for k, v in self.still.items() if v.get('unconfirmed')]

    def remaining(self):
        return dict(self.still, **self.new)


def classify(cycle, current, is_dismissed, unconfirmed=()):
    """current: {key: entry} for every candidate (and blocking lint failure)
    the re-scan found. is_dismissed(key) -> bool. unconfirmed: lint keys whose
    linter did not finish -- gone from `current` is not fixed for them (R17)."""
    out = Outcome()
    for key, meta in cycle['opened'].items():
        if key in current:
            out.still[key] = current[key]
        elif key in unconfirmed:
            out.still[key] = dict(meta, unconfirmed=True)
        elif not key.startswith('lint:') and is_dismissed(key):
            out.dismissed[key] = meta
        else:
            out.fixed[key] = meta
    seen = set(cycle.get('seen') or ()) | set(cycle['opened'])
    for key, meta in current.items():
        if key not in seen:
            out.new[key] = meta
    _pair_moves(out)
    return out


def _squeezed(meta):
    return ''.join(str(meta.get('snippet') or '').split())


def _pair_moves(out):
    """A violation reformatted in place (same rule and file, same code once
    every space is gone) or moved whole (same code, another file) is the same
    one: a fixed and a new become one still. A different violation the fix
    wrote (`dd(1)` -> `var_dump(1)`) stays fixed plus new. Blocking is
    unchanged -- still blocks like new -- only the tuning numbers are (R23f)."""
    for fixed_key in sorted(out.fixed):
        if fixed_key.startswith('lint:'):
            continue
        meta = out.fixed[fixed_key]
        digest = fixed_key.rpartition(':')[2]
        reformat = [k for k in sorted(out.new)
                    if out.new[k]['rule_id'] == meta['rule_id']
                    and out.new[k]['file'] == meta['file']
                    and _squeezed(out.new[k]) == _squeezed(meta)]
        moved = [k for k in sorted(out.new)
                 if out.new[k]['rule_id'] == meta['rule_id'] and k.rpartition(':')[2] == digest]
        partner = (reformat or moved or [None])[0]
        if partner is not None:
            out.still[partner] = dict(out.new.pop(partner), was=fixed_key)
            del out.fixed[fixed_key]
