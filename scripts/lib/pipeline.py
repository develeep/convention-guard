"""The one checking pipeline every entry point runs.

    scope -> stacks -> rules -> linters -> detection -> dismissals -> result

The Stop hook, scan.py, dismiss.py and the semantic queue differ only in how
they build the ChangeScope and what they do with the Result. Anything that
decides *whether something is reported* belongs here, so no two callers can
drift apart.
"""

from . import detect, dismiss as dismisslib, lint, rules as rulelib, stack as stacklib
from .detect import Stacks
from .paths import plugin_root as default_plugin_root


class Result:
    def __init__(self, scope, stacks, rules, notes, lint_blocking, lint_notes, lint_raw,
                 hits, semantic_hits, dismissals):
        self.scope = scope
        self.stacks = stacks
        self.rules = rules                  # every loaded, enabled rule
        self.notes = notes                  # [(level, text)] from loading
        self.lint_blocking = lint_blocking  # linter failures anchored to this change
        self.lint_notes = lint_notes        # linter findings elsewhere in touched files
        self.lint_raw = lint_raw
        self.hits = hits                    # [(rule, [Candidate])], deterministic rules
        self.semantic_hits = semantic_hits  # [(rule, [Candidate])], review-gated rules
        self.dismissals = dismissals        # number of recorded dismissals applied

    def applicable_rules(self):
        return [r for r in self.rules
                if rulelib.stack_ok(r, self.stacks.tags, self.stacks.versions)]


def detect_stacks(root, cfg, plugin_root=None):
    detected = stacklib.detect(plugin_root or default_plugin_root(), root,
                               forced=cfg.get('stacks') or None)
    return Stacks.from_detected(detected)


def load_rules(root, plugin_root=None, include_disabled=False):
    rules, notes, _ = rulelib.load_all(root, root=plugin_root or default_plugin_root(),
                                       include_disabled=include_disabled)
    return rules, notes


def run(scope, cfg, plugin_root=None, run_lint=True, cap=None, use_dismiss=True,
        rule_filter=None):
    root = scope.root
    stacks = detect_stacks(root, cfg, plugin_root)
    rules, notes = load_rules(root, plugin_root)
    if rule_filter:
        rules = [r for r in rules if rule_filter(r)]

    is_dismissed = detect._never_dismissed
    dismissals = 0
    if use_dismiss:
        keys, entries = dismisslib.load(root)
        is_dismissed = dismisslib.predicate(keys)
        dismissals = len(entries)

    lint_blocking, lint_notes, lint_raw = [], [], []
    if run_lint and cfg.get('run_linters', True) and stacks.lint and scope:
        lint_raw = lint.run(root, stacks.lint, scope.paths(),
                            timeout=int(cfg.get('lint_timeout', 90)))
        lint_blocking, lint_notes = lint.split_by_change(lint_raw, scope)

    active = [r for r in rules
              if not (cfg.get('respect_supersede', True) and rulelib.superseded(r, root))]
    cap = int(cap if cap is not None else cfg.get('max_hits_per_rule', 3))
    plain = [r for r in active if r.get('kind') != 'semantic']
    gated = [r for r in active if r.get('kind') == 'semantic']
    hits = detect.run(plain, scope, stacks, cap, is_dismissed)
    semantic_hits = detect.run(gated, scope, stacks, cap, is_dismissed)

    return Result(scope, stacks, rules, notes, lint_blocking, lint_notes, lint_raw,
                  hits, semantic_hits, dismissals)
