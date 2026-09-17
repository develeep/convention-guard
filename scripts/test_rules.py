#!/usr/bin/env python3
"""Test the rules themselves. Run this in CI.

A convention checker earns trust by not crying wolf, so every rule ships with
fixtures and the fixtures are what CI protects. Run against the bundled rules,
or point it at a repo to include that repo's local overlay:

    python3 scripts/test_rules.py
    python3 scripts/test_rules.py --repo /path/to/repo
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import rules as rulelib  # noqa: E402
from lib.paths import plugin_root, read_yaml  # noqa: E402

GREEN, RED, YELLOW, RESET = '\033[32m', '\033[31m', '\033[33m', '\033[0m'
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = RESET = ''


def collect(repo):
    root = plugin_root()
    found = []
    bases = [(os.path.join(root, 'rules'), 'core')]
    if repo:
        bases.append((os.path.join(repo, rulelib.LOCAL_DIRNAME), 'local'))
    for base, source in bases:
        for path in rulelib._iter_rule_files(base):
            try:
                raw = read_yaml(path) or {}
            except Exception as exc:
                found.append((path, source, None, 'parse: %s' % exc))
                continue
            found.append((path, source, raw, None))
    return found


def _matcher(kind, rule):
    """A fixture 'matches' when the rule would report it. Semantics per kind:

      line / file   픽스처 = 코드. 패턴이 있으면 위반
      absent        픽스처 = 새 파일 본문. 패턴이 없으면 위반
      requires      픽스처 = 파일 본문. 조건은 있는데 필수 요소가 없으면 위반
      paired        픽스처 = 변경된 경로 목록. 짝이 없으면 위반
    """
    if kind == 'paired':
        def check(sample):
            paths = [sample] if isinstance(sample, str) else list(sample)
            if not any(rulelib._match_any(rule['when_changed'], p) for p in paths):
                return False
            return not any(rulelib._match_any(rule['require_changed'], p)
                           for p in paths)
        return check
    if kind == 'absent':
        return lambda s: not rule['compiled_absent'].search(str(s))
    if kind == 'requires':
        return lambda s: (bool(rule['compiled_when'].search(str(s)))
                          and not rule['compiled_must'].search(str(s)))
    if kind == 'file':
        return lambda s: bool(rule['compiled_file'].search(str(s)))
    if kind == 'semantic':
        # fixtures test the gate only -- the verdict belongs to the subagent
        return lambda s: bool(rule['compiled_review'].search(str(s)))
    return lambda s: bool(rule['compiled'].search(str(s)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', help='로컬 오버레이까지 함께 검사할 레포 경로')
    parser.add_argument('--require-tests', action='store_true', default=True)
    args = parser.parse_args()

    failures, warnings, checked = [], [], 0
    seen_ids = {}

    for path, source, raw, err in collect(args.repo):
        rel = os.path.relpath(path)
        if err:
            failures.append('%s: %s' % (rel, err))
            continue

        target = raw.get('override')
        rid = raw.get('id') or target
        if not rid:
            failures.append('%s: id 도 override 도 없음' % rel)
            continue
        key = str(target) if target else str(rid)
        if not target:
            if key in seen_ids and seen_ids[key] != source:
                warnings.append('%s: id %s 가 %s 레이어와 충돌' % (rel, key, seen_ids[key]))
            seen_ids[key] = source

        stub = rulelib._normalize(raw, path, source)
        try:
            kind = rulelib._compile(stub)
        except re.error as exc:
            failures.append('%s: 정규식 오류 — %s' % (rel, exc))
            continue
        except ValueError as exc:
            if not target:
                warnings.append('%s: %s' % (rel, exc))
            continue

        if kind == 'semantic':
            if not raw.get('review_prompt'):
                failures.append('%s: semantic 규칙에 review_prompt 없음' % rel)
        elif not raw.get('context_injection'):
            warnings.append('%s: context_injection 비어 있음' % rel)

        tests = raw.get('tests') or {}
        should = tests.get('should_match') or []
        shouldnt = tests.get('should_not_match') or []
        if args.require_tests and not should:
            failures.append('%s: should_match 픽스처 없음' % rel)
        if args.require_tests and not shouldnt:
            warnings.append('%s: should_not_match 픽스처 없음 (오탐 확인 불가)' % rel)

        hit = _matcher(kind, stub)
        for sample in should:
            checked += 1
            if not hit(sample):
                failures.append('%s: 걸려야 하는데 안 걸림 — %r' % (rel, sample))
        for sample in shouldnt:
            checked += 1
            if hit(sample):
                failures.append('%s: 걸리면 안 되는데 걸림 (오탐) — %r' % (rel, sample))

    for note in warnings:
        print('%sWARN%s %s' % (YELLOW, RESET, note))
    for note in failures:
        print('%sFAIL%s %s' % (RED, RESET, note))

    total = len(seen_ids)
    if failures:
        print('\n%s실패 %d건%s / 픽스처 %d개 / 규칙 %d개'
              % (RED, len(failures), RESET, checked, total))
        return 1
    print('\n%s통과%s — 픽스처 %d개, 규칙 %d개, 경고 %d건'
          % (GREEN, RESET, checked, total, len(warnings)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
