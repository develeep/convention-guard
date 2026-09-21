#!/usr/bin/env python3
"""The linter half must be anchored to the change like the rules are.

`phpstan app/Legacy.php` reports the whole file and `go vet ./...` the whole
module. Blocking on all of it meant touching one line in a five-year-old file
failed the turn on errors nobody in this change wrote -- exactly the legacy
explosion the rule triggers are designed to avoid.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (Session, check, make_repo, run_cases, write)  # noqa: E402
from lib import lint  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402


def ctx_for(root, changed):
    return ChangeScope(root, changed, set(), 'test')


def case_parsers():
    root = '/repo'

    def parsed(kind, text):
        return [(loc['file'], loc['line']) for loc in
                lint.parse_output(root, {'parse': kind}, text)]

    eslint = ('[{"filePath":"/repo/src/a.ts","messages":'
              '[{"line":12,"message":"no-any","ruleId":"x"}]}]')
    check('eslint-json', parsed('eslint-json', eslint) == [('src/a.ts', 12)],
          parsed('eslint-json', eslint))
    phpstan = '{"files":{"/repo/app/A.php":{"messages":[{"line":7,"message":"oops"}]}}}'
    check('phpstan-json', parsed('phpstan-json', phpstan) == [('app/A.php', 7)])
    golangci = ('{"Issues":[{"Pos":{"Filename":"pkg/a.go","Line":5},'
                '"Text":"err ignored","FromLinter":"errcheck"}]}')
    check('golangci-json', parsed('golangci-json', golangci) == [('pkg/a.go', 5)])
    unix = './pkg/a.go:9:3: composite literal uses unkeyed fields\nnot a finding\n'
    check('unix', parsed('unix', unix) == [('pkg/a.go', 9)], parsed('unix', unix))
    github = '::error title=lint/style,file=/repo/src/b.ts,line=4,col=1::use const\n'
    check('github', parsed('github', github) == [('src/b.ts', 4)], parsed('github', github))
    diff = ('--- a/app/A.php\n+++ b/app/A.php\n@@ -14,2 +14,2 @@\n'
            '-  $x=1;\n+  $x = 1;\n')
    check('diff (minus side anchors to the current file)',
          parsed('diff', diff) == [('app/A.php', 14)], parsed('diff', diff))
    check('no parse spec means no locations', lint.parse_output(root, {}, unix) == [])
    check('garbage output degrades to no locations', parsed('eslint-json', 'not json') == [])


def fake_entry(line, parse='unix'):
    script = 'import sys\nprint("src/a.py:%d: something")\nsys.exit(1)\n' % line
    return {'cmd': [sys.executable, '-c', script, '{files}'], 'parse': parse,
            'files': ['**/*.py'], 'stack': 'fake'}


def case_split(tmp):
    write(tmp, 'src/a.py', '\n'.join('line %d' % i for i in range(1, 30)))
    ctx = ctx_for(tmp, {'src/a.py': [(20, 'line 20')]})

    blocking, notes = lint.split_by_change(lint.run(tmp, [fake_entry(20)], ['src/a.py']), ctx)
    check('finding on a changed line blocks', len(blocking) == 1 and not notes,
          (blocking, notes))

    blocking, notes = lint.split_by_change(lint.run(tmp, [fake_entry(3)], ['src/a.py']), ctx)
    check('finding on untouched legacy line does not block',
          not blocking and len(notes) == 1, (blocking, notes))

    unparsed = {'cmd': [sys.executable, '-c', 'import sys; print("boom"); sys.exit(1)',
                        '{files}'], 'files': ['**/*.py'], 'stack': 'fake'}
    blocking, notes = lint.split_by_change(lint.run(tmp, [unparsed], ['src/a.py']), ctx)
    check('unparseable failure still blocks', len(blocking) == 1, (blocking, notes))

    skipped = lint.run(tmp, [fake_entry(20)], ['README.md'])
    check('a linter with nothing it owns is skipped', skipped == [], skipped)


def slow_entry(seconds):
    script = 'import time, sys\ntime.sleep(%s)\nsys.exit(1)\n' % seconds
    return {'cmd': [sys.executable, '-c', script, '{files}'], 'parse': 'unix',
            'files': ['**/*.py'], 'stack': 'slow'}


def case_lint_budget(tmp):
    """`linters.timeout` is per linter and they run in sequence, so N linters
    can outlive the Stop hook's own timeout. A killed hook prints nothing, which
    reads as a clean check -- so the budget must cut the phase short *and say so*.
    """
    write(tmp, 'src/a.py', 'line 1\n')

    notes = []
    failures = lint.run(tmp, [slow_entry(5)], ['src/a.py'], timeout=30, budget=1, notes=notes)
    check('a linter that outlives the budget reports nothing', failures == [], failures)
    check('and it is not silent about it',
          any(level == 'warn' and '검사되지 않았습니다' in text for level, text in notes), notes)

    notes = []
    failures = lint.run(tmp, [slow_entry(5), fake_entry(1)], ['src/a.py'],
                        timeout=30, budget=1, notes=notes)
    check('the linter behind it is not run either', failures == [], failures)
    check('both are reported as unchecked', len(notes) == 2, notes)

    notes = []
    failures = lint.run(tmp, [fake_entry(1)], ['src/a.py'], timeout=30, budget=60, notes=notes)
    check('a linter that fits the budget still runs normally',
          len(failures) == 1 and not notes, (failures, notes))

    notes = []
    lint.run(tmp, [slow_entry(5)], ['src/a.py'], timeout=1, notes=notes)
    check('a per-linter timeout is reported too, not swallowed',
          len(notes) == 1 and '1초' in notes[0][1], notes)


def case_lint_file_chunks(tmp):
    log = os.path.join(tmp, 'seen.txt')
    script = ('import sys\n'
              'with open(sys.argv[1], "a") as fh:\n'
              '    fh.write("\\n".join(sys.argv[2:]) + "\\n")\n')
    files = ['src/f%d.py' % i for i in range(5)]
    for rel in files:
        write(tmp, rel, 'pass\n')
    entry = {'cmd': [sys.executable, '-c', script, log, '{files}'],
             'files': ['**/*.py'], 'stack': 'fake'}
    notes = []
    failures = lint.run(tmp, [entry], files, max_files=2, notes=notes)
    with open(log, encoding='utf-8') as fh:
        seen = sorted(line.strip() for line in fh if line.strip())
    check('a linter processes every owned file in bounded chunks',
          seen == sorted(files), seen)
    check('successful chunks do not create failures or warnings',
          failures == [] and notes == [], (failures, notes))

    failing = {'cmd': [sys.executable, '-c',
                       'import sys; print(sys.argv[-1] + ":1: bad"); sys.exit(1)',
                       '{files}'],
               'parse': 'unix', 'files': ['**/*.py'], 'stack': 'fake'}
    before = lint.run(tmp, [failing], files, max_files=2)
    extra = 'src/a-first.py'
    write(tmp, extra, 'pass\n')
    after = lint.run(tmp, [failing], [extra] + files, max_files=2)
    before_keys = {failure.get('key') for failure in before}
    after_keys = {failure.get('key') for failure in after}
    check('all chunks of one linter use one stable verification key',
          None not in before_keys and len(before_keys) == 1
          and before_keys == after_keys, (before_keys, after_keys))


def case_dirs_placeholder():
    argv = lint._build({'cmd': ['go', 'vet', '{dirs}']},
                       ['pkg/a/x.go', 'pkg/a/y.go', 'pkg/b/z.go', 'main.go'])
    check('{dirs} collapses to unique packages',
          argv == ['go', 'vet', './pkg/a', './pkg/b', '.'], argv)


FAKE_LINTER = ('import os, sys\n'
               'print("src/a.py:%s: problem" % os.environ["CG_TEST_LINE"])\n'
               'sys.exit(1)\n')


def fake_plugin(tmp):
    """A plugin root with one stack whose only linter we control."""
    plug = os.path.join(tmp, 'plug')
    os.makedirs(os.path.join(plug, 'rules'), exist_ok=True)
    write(plug, 'config.yaml', 'mode: fix\n')
    write(plug, 'stacks/fake.yaml',
          'id: fake\n'
          'tags: [fake]\n'
          'detect:\n'
          '  file: marker.txt\n'
          'lint:\n'
          '  - cmd: [%s, "-c", %s, "{files}"]\n'
          '    files: ["**/*.py"]\n'
          '    parse: unix\n' % (json.dumps(sys.executable), json.dumps(FAKE_LINTER)))
    return plug


def slow_plugin(tmp):
    plug = os.path.join(tmp, 'slow-plug')
    os.makedirs(os.path.join(plug, 'rules'), exist_ok=True)
    write(plug, 'config.yaml', 'mode: report\n')
    write(plug, 'rules/error.yaml',
          'id: forced-error\n'
          'title: forced error\n'
          'severity: error\n'
          'applies_to:\n  stacks: ["fake"]\n  files: ["**/*.py"]\n'
          'detect:\n  when_line_added: BAD\n')
    write(plug, 'presets/common.yaml',
          'name: common\nstacks: ["*"]\nrules: ["core/forced-error"]\n')
    script = 'import time\ntime.sleep(2)\n'
    write(plug, 'stacks/fake.yaml',
          'id: fake\n'
          'tags: [fake]\n'
          'detect:\n'
          '  file: marker.txt\n'
          'lint:\n'
          '  - cmd: [%s, "-c", %s, "{files}"]\n'
          '    files: ["**/*.py"]\n'
          '    parse: unix\n' % (json.dumps(sys.executable), json.dumps(script)))
    return plug


def case_hook_reports_unchecked_linter(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'marker.txt': 'fake stack\n', 'src/a.py': 'old\n'})
    write(repo, '.claude/convention-guard/config.yaml',
          'mode: report\ndisable: ["core/does-not-exist"]\nlinters:\n  timeout: 1\n')
    write(repo, 'src/a.py', 'BAD changed\n')
    session = Session(repo, os.path.join(tmp, 'data'), 'unchecked',
                      plugin_root=slow_plugin(tmp))
    session.touch('src/a.py')
    out = session.stop('p1')
    check('a skipped linter warning reaches report-mode early output',
          '검사되지 않았습니다' in out['summary'], out)


def case_hook_blocks_only_changed_lines(tmp):
    """The whole path, through the real Stop hook."""
    repo = os.path.join(tmp, 'repo')
    body = ['line %d' % i for i in range(1, 31)]
    make_repo(repo, {'marker.txt': 'fake stack\n', 'src/a.py': '\n'.join(body) + '\n'})
    body[19] = 'line 20 changed'
    write(repo, 'src/a.py', '\n'.join(body) + '\n')
    plug = fake_plugin(tmp)

    def stop(line, name):
        session = Session(repo, os.path.join(tmp, 'data-%s' % name), name,
                          plugin_root=plug, CG_TEST_LINE=line)
        session.touch('src/a.py')
        return session.stop('p1')

    legacy = stop(3, 'legacy')
    check('a linter finding on an untouched line does not block the turn',
          legacy['decision'] is None, legacy)
    check('it is still reported to the user', '기존 코드' in legacy['summary'], legacy)

    ours = stop(20, 'ours')
    check('a linter finding on a changed line blocks', ours['decision'] == 'block', ours)
    check('the reason carries the file and line', 'src/a.py:20' in ours['reason'],
          ours['reason'])


def main():
    print('case_parsers:')
    case_parsers()
    print('case_dirs_placeholder:')
    case_dirs_placeholder()
    return run_cases([case_split, case_lint_budget, case_lint_file_chunks,
                      case_hook_reports_unchecked_linter,
                      case_hook_blocks_only_changed_lines],
                     '린터 앵커링')


if __name__ == '__main__':
    sys.exit(main())
