#!/usr/bin/env python3
"""Structure conditions inside the detector.

`business-rules.md` DR-09~DR-24. The detector still owns anchors and the cap;
the conditions are a filter that runs where dismissals already run, and a file
the layer could not read produces a candidate plus a notice -- never silence.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish, fixtures, tempdir  # noqa: E402
from lib import detect, report, stop, structure  # noqa: E402
from lib.rules import fixtures as rulefixtures, schema  # noqa: E402

PHP = '<?php\n'


class FakeScope:
    """The slice of Scope the detector uses, over in-memory files."""

    def __init__(self, files, changed=None, new=()):
        self.files = files
        self.changed = changed or {
            path: tuple(enumerate(text.split('\n'), start=1))
            for path, text in files.items()}
        self.new_files = set(new)
        self.reads = 0

    def paths(self):
        return sorted(self.files)

    def text(self, relpath):
        self.reads += 1
        return self.files.get(relpath, '')

    def lines(self, relpath):
        return self.changed.get(relpath, ())

    def changed_linenos(self, relpath):
        return {n for n, _ in self.changed.get(relpath, ())}

    def seams_of(self, relpath):
        return frozenset()

    def added_body(self, relpath):
        return '\n'.join(t for _, t in self.changed.get(relpath, ()))

    def is_new(self, relpath):
        return relpath in self.new_files


def rule(**detect_spec):
    raw = {'id': 'r', 'title': 't', 'severity': 'warn',
           'applies_to': {'stacks': ['*']}, 'detect': detect_spec, 'message': 'm'}
    return schema.normalize(raw, 'r.yaml', 'local')


def stacks():
    return detect.Stacks(tags=['*'])


def scan(rule_obj, scope, cap=10, unchecked=None):
    return detect.scan(rule_obj, scope, stacks(), cap, unchecked=unchecked)


def case_gate():
    print('case_gate:')
    counter = {'analyze': 0}
    original = structure.analyze

    def counted(text, language):
        counter['analyze'] += 1
        return original(text, language)

    structure.analyze = counted
    try:
        scope = FakeScope({'a.php': PHP + 'dd(1);\n'})
        found = scan(rule(when_line_added=r'dd\('), scope)
        check('a rule without conditions still finds its candidate', len(found) == 1)
        check('and never analyses the file (NR-U2-13)', counter['analyze'] == 0,
              str(counter))
        check('and never reads it either', scope.reads == 0, str(scope.reads))

        scope = FakeScope({'a.php': PHP + 'dd(1);\n'})
        scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope)
        check('a rule with conditions does analyse', counter['analyze'] == 1,
              str(counter))
    finally:
        structure.analyze = original


def case_not_in_line():
    print('case_not_in_line:')
    scope = FakeScope({'a.php': PHP + '// dd(1)\ndd(2);\n'})
    found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope)
    lines = [c.line for c in found]
    check('the commented match is filtered, the real one survives',
          lines == [3], str(lines))

    scope = FakeScope({'a.php': PHP + '$s = "dd(1)";\n'})
    found = scan(rule(when_line_added=r'dd\(', not_in=['string']), scope)
    check('a match inside a string is filtered', found == [], str(found))

    scope = FakeScope({'a.php': PHP + '$s = "dd(1)";\n'})
    found = scan(rule(when_line_added=r'dd\('), scope)
    check('without the condition it fires (1.x behaviour)', len(found) == 1)


def case_in_scope_and_block_empty():
    print('case_in_scope_and_block_empty:')
    text = PHP + 'function f() {\n    foreach ($a as $b) {\n        dd(1);\n    }\n}\ndd(2);\n'
    scope = FakeScope({'a.php': text})
    found = scan(rule(when_line_added=r'dd\(', in_scope='loop'), scope)
    check('only the match inside the loop survives',
          [c.line for c in found] == [4], str([c.line for c in found]))

    empty = PHP + 'try { go(); } catch (\\Throwable $e) {\n}\n'
    commented = PHP + 'try { go(); } catch (\\Throwable $e) {\n    // 무시\n}\n'
    spec = {'file_regex': r'catch\s*\([^)]*\)\s*\{[^}]*\}', 'block_empty': True}
    check('an empty catch is reported',
          len(scan(rule(**spec), FakeScope({'a.php': empty}))) == 1)
    check('a commented catch is not (US-10)',
          scan(rule(**spec), FakeScope({'a.php': commented})) == [], 'commented')


def case_unknown_is_recorded():
    print('case_unknown_is_recorded:')
    broken = PHP + '$a = "oops;\ndd(1);\n'
    scope = FakeScope({'a.php': broken})
    unchecked = detect.Unchecked()
    found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope, unchecked=unchecked)
    check('a file that would not parse still yields the candidate (D5)', len(found) == 1)
    check('and is recorded as unchecked', unchecked.files() == ('a.php',),
          str(unchecked.files()))
    check('with the reason from the structure layer',
          unchecked.reason('a.php').startswith('unterminated_string'),
          unchecked.reason('a.php'))

    scope = FakeScope({'notes.txt': 'dd(1)\n'})
    unchecked = detect.Unchecked()
    found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope, unchecked=unchecked)
    check('an unsupported language is unchecked, not silently passed',
          len(found) == 1 and unchecked.reason('notes.txt') == 'unsupported_language',
          str(unchecked.reason('notes.txt')))

    blade = "<p>x</p>\n<?php dd(1); ?>\n"
    scope = FakeScope({'v.blade.php': blade})
    unchecked = detect.Unchecked()
    found = scan(rule(when_line_added=r'dd\(', in_scope='function'), scope,
                 unchecked=unchecked)
    check('blade has no scopes, so in_scope is unchecked (CQ2=B)',
          len(found) == 1 and unchecked.reason('v.blade.php') == 'no_scope:blade',
          str(unchecked.reason('v.blade.php')))


def case_stale_line():
    print('case_stale_line:')
    scope = FakeScope({'a.php': PHP + 'clean();\n'},
                      changed={'a.php': ((2, 'dd(1);'),)})   # diff and tree disagree
    unchecked = detect.Unchecked()
    found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope,
                 unchecked=unchecked)
    check('a line that no longer matches the file is not judged (SR-31)',
          len(found) == 1 and unchecked.reason('a.php') == 'stale_line:2',
          str(unchecked.reason('a.php')))


def case_cap():
    print('case_cap:')
    body = PHP + ''.join('// dd(%d)\n' % i for i in range(5)) + 'dd(99);\n'
    scope = FakeScope({'a.php': body})
    found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope, cap=2)
    check('filtered matches do not fill the cap (DR-14)',
          [c.line for c in found] == [7], str([c.line for c in found]))


def case_every_match_on_the_line():
    """R5 -- a rejected first match must not hide a real one on the same line."""
    print('case_every_match_on_the_line:')
    spec = {'when_line_added': r'dd\(', 'not_in': ['comment', 'string']}
    scope = FakeScope({'a.php': PHP + '$label = "dd("; dd($user);\n'})
    found = scan(rule(**spec), scope)
    check('a string before the call does not hide it',
          [c.line for c in found] == [2], str([c.line for c in found]))

    js = {'when_line_added': r'console\.log\(', 'not_in': ['comment', 'string']}
    scope = FakeScope({'a.js': 'const s = "console.log("; console.log(x);\n'})
    found = scan(rule(**js), scope)
    check('same in JS', [c.line for c in found] == [1], str([c.line for c in found]))

    scope = FakeScope({'a.php': PHP + '$a = "dd("; // dd(1)\n'})
    check('a line whose every match is rejected stays quiet',
          scan(rule(**spec), scope) == [])

    req = {'when_line_added': r'run\(', 'must_contain_in_file': r'guard\(',
           'not_in': ['comment']}
    scope = FakeScope({'a.php': PHP + '/* run( */ run();\n'})
    found = scan(rule(**req), scope)
    check('a requires trigger behind a commented one is found',
          [c.line for c in found] == [2], str([c.line for c in found]))

    def fixture(spec_):
        # a fragment needs a language, or every condition is UNKNOWN and keeps it
        return rulefixtures.matcher(dict(rule(**spec_), tests={'lang': 'php'}))

    check('the fixture runner agrees on line rules',
          fixture(spec)('$label = "dd("; dd($user);'))
    check('and on requires rules', fixture(req)('/* run( */ run();'))
    check('and still rejects a line of rejected matches',
          not fixture(spec)('$a = "dd("; // dd(1)'))


def case_requirement_outside_comments():
    """R6 -- a requirement that only appears in a comment is not there."""
    print('case_requirement_outside_comments:')
    req = {'when_line_added': r'run\(', 'must_contain_in_file': r'guard\('}

    def lines(text, **extra):
        return [c.line for c in scan(rule(**dict(req, **extra)), FakeScope({'a.php': text}))]

    commented = PHP + '// guard();\nrun();\n'
    check('a commented requirement does not count, without any condition',
          lines(commented) == [3], str(lines(commented)))
    check('nor with a condition on the trigger',
          lines(commented, not_in=['comment']) == [3])
    check('a real one after a commented one does',
          lines(PHP + '// guard();\nguard();\nrun();\n') == [])
    check('must_not_in: [] counts comments again (license headers)',
          lines(commented, must_not_in=[]) == [])

    in_string = PHP + '$note = "guard() later";\nrun();\n'
    check('a string still counts by default', lines(in_string) == [])
    check('unless the rule opts strings out',
          lines(in_string, must_not_in=['comment', 'string']) == [3])

    absent = {'when_file_added': True, 'must_contain_in_file': r'declare\(strict_types=1\)'}
    scope = FakeScope({'a.php': PHP + '// declare(strict_types=1);\nclass A {}\n'},
                      new=['a.php'])
    check('absent: a commented declaration is missing',
          [c.line for c in scan(rule(**absent), scope)] == [1])

    unchecked = detect.Unchecked()
    scope = FakeScope({'a.php': PHP + '$a = "oops;\n// guard();\nrun();\n'})
    found = scan(rule(**req), scope, unchecked=unchecked)
    check('a file that will not parse keeps the plain answer',
          found == [], str([c.line for c in found]))
    check('and is reported as unchecked',
          (unchecked.reason('a.php') or '').startswith('unterminated_string'),
          str(unchecked.reason('a.php')))

    scope = FakeScope({'a.php': PHP + 'run();\n'})
    unchecked = detect.Unchecked()
    scan(rule(**req), scope, unchecked=unchecked)
    check('no requirement in the text, nothing analysed or recorded', not unchecked)

    def fixture(spec_, sample):
        return rulefixtures.matcher(dict(rule(**spec_), tests={'lang': 'php'}))(sample)

    check('the fixture runner agrees on requires', fixture(req, '// guard();\nrun();'))
    check('and on absent', fixture(absent, '// declare(strict_types=1);'))
    check('and on opted-out strings',
          fixture(dict(req, must_not_in=['string']), '$n = "guard()";\nrun();'))

    for bad, why in (({'must_not_in': ['comments']}, 'unknown value'),
                     ({'when_line_added': 'x', 'must_not_in': ['comment']},
                      'no requirement to qualify')):
        spec = dict(req, **bad) if 'when_line_added' not in bad else bad
        try:
            rule(**spec)
            ok = False
        except schema.RuleError:
            ok = True
        check('schema rejects must_not_in with %s' % why, ok)


def case_unchecked_collector():
    print('case_unchecked_collector:')
    unchecked = detect.Unchecked()
    unchecked.record('b.php', 'first')
    unchecked.record('a.php', 'second')
    unchecked.record('b.php', 'later')
    check('files come back sorted', unchecked.files() == ('a.php', 'b.php'))
    check('the first reason wins (DR-20)', unchecked.reason('b.php') == 'first')
    check('it knows when it is empty', not detect.Unchecked())

    many = detect.Unchecked()
    for i in range(25):
        many.record('f%02d.php' % i, 'r')
    shown, folded = many.summary(limit=20)
    check('a long list folds', len(shown) == 20 and folded == 5, str(folded))
    shown, folded = many.summary()
    check('no limit shows everything', len(shown) == 25 and folded == 0)


def case_notice():
    print('case_notice:')
    check('nothing to say when everything parsed',
          report.unchecked_note(detect.Unchecked()) is None)

    unchecked = detect.Unchecked()
    unchecked.record('b.php', 'unterminated_string:4')
    unchecked.record('a.php', 'no_scope:blade')
    note = report.unchecked_note(unchecked)
    check('the note names the files, sorted', 'a.php, b.php' in note, note)
    check('it counts them', '2개 파일' in note, note)
    check('it says the candidates came through', '후보' in note, note)
    check('reason codes stay out of the message',
          'no_scope' not in note and 'unterminated' not in note, note)

    many = detect.Unchecked()
    for i in range(25):
        many.record('f%02d.php' % i, 'r')
    folded = report.unchecked_note(many, limit=20)
    check('the audit path folds a long list', '외 5개' in folded, folded)


UNCHECKED_LIMIT = 0.05          # NR-U2-08


def _unchecked_ratio(root):
    """(tried, unknown) over every file the layer claims to understand."""
    skip = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'aidlc-docs',
            '.hypothesis', 'vendor'}
    tried = unknown = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for name in sorted(filenames):
            relpath = os.path.relpath(os.path.join(dirpath, name), root)
            language = structure.language_of(relpath)
            if language is None:
                continue
            try:
                with open(os.path.join(root, relpath), encoding='utf-8') as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            tried += 1
            analysed = structure.analyze(text, language)
            if not analysed.ok or not analysed.scope_supported:
                unknown += 1
    return tried, unknown


def case_unchecked_ratio():
    """NR-U2-08 -- how much of a real repository the layer cannot read."""
    print('case_unchecked_ratio:')
    tried = unknown = 0
    for builder in (fixtures.laravel_repo, fixtures.next_repo,
                    fixtures.nest_repo):
        with tempdir() as tmp:
            builder(tmp)
            got_tried, got_unknown = _unchecked_ratio(tmp)
            tried += got_tried
            unknown += got_unknown
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    got_tried, got_unknown = _unchecked_ratio(here)
    tried += got_tried
    unknown += got_unknown
    ratio = unknown / tried if tried else 0.0
    print('  시도 %d개 파일 중 미확인 %d개 = %.2f%%' % (tried, unknown, ratio * 100))
    check('the corpus stays under the unchecked threshold (NR-U2-08)',
          ratio <= UNCHECKED_LIMIT, '%.2f%% > %.0f%%' % (ratio * 100, UNCHECKED_LIMIT * 100))
    check('the comparison actually ran', tried > 50, str(tried))


class _FakeScan:
    def __init__(self, unchecked):
        self.result = type('R', (), {'unchecked': unchecked, 'too_large': (),
                                       'unknown': ()})()


def _scan(unchecked):
    return _FakeScan(unchecked) if unchecked is not None else None


def case_notice_is_attached():
    """The notice reaches the hook output whatever else it carries."""
    print('case_notice_is_attached:')
    unchecked = detect.Unchecked()
    unchecked.record('a.php', 'unterminated_string:2')
    scan = _scan(unchecked)

    out = stop.with_notes(None, scan)
    check('a silent turn gains a systemMessage',
          out and '구조 미확인' in out['systemMessage'], str(out))

    blocked = {'decision': 'block', 'reason': 'r', 'systemMessage': '기존'}
    out = stop.with_notes(dict(blocked), scan)
    check('a blocking turn keeps its decision and reason',
          out['decision'] == 'block' and out['reason'] == 'r')
    check('and its existing message is kept alongside',
          out['systemMessage'].startswith('기존 · '), out['systemMessage'])

    passing = {'systemMessage': '요약'}
    out = stop.with_notes(dict(passing), scan)
    check('a passing turn joins the two messages',
          '요약 · ' in out['systemMessage'], out['systemMessage'])

    check('nothing is added when everything parsed',
          stop.with_notes(None, _scan(detect.Unchecked())) is None)
    check('nor when there was no scan at all',
          stop.with_notes(None, _scan(None)) is None)


def case_layer_failure_is_survivable():
    """If the structure layer broke its own contract the hook still finishes."""
    print('case_layer_failure_is_survivable:')
    original = structure.analyze

    def explode(_text, _language):
        raise RuntimeError('contract broken')

    structure.analyze = explode
    try:
        scope = FakeScope({'a.php': PHP + 'dd(1);\n'})
        unchecked = detect.Unchecked()
        found = scan(rule(when_line_added=r'dd\(', not_in=['comment']), scope,
                     unchecked=unchecked)
    finally:
        structure.analyze = original
    check('the candidate survives', len(found) == 1)
    check('and the file is reported as unchecked',
          unchecked.reason('a.php') == 'internal_error:Detect',
          str(unchecked.reason('a.php')))


def case_run_passes_the_collector():
    print('case_run_passes_the_collector:')
    scope = FakeScope({'a.php': PHP + '$a = "oops;\ndd(1);\n'})
    unchecked = detect.Unchecked()
    hits = detect.run([rule(when_line_added=r'dd\(', not_in=['comment'])], scope,
                      stacks(), 10, unchecked=unchecked)
    check('run() reports the hit', len(hits) == 1 and len(hits[0][1]) == 1)
    check('and threads the collector through', unchecked.files() == ('a.php',))


def main():
    for case in (case_gate, case_not_in_line, case_in_scope_and_block_empty,
                 case_unknown_is_recorded, case_stale_line, case_cap,
                 case_every_match_on_the_line, case_requirement_outside_comments, case_unchecked_collector,
                 case_notice, case_notice_is_attached,
                 case_layer_failure_is_survivable, case_run_passes_the_collector,
                 case_unchecked_ratio):
        case()
    return finish('detect + structure conditions')


if __name__ == '__main__':
    sys.exit(main())
