#!/usr/bin/env python3
"""How long the structure layer takes.

    python3 tests/perf/run.py                  # both corpora, prints a table
    python3 tests/perf/run.py --corpus real
    python3 tests/perf/run.py --json out.json

Not collected by tests/run_all.py on purpose: it is a measurement, not an
assertion, and the Stop hook must not pay for it every turn. A smoke test in
tests/structure/ keeps it from rotting.

Numbers are medians -- a mean would follow whatever the garbage collector did
during the run. They are also machine-specific, which is why the JSON records
the interpreter, the platform and the baseline commit: U2 re-measures the
integrated path with the same harness and compares against a baseline taken
on the same machine (NR-07).
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from helpers import corpus  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure.native import langs, mask, scopes  # noqa: E402

# blade has no scope tree, so it is not part of the like-for-like table
SYNTHETIC_LANGUAGES = ('php', 'js', 'go', 'java', 'rust', 'c', 'py')
SIZES = (100, 1000, 10000)
DENSITIES = ('sparse', 'dense')
REPEATS = 5
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'aidlc-docs', '.hypothesis'}

# NR-01: the per-file budget this unit is judged against (ms, median)
TARGETS = {100: 0.5, 1000: 5.0, 10000: 60.0}
CACHE_TARGET = 0.05


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def timed(call, repeats=REPEATS):
    """Median milliseconds over `repeats` runs."""
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        samples.append((time.perf_counter() - start) * 1000)
    return median(samples)


def measure(text, language):
    """Every metric for one sample."""
    definition = langs.definition(language)
    structure.reset_cache()
    row = {
        'M-1': timed(lambda: (structure.reset_cache(),
                              structure.analyze(text, language))),
        'M-2': timed(lambda: mask.scan(text, definition)),
    }
    masked = mask.scan(text, definition)
    row['M-3'] = timed(lambda: scopes.build(text, definition, masked))
    structure.reset_cache()
    structure.analyze(text, language)
    row['M-5'] = timed(lambda: structure.analyze(text, language))
    row['ok'] = structure.analyze(text, language).ok
    row['bytes'] = len(text)
    return row


def synthetic_rows(sizes=SIZES):
    for language in SYNTHETIC_LANGUAGES:
        for size in sizes:
            for density in DENSITIES:
                # broken=0 keeps the size honest: a corpus that fails to parse
                # halfway measures less work than a real file of that size
                text = corpus.make_file(language, seed=size, lines=size,
                                        density=density, broken=0.0)
                row = measure(text, language)
                row.update(corpus='synthetic', language=language, size=size,
                           density=density)
                yield row


def real_rows():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            relpath = os.path.relpath(os.path.join(dirpath, name), ROOT)
            language = structure.language_of(relpath)
            if language is None:
                continue
            try:
                with open(os.path.join(ROOT, relpath), encoding='utf-8') as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            row = measure(text, language)
            row.update(corpus='real', language=language, size=text.count('\n') + 1,
                       density='real', path=relpath)
            yield row


def budget(rows):
    """NR-01 per-file targets against the synthetic corpus."""
    out = []
    for size in SIZES:
        sized = [row['M-1'] for row in rows
                 if row['corpus'] == 'synthetic' and row['size'] == size]
        if sized:
            worst = max(sized)
            out.append({'size': size, 'target_ms': TARGETS[size],
                        'median_ms': round(median(sized), 3),
                        'worst_ms': round(worst, 3),
                        'meets_target': worst <= TARGETS[size]})
    cached = [row['M-5'] for row in rows if row['corpus'] == 'synthetic']
    if cached:
        out.append({'size': 'cache-hit', 'target_ms': CACHE_TARGET,
                    'median_ms': round(median(cached), 4),
                    'worst_ms': round(max(cached), 4),
                    'meets_target': max(cached) <= CACHE_TARGET})
    return out


def environment():
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ''
    return {'python': platform.python_version(), 'platform': platform.platform(),
            'cpu': platform.processor() or platform.machine(),
            'baseline_commit': commit}


def print_table(rows, budgets):
    print('%-10s %-8s %7s %-7s %9s %9s %9s %9s'
          % ('corpus', 'lang', 'lines', 'density', 'M-1', 'M-2 mask', 'M-3 scope', 'M-5'))
    for row in rows:
        print('%-10s %-8s %7s %-7s %9.3f %9.3f %9.3f %9.4f'
              % (row['corpus'], row['language'], row['size'], row['density'],
                 row['M-1'], row['M-2'], row['M-3'], row['M-5']))
    print('\nNR-01 per-file budget')
    for item in budgets:
        print('  %-10s target %6s ms   median %8.3f   worst %8.3f   %s'
              % (item['size'], item['target_ms'], item['median_ms'], item['worst_ms'],
                 'OK' if item['meets_target'] else 'MISS'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', choices=('synthetic', 'real', 'both'), default='both')
    parser.add_argument('--json', default=os.path.join(HERE, 'results',
                                                       'u1-structure-only.json'))
    parser.add_argument('--stage', default='structure_only')
    parser.add_argument('--max-lines', type=int, default=max(SIZES),
                        help='가장 큰 합성 표본의 줄 수 (스모크 테스트는 100)')
    args = parser.parse_args()

    rows = []
    if args.corpus in ('synthetic', 'both'):
        rows.extend(synthetic_rows([s for s in SIZES if s <= args.max_lines]))
    if args.corpus in ('real', 'both'):
        rows.extend(real_rows())

    budgets = budget(rows)
    print_table(rows, budgets)

    payload = {'stage': args.stage, 'env': environment(), 'repeats': REPEATS,
               'budget': budgets, 'rows': rows}
    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        print('\n%s 에 기록' % os.path.relpath(args.json, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
