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
from lib import config, detect, rules as rulelib  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402

COMMENT = ("severity:\n"
           "  # NEXT_PUBLIC_CHANNEL_PLUGIN_KEY is a public key by design,\n"
           "  # not a secret -- downgrading this rule to warn.\n"
           "  core/next-no-public-secret: warn\n")


def offenders(tmp):
    stacks = detect.Stacks({'js', 'react', 'next'})
    rules = rulelib.load(tmp, ROOT, config.DEFAULTS, stacks.tags).rules
    scope = ChangeScope.working_tree(tmp)
    return [c.file for _, cands in detect.run(rules, scope, stacks, 10) for c in cands
            if '.claude' in c.file]


def case_own_config_is_not_content(tmp):
    make_repo(tmp, {'package.json': '{"dependencies": {"next": "15.0.0"}}'})
    write(tmp, '.claude/convention-guard/config.yaml', COMMENT)
    write(tmp, '.claude/rules/convention-js.md', '- NEXT_PUBLIC_STRIPE_SECRET 금지\n')
    found = offenders(tmp)
    check('own config and generated context are never scanned', not found, found)


def case_unmigrated_layout_is_not_content(tmp):
    make_repo(tmp, {'package.json': '{"dependencies": {"next": "15.0.0"}}'})
    write(tmp, '.claude/convention-rules/config.yaml', COMMENT)
    found = offenders(tmp)
    check('a 0.x config directory is not scanned either', not found, found)


if __name__ == '__main__':
    sys.exit(run_cases([case_own_config_is_not_content, case_unmigrated_layout_is_not_content],
                       '자체 설정 파일 제외'))
