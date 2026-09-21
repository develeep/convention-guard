"""The one checking pipeline every entry point runs.

    scope -> stacks -> rules (presets, config, applicability) -> linters
          -> detection -> dismissals -> deterministic | semantic

The Stop hook, scan.py, dismiss.py and review.py differ only in how they build
the ChangeScope and what they do with the Result. Anything that decides
*whether something is reported* belongs here, so no two callers can drift.
"""

from . import detect, dismiss as dismisslib, lint, rules as rulelib, stack as stacklib
from .detect import Stacks
from .paths import plugin_root as default_plugin_root


class Result:
    def __init__(self, scope, stacks, ruleset, applicable, lint_blocking, lint_notes,
                 lint_raw, hits, semantic_hits, dismissals):
        self.scope = scope
        self.stacks = stacks
        self.ruleset = ruleset              # RuleSet: rules in play, inactive, notes, presets
        self.rules = ruleset.rules
        self.notes = ruleset.notes
        self.applicable = applicable        # rules that could fire on this scope
        self.lint_blocking = lint_blocking  # linter failures anchored to this change
        self.lint_notes = lint_notes        # linter findings elsewhere in touched files
        self.lint_raw = lint_raw
        self.hits = hits                    # [(rule, [Candidate])] judged by the agent
        self.semantic_hits = semantic_hits  # [(rule, [Candidate])] judged by a reviewer
        self.dismissals = dismissals        # recorded dismissals that were applied

    @property
    def errors(self):
        return [text for level, text in self.notes if level == 'error']


def detect_stacks(root, cfg, plugin_root=None):
    detected = stacklib.detect(plugin_root or default_plugin_root(), root,
                               forced=cfg.get('stacks') or None)
    return Stacks.from_detected(detected)


def load_rules(root, cfg, stacks, plugin_root=None):
    ruleset = rulelib.load(root, plugin_root or default_plugin_root(), cfg, stacks.tags)
    ruleset.notes += stacks.notes
    return ruleset


def run(scope, cfg, plugin_root=None, run_lint=True, cap=None, use_dismiss=True,
        rule_filter=None, lint_budget=None):
    root = scope.root
    stacks = detect_stacks(root, cfg, plugin_root)
    ruleset = load_rules(root, cfg, stacks, plugin_root)
    rules = ruleset.rules
    if rule_filter:
        rules = [r for r in rules if rule_filter(r)]
        ruleset.rules = rules

    is_dismissed = detect._never_dismissed
    dismissals = 0
    if use_dismiss:
        recorded = dismisslib.load(root)
        if recorded.error:
            # never check as if nothing had been declined: every dismissed
            # finding would come back and block again
            ruleset.notes.append(('error', recorded.error))
        is_dismissed = recorded.is_dismissed
        dismissals = len(recorded)

    lint_blocking, lint_notes, lint_raw = [], [], []
    if run_lint and cfg['linters']['enabled'] and stacks.lint and scope:
        lint_raw = lint.run(root, stacks.lint, scope.paths(),
                            timeout=int(cfg['linters']['timeout']),
                            budget=lint_budget, notes=ruleset.notes)
        lint_blocking, lint_notes = lint.split_by_change(lint_raw, scope)

    if (not rule_filter and cfg['semantic_review']['enabled']
            and not any(r['review'] for r in rules)):
        # turning the option on and getting nothing back reads as "the feature
        # is broken"; it usually means no preset in play carries such a rule
        ruleset.notes.append(('warn', 'semantic_review 가 켜져 있지만 의미 판정 규칙이 하나도 '
                                      '켜져 있지 않습니다 — presets 에 architecture / '
                                      'performance 를 추가하세요'))

    applicable = rulelib.applicable(rules, stacks, scope.paths(), root,
                                    respect_supersede=cfg.get('respect_supersede', True))
    cap = int(cap if cap is not None else cfg.limit('max_locations_per_rule'))
    hits = detect.run([r for r in applicable if not r['review']], scope, stacks, cap,
                      is_dismissed)
    semantic_hits = detect.run([r for r in applicable if r['review']], scope, stacks, cap,
                               is_dismissed)

    return Result(scope, stacks, ruleset, applicable, lint_blocking, lint_notes, lint_raw,
                  hits, semantic_hits, dismissals)
