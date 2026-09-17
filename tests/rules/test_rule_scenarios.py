#!/usr/bin/env python3
"""Rules run against real git changes, not just strings.

Inline fixtures (tests.match / no_match) prove a pattern matches. They cannot
prove the anchor: that a rule fires on what *this change* added and stays
quiet on the same code sitting untouched in history. Each scenario file here
builds a throwaway repo per case and runs the rule through the real scope and
detector:

    rule: core/php-strict-types-required
    stacks: [php]
    cases:
      - name: 새 파일에 선언 없음
        before: {}                       # committed
        after:                           # working tree on top (null deletes)
          app/Foo.php: "<?php\\n\\nnamespace App;\\n"
        expect: ["app/Foo.php:1"]        # file:line of every candidate

Rules whose anchor is not a plain added line must have scenarios, including one
where the violation exists only in untouched legacy code.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from helpers import ROOT, check, finish, make_repo, tempdir, write  # noqa: E402
from lib import detect, rules as rulelib  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402
from lib.yamlio import read as read_yaml  # noqa: E402

SCENARIOS = os.path.join(HERE, 'scenarios')
ANCHORED = ('absent', 'requires', 'paired', 'file')


def core_rules():
    out = {}
    for path in rulelib.iter_rule_files(os.path.join(ROOT, 'rules')):
        rule = rulelib.normalize(read_yaml(path), path, 'core')
        rule['repo_exclude'] = list(rulelib.SELF_PATHS)
        out[rule['id']] = rule
    return out


def run_case(rule, stacks, case):
    with tempdir() as tmp:
        repo = os.path.join(tmp, 'repo')
        before = dict(case.get('before') or {})
        before.setdefault('.gitkeep', '')
        make_repo(repo, before)
        for rel, body in (case.get('after') or {}).items():
            if body is None:
                os.remove(os.path.join(repo, rel))
            else:
                write(repo, rel, body)
        scope = ChangeScope.working_tree(repo)
        found = detect.scan(rule, scope, detect.Stacks(stacks), cap=50)
        return sorted('%s:%d' % (c.file, c.line) for c in found)


def main():
    rules = core_rules()
    covered = {}
    for dirpath, _dirs, files in os.walk(SCENARIOS):
        for name in sorted(files):
            if not name.endswith('.yaml'):
                continue
            path = os.path.join(dirpath, name)
            spec = read_yaml(path)
            rid = spec.get('rule')
            print('%s:' % os.path.relpath(path, HERE))
            if rid not in rules:
                check('%s exists' % rid, False, path)
                continue
            kinds = set()
            for case in spec.get('cases') or []:
                got = run_case(rules[rid], spec.get('stacks') or ['*'], case)
                want = sorted(case.get('expect') or [])
                check('%s — %s' % (rid, case.get('name')), got == want,
                      'want=%r got=%r' % (want, got))
                kinds.add('legacy' if case.get('before') and not want else 'other')
            covered[rid] = kinds

    print('coverage:')
    for rid, rule in sorted(rules.items()):
        if rule['kind'] not in ANCHORED:
            continue
        check('%s has scenarios' % rid, rid in covered)
        check('%s has an untouched-legacy scenario' % rid, 'legacy' in covered.get(rid, ()))
    return finish('규칙 시나리오')


if __name__ == '__main__':
    sys.exit(main())
