#!/usr/bin/env python3
"""Does a structure condition actually remove false positives?

The fixture repositories are clean examples -- measured, they contain zero
matches inside comments or strings -- so they cannot answer this. This walks a
small fixed corpus instead: for every transitioned rule, the same violation is
written three times, as code, inside a comment and inside a string. A working
condition keeps the first and drops the other two.

The comparison runs twice over the same input: once with the rule as written
and once with its structure conditions stripped. Stripping the keys turns the
gate off, so the second pass is the real 1.x path rather than an imitation
(PT-U3-01). What is counted is candidates, not time, and a candidate count
does not depend on which entry point produced it.

    python3 tests/perf/fp_reduction.py
    python3 tests/perf/fp_reduction.py --json out.json
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from lib import detect, rules as rulelib  # noqa: E402
from lib.rules import schema  # noqa: E402
from lib.structure import conditions as condlib  # noqa: E402
from lib.yamlio import read as read_yaml  # noqa: E402

CORPUS = os.path.join(HERE, 'corpus', 'fp')
# Where each corpus file pretends to live, so `applies_to.files` matches.
SCAN_PATH = {
    'laravel-n-plus-one': 'app/Http/Controllers/OrderController.php',
}
STACKS = detect.Stacks(tags=['*', 'php', 'laravel', 'js', 'ts', 'go'])


class _Scope:
    """One file, every line treated as added -- the whole corpus is 'new'."""

    def __init__(self, relpath, text):
        self._relpath = relpath
        self._text = text

    def paths(self):
        return [self._relpath]

    def text(self, relpath):
        return self._text if relpath == self._relpath else ''

    def lines(self, relpath):
        if relpath != self._relpath:
            return ()
        return tuple(enumerate(self._text.split('\n'), start=1))

    def changed_linenos(self, relpath):
        return {n for n, _ in self.lines(relpath)}

    def added_body(self, relpath):
        return self.text(relpath)

    def is_new(self, relpath):
        return False


def load_rules():
    """Every core rule, by id."""
    out = {}
    base = os.path.join(ROOT, 'rules')
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(dirnames)
        for name in sorted(filenames):
            if not name.endswith(('.yaml', '.yml')):
                continue
            path = os.path.join(dirpath, name)
            try:
                rule = schema.normalize(read_yaml(path), path, 'core')
            except Exception:                     # noqa: BLE001
                continue
            out[rule['id'].split('/')[-1]] = rule
    return out


def without_conditions(rule):
    """The same rule with its structure conditions removed.

    `has_conditions()` then answers False, which is what the detector checks,
    so this really is the path a rule without conditions takes.
    """
    stripped = copy.deepcopy(rule)
    for key in condlib.CONDITION_KEYS:
        stripped['detect'].pop(key, None)
    return stripped


def corpus_files():
    for name in sorted(os.listdir(CORPUS)):
        stem = os.path.splitext(name)[0]
        with open(os.path.join(CORPUS, name), encoding='utf-8') as handle:
            yield stem, name, handle.read()


def count(rule, relpath, text):
    scope = _Scope(relpath, text)
    if not rulelib.applies(rule, relpath, STACKS.tags, STACKS.versions):
        return None
    return len(detect.scan(rule, scope, STACKS, 100))


def measure():
    rules = load_rules()
    rows, missing = [], []
    for stem, name, text in corpus_files():
        rule = rules.get(stem)
        if rule is None:
            missing.append(stem)
            continue
        relpath = SCAN_PATH.get(stem, name)
        after = count(rule, relpath, text)
        before = count(without_conditions(rule), relpath, text)
        rows.append({
            'rule': stem, 'file': name, 'conditions': sorted(
                key for key in condlib.CONDITION_KEYS if rule['detect'].get(key)),
            'before': before, 'after': after,
            'removed': None if before is None or after is None else before - after,
        })
    return rows, missing, rules


def untouched_rules_unchanged(rules):
    """Every rule without conditions must count the same either way (US-12)."""
    drift = []
    for stem, name, text in corpus_files():
        relpath = SCAN_PATH.get(stem, name)
        for rule_id, rule in sorted(rules.items()):
            if condlib.has_conditions(rule):
                continue
            first = count(rule, relpath, text)
            second = count(without_conditions(rule), relpath, text)
            if first != second:
                drift.append('%s on %s: %s != %s' % (rule_id, name, first, second))
    return drift


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--json')
    args = parser.parse_args(argv)

    rows, missing, rules = measure()
    print('%-28s %-26s %7s %7s %8s' % ('규칙', '조건', '조건없음', '조건적용', '제거'))
    for row in rows:
        print('%-28s %-26s %7s %7s %8s'
              % (row['rule'], ','.join(row['conditions']) or '-',
                 row['before'], row['after'],
                 '' if row['removed'] is None else row['removed']))

    conditioned = [row for row in rows if row['conditions']]
    silent = [row['rule'] for row in conditioned if not row['removed']]
    total_removed = sum(row['removed'] or 0 for row in conditioned)
    print('\n조건이 붙은 규칙 %d개에서 후보 %d건 제거' % (len(conditioned), total_removed))
    if silent:
        print('⚠ 제거가 0건인 규칙: %s' % ', '.join(silent))
    if missing:
        print('⚠ 코퍼스에 대응 규칙이 없음: %s' % ', '.join(missing))

    drift = untouched_rules_unchanged(rules)
    print('미전환 규칙 불변: %s' % ('OK' if not drift else '실패 — %s' % '; '.join(drift[:3])))

    if args.json:
        os.makedirs(os.path.dirname(args.json) or '.', exist_ok=True)
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump({'rows': rows, 'silent': silent, 'missing': missing,
                       'untouched_drift': drift}, handle,
                      ensure_ascii=False, indent=2, sort_keys=True)
        print('%s 에 기록' % os.path.relpath(args.json, ROOT))
    return 1 if drift or missing else 0


if __name__ == '__main__':
    sys.exit(main())
