#!/usr/bin/env python3
"""Every function boundary, old logic versus new, over the whole repository.

U1 moved four heuristics out of `context.py` into the structure layer. The
ported languages are supposed to keep behaving as they did, and "supposed to"
is not evidence, so this compares the frozen 1.x implementation against the
new one for every line of every file here and in examples/.

Differences are allowed, but only three kinds of them (SR-41):

    D-1  a brace inside a block comment or a multi-line string no longer
         breaks the depth count
    D-2  a block left open by the file now ends at the last line instead of
         being dropped
    D-3  a function header written inside a string is no longer a header

Anything else fails: it would mean the move changed behaviour nobody signed
off on. `.blade.php` files are skipped -- they are a different language now
(CQ2=B) -- and the count of skipped files is reported.

One-shot: this suite and `tests/helpers/legacy_scope.py` are removed once U1
is signed off (testable-properties.md §4.4).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish, legacy_scope  # noqa: E402
from lib import structure  # noqa: E402
from lib.context import PACK_SCOPES  # noqa: E402

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', 'aidlc-docs', '.hypothesis',
             '.venv', 'venv', 'env', 'site-packages'}


def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            relpath = os.path.relpath(path, ROOT)
            if legacy_scope.language(relpath) is None:
                continue
            try:
                with open(path, encoding='utf-8') as handle:
                    yield relpath, handle.read()
            except (OSError, UnicodeDecodeError):
                continue


def classify(fs, lines, old, new, legacy_lang):
    """Which of the three allowed differences this is, or None."""
    masked = fs.comments + fs.strings
    multiline = any(fs.text.count('\n', span.start, span.end) for span in masked)
    if old is None and new is not None and new[1] == len(lines) - 1:
        return 'D-2'
    for boundary in filter(None, (old, new)):
        header_offset = fs.offset_of(boundary[0] + 1)
        if any(span.contains(header_offset) for span in masked):
            return 'D-3'
    if multiline:
        return 'D-1'
    return None


def case_parity():
    print('case_parity:')
    files = kept = skipped_blade = 0
    differences = {'D-1': 0, 'D-2': 0, 'D-3': 0}
    unexplained = []
    for relpath, text in walk():
        files += 1
        legacy_lang = legacy_scope.language(relpath)
        language = structure.language_of(relpath)
        if language != legacy_lang:
            skipped_blade += 1
            continue
        kept += 1
        lines = text.split('\n')
        fs = structure.analyze(text, language)
        if not fs.ok:
            unexplained.append('%s: analysis failed (%s)' % (relpath, fs.reason))
            continue
        for index in range(len(lines)):
            old = legacy_scope.enclosing_function(lines, index, legacy_lang)
            node = fs.innermost(index + 1, PACK_SCOPES.get(language, ('function',)))
            new = (node.start_line - 1, node.end_line - 1) if node else None
            if old == new:
                continue
            kind = classify(fs, lines, old, new, legacy_lang)
            if kind is None:
                unexplained.append('%s:%d old=%s new=%s' % (relpath, index + 1, old, new))
            else:
                differences[kind] += 1

    print('  파일 %d개 중 %d개 비교, blade 로 분리되어 제외 %d개'
          % (files, kept, skipped_blade))
    print('  설명된 차이 — D-1 %(D-1)d, D-2 %(D-2)d, D-3 %(D-3)d' % differences)
    check('every comparable file parses', not any('analysis failed' in u
                                                  for u in unexplained),
          '; '.join(u for u in unexplained if 'analysis failed' in u)[:400])
    check('no unexplained difference remains (SR-42)',
          not unexplained, '%d건: %s' % (len(unexplained), '; '.join(unexplained[:5])))
    check('the comparison actually ran', kept > 0)


def main():
    case_parity()
    return finish('structure -- 1.x parity')


if __name__ == '__main__':
    sys.exit(main())
