#!/usr/bin/env python3
"""The linter half must be anchored to the change like the rules are.

`phpstan app/Legacy.php` reports the whole file and `go vet ./...` the whole
module. Blocking on all of it meant touching one line in a five-year-old file
failed the turn on errors nobody in this change wrote -- exactly the legacy
explosion the rule triggers are designed to avoid.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from lib import engine, lint  # noqa: E402

FAILED = []


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def ctx_for(root, changed):
    return engine.Context(root, changed, set(), set(), {})


def case_parsers():
    print('case_parsers:')
    root = '/repo'
    eslint = ('[{"filePath":"/repo/src/a.ts","messages":'
              '[{"line":12,"message":"no-any","ruleId":"x"}]}]')
    check('eslint-json', lint.parse_output(root, {'parse': 'eslint-json'}, eslint)
          == [{'file': 'src/a.ts', 'line': 12, 'message': 'no-any (x)'}],
          lint.parse_output(root, {'parse': 'eslint-json'}, eslint))

    phpstan = '{"files":{"/repo/app/A.php":{"messages":[{"line":7,"message":"oops"}]}}}'
    check('phpstan-json', lint.parse_output(root, {'parse': 'phpstan-json'}, phpstan)
          == [{'file': 'app/A.php', 'line': 7, 'message': 'oops'}])

    golangci = ('{"Issues":[{"Pos":{"Filename":"pkg/a.go","Line":5},'
                '"Text":"err ignored","FromLinter":"errcheck"}]}')
    check('golangci-json', lint.parse_output(root, {'parse': 'golangci-json'}, golangci)
          == [{'file': 'pkg/a.go', 'line': 5,
               'message': 'err ignored (errcheck)'}])

    unix = './pkg/a.go:9:3: composite literal uses unkeyed fields\nnot a finding\n'
    check('unix', lint.parse_output(root, {'parse': 'unix'}, unix)
          == [{'file': 'pkg/a.go', 'line': 9,
               'message': 'composite literal uses unkeyed fields'}],
          lint.parse_output(root, {'parse': 'unix'}, unix))

    github = '::error title=lint/style,file=/repo/src/b.ts,line=4,col=1::use const\n'
    check('github', lint.parse_output(root, {'parse': 'github'}, github)
          == [{'file': 'src/b.ts', 'line': 4, 'message': 'use const'}],
          lint.parse_output(root, {'parse': 'github'}, github))

    diff = ('--- a/app/A.php\n+++ b/app/A.php\n@@ -14,2 +14,2 @@\n'
            '-  $x=1;\n+  $x = 1;\n')
    check('diff (minus side anchors to the current file)',
          lint.parse_output(root, {'parse': 'diff'}, diff)
          == [{'file': 'app/A.php', 'line': 14, 'message': '포맷이 규약과 다릅니다'}],
          lint.parse_output(root, {'parse': 'diff'}, diff))

    check('no parse spec means no locations',
          lint.parse_output(root, {}, unix) == [])
    check('garbage output degrades to no locations',
          lint.parse_output(root, {'parse': 'eslint-json'}, 'not json') == [])


def fake_entry(line, parse='unix'):
    script = 'import sys\nprint("src/a.py:%d: something")\nsys.exit(1)\n' % line
    return {'cmd': ['python3', '-c', script, '{files}'], 'parse': parse,
            'files': ['**/*.py'], 'stack': 'fake'}


def case_split(tmp):
    print('case_split:')
    os.makedirs(os.path.join(tmp, 'src'), exist_ok=True)
    with open(os.path.join(tmp, 'src', 'a.py'), 'w') as fh:
        fh.write('\n'.join('line %d' % i for i in range(1, 30)))
    changed = {'src/a.py': [(20, 'line 20')]}
    ctx = ctx_for(tmp, changed)

    failures = lint.run(tmp, [fake_entry(20)], ['src/a.py'])
    blocking, notes = lint.split_by_change(failures, ctx)
    check('finding on a changed line blocks', len(blocking) == 1 and not notes,
          (blocking, notes))

    failures = lint.run(tmp, [fake_entry(3)], ['src/a.py'])
    blocking, notes = lint.split_by_change(failures, ctx)
    check('finding on untouched legacy line does not block',
          not blocking and len(notes) == 1, (blocking, notes))

    unparsed = {'cmd': ['python3', '-c', 'import sys; print("boom"); sys.exit(1)',
                        '{files}'],
                'files': ['**/*.py'], 'stack': 'fake'}
    failures = lint.run(tmp, [unparsed], ['src/a.py'])
    blocking, notes = lint.split_by_change(failures, ctx)
    check('unparseable failure still blocks', len(blocking) == 1, (blocking, notes))

    skipped = lint.run(tmp, [fake_entry(20)], ['README.md'])
    check('a linter with nothing it owns is skipped', skipped == [], skipped)


def case_dirs_placeholder():
    print('case_dirs_placeholder:')
    entry = {'cmd': ['go', 'vet', '{dirs}']}
    argv = lint._build(entry, ['pkg/a/x.go', 'pkg/a/y.go', 'pkg/b/z.go', 'main.go'])
    check('{dirs} collapses to unique packages',
          argv == ['go', 'vet', './pkg/a', './pkg/b', '.'], argv)


FAKE_LINTER = ('import os, sys\n'
               'print("src/a.py:%s: problem" % os.environ["CG_TEST_LINE"])\n'
               'sys.exit(1)\n')


def fake_plugin(tmp):
    """A plugin root with one stack whose only linter we control."""
    plug = os.path.join(tmp, 'plug')
    os.makedirs(os.path.join(plug, 'rules'), exist_ok=True)
    os.makedirs(os.path.join(plug, 'stacks'), exist_ok=True)
    with open(os.path.join(plug, 'stacks', 'fake.yaml'), 'w', encoding='utf-8') as fh:
        fh.write('id: fake\n'
                 'tags: [fake]\n'
                 'detect:\n'
                 '  file: marker.txt\n'
                 'lint:\n'
                 '  - cmd: ["python3", "-c", %s, "{files}"]\n'
                 '    files: ["**/*.py"]\n'
                 '    parse: unix\n' % json.dumps(FAKE_LINTER))
    return plug


def case_hook_blocks_only_changed_lines(tmp):
    """The whole path, through the real Stop hook."""
    print('case_hook_blocks_only_changed_lines:')
    repo = os.path.join(tmp, 'repo')
    os.makedirs(os.path.join(repo, 'src'), exist_ok=True)
    subprocess.run(['git', 'init', '-q', repo], check=True)
    for key, value in (('user.email', 't@t'), ('user.name', 't')):
        subprocess.run(['git', '-C', repo, 'config', key, value], check=True)
    with open(os.path.join(repo, 'marker.txt'), 'w') as fh:
        fh.write('fake stack\n')
    body = ['line %d' % i for i in range(1, 31)]
    with open(os.path.join(repo, 'src', 'a.py'), 'w') as fh:
        fh.write('\n'.join(body) + '\n')
    subprocess.run(['git', '-C', repo, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', repo, 'commit', '-q', '-m', 'init'], check=True)
    body[19] = 'line 20 changed'
    with open(os.path.join(repo, 'src', 'a.py'), 'w') as fh:
        fh.write('\n'.join(body) + '\n')

    plug = fake_plugin(tmp)

    def stop(line, session):
        env = dict(os.environ, CLAUDE_PLUGIN_ROOT=plug,
                   CLAUDE_PLUGIN_DATA=os.path.join(tmp, 'data-%s' % session),
                   CLAUDE_PROJECT_DIR=repo, CG_TEST_LINE=str(line))
        for script, payload in (
                ('collect.py', {'session_id': session, 'cwd': repo,
                                'tool_name': 'Edit',
                                'tool_input': {'file_path': 'src/a.py'}}),
                ('check.py', {'session_id': session, 'cwd': repo,
                              'prompt_id': 'p1', 'hook_event_name': 'Stop',
                              'last_assistant_message': 'done.'})):
            proc = subprocess.run(
                ['python3', os.path.join(ROOT, 'scripts', script)],
                input=json.dumps(payload), capture_output=True, text=True,
                env=env, cwd=repo)
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return out, proc.stderr

    legacy, err = stop(3, 'legacy')
    check('a linter finding on an untouched line does not block the turn',
          legacy.get('decision') is None, (legacy, err))
    check('it is still reported to the user',
          '기존 코드' in (legacy.get('systemMessage') or ''), legacy)

    ours, err = stop(20, 'ours')
    check('a linter finding on a changed line blocks',
          ours.get('decision') == 'block', (ours, err))
    check('the reason carries the file and line',
          'src/a.py:20' in (ours.get('reason') or ''), ours.get('reason'))


def main():
    case_parsers()
    tmp = tempfile.mkdtemp()
    try:
        case_split(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    case_dirs_placeholder()
    tmp = tempfile.mkdtemp()
    try:
        case_hook_blocks_only_changed_lines(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print('\n실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('\n통과 — 린터 앵커링')
    return 0


if __name__ == '__main__':
    sys.exit(main())
