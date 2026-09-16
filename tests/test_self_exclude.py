#!/usr/bin/env python3
"""Regression test: convention-guard must never scan its own config/output
files as content.

Before a repo commits .claude/convention-rules/, git reports it as
untracked, so the engine's "new file" path reads the whole file -- including
YAML comments written in plain language that happen to contain a rule's
trigger words. Caught in production: a downgrade rationale explaining why
NEXT_PUBLIC_CHANNEL_PLUGIN_KEY is not a secret tripped the very
next-no-public-secret rule it was explaining.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


def make_repo(tmp):
    subprocess.run(['git', 'init', '-q', tmp], check=True)
    subprocess.run(['git', '-C', tmp, 'config', 'user.email', 't@t'], check=True)
    subprocess.run(['git', '-C', tmp, 'config', 'user.name', 't'], check=True)
    with open(os.path.join(tmp, 'package.json'), 'w') as fh:
        fh.write('{"dependencies": {"next": "15.0.0"}}')
    subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', tmp, 'commit', '-q', '-m', 'init'], check=True)

    # Mirrors the field-reported case: an uncommitted config.yaml whose
    # comment explains why a rule was downgraded, using the rule's own
    # trigger words in plain language.
    cfg_dir = os.path.join(tmp, '.claude', 'convention-rules')
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, 'config.yaml'), 'w') as fh:
        fh.write(
            "severity:\n"
            "  # NEXT_PUBLIC_CHANNEL_PLUGIN_KEY is a public key by design,\n"
            "  # not a secret -- downgrading this rule to warn.\n"
            "  core/next-no-public-secret: warn\n"
        )


def main():
    tmp = tempfile.mkdtemp()
    try:
        make_repo(tmp)
        from lib import engine, rules as rulelib, stack as stacklib
        from lib import gitdiff

        detected = stacklib.detect(ROOT, tmp, forced=['next'])
        all_rules, _notes, _cfg = rulelib.load_all(tmp, root=ROOT)
        changed = gitdiff.added_lines(tmp, gitdiff.untracked(tmp), None)
        ctx = engine.Context(tmp, changed,
                             gitdiff.untracked(tmp) & set(changed),
                             detected['tags'], detected['versions'])
        hits = engine.collect(all_rules, ctx, 10)

        offenders = [os.path.relpath(loc['file'])
                     for hit in hits for loc in hit['locations']
                     if '.claude' in loc['file']]
        assert not offenders, (
            'convention-guard scanned its own config as content: %r' % offenders)
        print('통과 — 자체 설정 파일이 스캔 대상에서 제외됨')
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
