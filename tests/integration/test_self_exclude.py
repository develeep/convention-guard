#!/usr/bin/env python3
"""Regression test: convention-guard must never scan its own config/output
files as content.

Before a repo commits its convention-guard directory, git reports it as
untracked, so the engine's "new file" path reads the whole file -- including
YAML comments written in plain language that happen to contain a rule's
trigger words. Caught in production: a downgrade rationale explaining why
NEXT_PUBLIC_CHANNEL_PLUGIN_KEY is not a secret tripped the very
next-no-public-secret rule it was explaining.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, make_repo, run_cases, write  # noqa: E402
from lib import engine, gitdiff, rules as rulelib, stack as stacklib  # noqa: E402


def case_own_config_is_not_content(tmp):
    make_repo(tmp, {'package.json': '{"dependencies": {"next": "15.0.0"}}'})
    write(tmp, '.claude/convention-rules/config.yaml',
          "severity:\n"
          "  # NEXT_PUBLIC_CHANNEL_PLUGIN_KEY is a public key by design,\n"
          "  # not a secret -- downgrading this rule to warn.\n"
          "  core/next-no-public-secret: warn\n")

    detected = stacklib.detect(ROOT, tmp, forced=['next'])
    all_rules, _notes, _cfg = rulelib.load_all(tmp, root=ROOT)
    changed = gitdiff.added_lines(tmp, gitdiff.untracked(tmp), None)
    ctx = engine.Context(tmp, changed, gitdiff.untracked(tmp) & set(changed),
                         detected['tags'], detected['versions'])
    offenders = [loc['file'] for hit in engine.collect(all_rules, ctx, 10)
                 for loc in hit['locations'] if '.claude' in loc['file']]
    check('own config is never scanned as content', not offenders, offenders)


if __name__ == '__main__':
    sys.exit(run_cases([case_own_config_is_not_content], '자체 설정 파일 제외'))
