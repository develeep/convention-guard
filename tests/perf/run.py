#!/usr/bin/env python3
"""How long the structure layer takes, and what a structure condition costs.

Two stages. `structure_only` (U1) measures analysis of one file at a time.
`end_to_end` (U2) runs the Stop hook itself against a fixed 60-file change,
with 0, 5, 10 and 20 rules carrying a structure condition, and reads the cost
of a condition off the slope -- which is what decides how many rules U3 may
convert (gate B, NR-U2-05).

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
sys.path.insert(0, HERE)

from helpers import corpus  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure.native import langs, mask, scopes  # noqa: E402

# blade has no scope tree, so it is not part of the like-for-like table
SYNTHETIC_LANGUAGES = ('php', 'js', 'go', 'java', 'rust', 'c', 'py')
SIZES = (100, 1000, 10000)
DENSITIES = ('sparse', 'dense')
REPEATS = 5
# A cache hit is one sha1 and lands around 70 us, where scheduler noise is
# larger than the thing being measured; five samples do not settle.
CACHE_REPEATS = 25
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'aidlc-docs', '.hypothesis',
             '.venv', 'venv', 'env', 'site-packages'}

# NR-01: the per-file budget this unit is judged against (ms, median)
TARGETS = {100: 0.5, 1000: 5.0, 10000: 60.0}
# NR-01.d: a cache hit costs one sha1 of the text, so the budget scales with
# size instead of being a constant -- 0.05 ms up to 100KB, 0.45 us per KB above
CACHE_TARGET = 0.05
# NR-U2-01: the hook may end up 50% slower than the same change on `master`
HOOK_BUDGET_RATIO = 1.50
GATE_B_MARGIN = 0.70            # NR-U2-05, applied to the count, not the budget
CONDITION_COUNTS = (0, 5, 10, 20)
HOOK_REPEATS = 15
CACHE_FREE_KB = 100
CACHE_US_PER_KB = 0.6


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
    row['M-5'] = timed(lambda: structure.analyze(text, language), CACHE_REPEATS)
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
    cached = [(row['bytes'] / 1024, row['M-5']) for row in rows]
    if cached:
        over = [(kb, ms) for kb, ms in cached if ms > cache_budget(kb)]
        out.append({'size': 'cache-hit', 'target_ms': CACHE_TARGET,
                    'median_ms': round(median([ms for _kb, ms in cached]), 4),
                    'worst_ms': round(max(ms for _kb, ms in cached), 4),
                    'worst_over_budget': round(max((ms - cache_budget(kb))
                                                   for kb, ms in over), 4) if over else 0.0,
                    'meets_target': not over})
    return out


def cache_budget(kilobytes):
    """NR-01.d: flat up to 100KB, linear beyond -- the fingerprint is linear."""
    return CACHE_TARGET + max(0.0, kilobytes - CACHE_FREE_KB) * CACHE_US_PER_KB / 1000


def _hook_samples(check_py, payload, env, repeats=HOOK_REPEATS):
    """Wall time of each Stop-hook run, in ms.

    The spread is kept, not just the median: at this scale the difference a
    structure condition makes can be smaller than the scheduler's noise, and
    a verdict drawn from a median that hides that would be made up.
    """
    samples = []
    for turn in range(repeats):
        start = time.perf_counter()
        subprocess.run([sys.executable, check_py], input=payload(turn + 1),
                       capture_output=True, text=True, env=env)
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def end_to_end_rows(counts=CONDITION_COUNTS):
    """One row per condition count, plus the `master` baseline."""
    import rig                                   # tests/perf/rig.py

    work = rig.scratch()
    rows = []
    try:
        repo = os.path.join(work, 'repo')
        touched = rig.change_set(repo)

        for count in counts:
            bundle = os.path.join(work, 'bundle-%d' % count)
            os.makedirs(bundle)
            conditioned = rig.rules_with_conditions(count, bundle)
            plugin = rig.plugin_root_with(bundle)
            data = os.path.join(work, 'data-%d' % count)
            os.makedirs(data)
            env, check_py, session = rig.run_hook(repo, touched, data, plugin)
            samples = _hook_samples(check_py,
                                    lambda n: rig.stop_payload(session, repo, n), env)
            rows.append({
                'corpus': 'hook', 'language': 'mixed', 'size': len(touched),
                'density': 'real', 'conditioned_rules': conditioned,
                'M-1': median(samples), 'min_ms': min(samples), 'max_ms': max(samples),
            })

        baseline = os.path.join(work, 'baseline')
        rig.baseline_worktree('master', baseline)
        try:
            data = os.path.join(work, 'data-baseline')
            os.makedirs(data)
            env, check_py, session = rig.run_hook(repo, touched, data, baseline)
            samples = _hook_samples(check_py,
                                    lambda n: rig.stop_payload(session, repo, n), env)
            rows.append({
                'corpus': 'hook', 'language': 'mixed', 'size': len(touched),
                'density': 'real', 'conditioned_rules': 'baseline',
                'M-1': median(samples), 'min_ms': min(samples), 'max_ms': max(samples),
            })
        finally:
            rig.remove_worktree(baseline)
    finally:
        rig.clean(work)
    return rows


def gate_b(rows):
    """How many rules U3 may convert (NR-U2-05)."""
    by_count = {row['conditioned_rules']: row['M-1'] for row in rows}
    baseline = by_count.get('baseline')
    zero = by_count.get(0)
    if baseline is None or zero is None:
        return {'error': 'baseline 또는 N=0 측정이 없습니다'}
    budget = baseline * HOOK_BUDGET_RATIO
    counts = sorted(n for n in by_count if isinstance(n, int) and n > 0)
    top = counts[-1] if counts else 0
    marginal = (by_count[top] - zero) / top if top else 0.0
    room = budget - zero
    # the widest spread any configuration showed is the smallest difference
    # this rig can see; and a cost that is real grows with the count, so a
    # sequence that wanders up and down is noise however large it looks
    noise = max((row['max_ms'] - row['min_ms'] for row in rows), default=0.0)
    measured_in_order = [by_count[n] for n in counts]
    monotonic = all(later >= earlier - noise
                    for earlier, later in zip(measured_in_order, measured_in_order[1:]))
    rising = all(later >= earlier
                 for earlier, later in zip(measured_in_order, measured_in_order[1:]))
    resolvable = marginal * top > noise and rising
    allowed = (int((room / marginal) * GATE_B_MARGIN)
               if marginal > 0 and resolvable else None)
    return {
        'baseline_ms': round(baseline, 2),
        'budget_ms': round(budget, 2),
        'T0_ms': round(zero, 2),
        'gate_open': zero <= budget,
        'marginal_ms_per_rule': round(marginal, 4),
        'headroom_ms': round(room, 2),
        'allowed_rules': allowed,
        'noise_ms': round(noise, 2),
        'monotonic': rising,
        'within_noise_band': monotonic,
        'below_noise': not resolvable,
        'margin': GATE_B_MARGIN,
        'measured': {str(k): round(v, 2) for k, v in sorted(
            by_count.items(), key=lambda kv: str(kv[0]))},
    }


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
    parser.add_argument('--json', default=None)
    parser.add_argument('--stage', default='structure_only',
                        choices=('structure_only', 'end_to_end'))
    parser.add_argument('--max-lines', type=int, default=max(SIZES),
                        help='가장 큰 합성 표본의 줄 수 (스모크 테스트는 100)')
    args = parser.parse_args()
    if args.json is None:
        args.json = os.path.join(HERE, 'results', 'u1-structure-only.json'
                                 if args.stage == 'structure_only'
                                 else 'u2-end-to-end.json')

    if args.stage == 'end_to_end':
        rows = end_to_end_rows()
        verdict = gate_b(rows)
        print('%-10s %10s %10s %10s' % ('조건규칙', '중앙값(ms)', '최소', '최대'))
        for row in rows:
            print('%-10s %10.2f %10.2f %10.2f'
                  % (row['conditioned_rules'], row['M-1'], row['min_ms'], row['max_ms']))
        print('\n게이트 B (NR-U2-05)')
        if 'error' in verdict:
            print('  %s' % verdict['error'])
        else:
            print('  기준선(master) %.2f ms   예산 %.2f ms (+50%%)'
                  % (verdict['baseline_ms'], verdict['budget_ms']))
            print('  T(0) %.2f ms  -> %s'
                  % (verdict['T0_ms'], '예산 안' if verdict['gate_open'] else '예산 초과'))
            print('  규칙 1개당 %.3f ms,  여유 %.2f ms'
                  % (verdict['marginal_ms_per_rule'], verdict['headroom_ms']))
            if verdict.get('below_noise'):
                print('  조건 규칙 수에 따른 증가를 잡음(%.2f ms) 위에서 분리하지 못했습니다%s'
                      % (verdict['noise_ms'],
                         '' if verdict['monotonic'] else ' (측정값이 단조 증가하지 않음)'))
                print('  허용 전환 개수: 제한 없음 (조건을 붙일 수 있는 core 규칙 전부)')
            else:
                print('  허용 전환 개수 (여유 %.0f%% 적용): %s'
                      % (verdict['margin'] * 100, verdict['allowed_rules']))
        payload = {'stage': args.stage, 'env': environment(), 'repeats': HOOK_REPEATS,
                   'gate_b': verdict, 'rows': rows}
        if args.json:
            os.makedirs(os.path.dirname(args.json), exist_ok=True)
            with open(args.json, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            print('\n%s 에 기록' % os.path.relpath(args.json, ROOT))
        return 0

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
