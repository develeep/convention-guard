#!/usr/bin/env python3
"""Every rule's own fixtures, plus the structural promises rules make.

A convention checker earns trust by not crying wolf, so every rule ships with
`tests.match` / `tests.no_match` and CI protects them. Run against the bundled
rules, or include a repo's local overlay (overrides are merged first, so a
patched rule is tested as the repo will actually run it):

    python3 tests/rules/test_rule_fixtures.py
    python3 tests/rules/test_rule_fixtures.py --repo /path/to/repo

What a fixture means depends on the anchor:

    when_line_added              코드. 패턴이 있으면 걸림
    + must_contain_in_file       파일 본문. 조건은 있고 필수 요소가 없으면 걸림
    when_file_added              새 파일 본문. 필수 요소가 없으면 걸림
    when_changed                 변경된 경로 목록. 짝이 되는 파일이 없으면 걸림
    file_regex                   코드(여러 줄). 패턴이 있으면 걸림

For a rule with semantic_review the fixtures test the gate only; the verdict
belongs to the reviewer.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from helpers import ROOT  # noqa: E402
from lib import rules as rulelib, structure
from lib.structure import conditions
from lib.structure.model import REJECT, Span  # noqa: E402
from lib.yamlio import read as read_yaml  # noqa: E402


# A fixture is a fragment, not a file: a PHP snippet has no `<?php`, so the
# structure layer would read all of it as template text and find neither
# comments nor strings. The prologue makes the fragment a file. It is part of
# the synthesised text, so detection and analysis share one coordinate system
# (DR-25, DR-26). `tests.lang_prefix: false` opts out.
PROLOGUE = {'php': '<?php\n'}


def fixture_language(rule):
    """The language a fixture fragment should be read as."""
    for pattern in rule.get('files') or ():
        language = structure.language_of(str(pattern).replace('*', 'x'))
        if language:
            return language
    return None


def synthesise(rule, sample):
    """(text, language) -- the fragment as a file."""
    language = fixture_language(rule)
    if not language or rule['tests'].get('lang_prefix', True) is False:
        return str(sample), language
    return PROLOGUE.get(language, '') + str(sample), language


def passes_conditions(rule, text, language, match):
    """Would the detector keep this match? UNKNOWN keeps it (D5)."""
    analysed = structure.analyze(text, language)
    if not analysed.ok:
        return True
    span = Span(match.start(), match.end())
    return conditions.evaluate(rule, analysed, span) != REJECT


def matcher(rule):
    kind = rule['kind']
    if conditions.has_conditions(rule) and kind in ('line', 'requires', 'file'):
        plain = _plain_matcher(rule)

        def check(sample):
            text, language = synthesise(rule, sample)
            pattern = rule['compiled_file'] if kind == 'file' else rule['compiled_when']
            match = pattern.search(text)
            if match is None or not plain(sample):
                return False
            return passes_conditions(rule, text, language, match)
        return check
    return _plain_matcher(rule)


def _plain_matcher(rule):
    kind = rule['kind']
    if kind == 'paired':
        def check(sample):
            paths = [sample] if isinstance(sample, str) else list(sample)
            if not any(rulelib.match_any(rule['when_changed'], p) for p in paths):
                return False
            return not any(rulelib.match_any(rule['require_changed'], p) for p in paths)
        return check
    if kind == 'absent':
        return lambda s: not rule['compiled_must'].search(str(s))
    if kind == 'requires':
        return lambda s: (bool(rule['compiled_when'].search(str(s)))
                          and not rule['compiled_must'].search(str(s)))
    if kind == 'file':
        return lambda s: bool(rule['compiled_file'].search(str(s)))
    return lambda s: bool(rule['compiled_when'].search(str(s)))


def layers(repo):
    """[(path, source, raw)] with local overrides merged into their targets."""
    out, by_id = [], {}
    bases = [(os.path.join(ROOT, 'rules'), 'core')]
    if repo:
        bases.append((rulelib.local_rules_dir(repo), 'local'))
    for base, source in bases:
        for path in rulelib.iter_rule_files(base):
            raw = read_yaml(path)
            if isinstance(raw, dict) and raw.get('override'):
                target = by_id.get(str(raw['override']))
                if target is None:
                    out.append((path, source, None, 'override 대상 %s 없음' % raw['override']))
                    continue
                merged = rulelib.deep_merge(target[2], {k: v for k, v in raw.items()
                                                        if k not in ('override', 'id')})
                out.append((path, source, merged, None))
                continue
            entry = (path, source, raw, None)
            out.append(entry)
            if isinstance(raw, dict):
                by_id[rulelib.schema.rule_id(raw, path, source)] = entry
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', help='로컬 오버레이까지 함께 검사할 레포 경로')
    args = parser.parse_args()

    failures, warnings, checked, rules = [], [], 0, 0
    presets, preset_notes = rulelib.load_presets(ROOT)
    failures += [text for _, text in preset_notes]

    for path, source, raw, err in layers(args.repo):
        rel = os.path.relpath(path, ROOT) if path.startswith(ROOT) else path
        if err:
            failures.append('%s: %s' % (rel, err))
            continue
        try:
            rule = rulelib.normalize(raw, path, source)
        except rulelib.RuleError as exc:
            failures.append('%s: %s' % (rel, exc))
            continue
        rules += 1

        if source == 'core':
            stem = os.path.splitext(os.path.basename(path))[0]
            if raw.get('id') and raw['id'] != stem:
                failures.append('%s: id(%s) 와 파일명이 다릅니다' % (rel, raw['id']))
            owners = [p for p in presets.values() if p.includes(rule['id'])]
            if not owners:
                failures.append('%s: 어느 프리셋에도 속하지 않아 실행되지 않습니다' % rel)
        if not rule['review'] and not rule['message']:
            warnings.append('%s: message 가 비어 있음' % rel)

        tests = rule['tests']
        should, shouldnt = tests.get('match') or [], tests.get('no_match') or []
        if not should:
            failures.append('%s: tests.match 픽스처 없음' % rel)
        if not shouldnt:
            warnings.append('%s: tests.no_match 픽스처 없음 (오탐 확인 불가)' % rel)
        hit = matcher(rule)
        for sample in should:
            checked += 1
            if not hit(sample):
                failures.append('%s: 걸려야 하는데 안 걸림 — %r' % (rel, sample))
        for sample in shouldnt:
            checked += 1
            if hit(sample):
                failures.append('%s: 걸리면 안 되는데 걸림 (오탐) — %r' % (rel, sample))

        fix = rule.get('fix')
        if fix:
            # an auto-fix must resolve every violation it is shown, and leave
            # already-correct code byte for byte alone
            for sample in should:
                after = fix['compiled'].sub(fix['with'], sample)
                checked += 1
                if after == sample or hit(after):
                    failures.append('%s: fix.auto 가 위반을 고치지 못함 — %r -> %r'
                                    % (rel, sample, after))
            for sample in shouldnt:
                checked += 1
                if fix['compiled'].sub(fix['with'], sample) != sample:
                    failures.append('%s: fix.auto 가 정상 코드를 바꿈 — %r' % (rel, sample))

    for note in warnings:
        print('WARN %s' % note)
    for note in failures:
        print('FAIL %s' % note)
    if failures:
        print('\n실패 %d건 / 픽스처 %d개 / 규칙 %d개' % (len(failures), checked, rules))
        return 1
    print('\n통과 — 픽스처 %d개, 규칙 %d개, 경고 %d건' % (checked, rules, len(warnings)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
