#!/usr/bin/env python3
"""Auto-fix: mechanical, bounded to this change, and never a surprise.

1. mode: auto-fix rewrites only flagged added lines of rules with fix.auto;
   the same pattern in committed legacy code is left alone.
2. What the fix resolves no longer blocks; what it cannot fix still does, and
   the agent is told which files changed under it.
3. A line that changed after detection is not rewritten.
4. The file keeps its line endings.
5. scan.py --fix only shows; --fix --write applies and reports what is left.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, ROOT, Session, check, finish,  # noqa: E402
                     isolated_env, make_repo, run_script, tempdir, write)
from lib import autofix, detect, rules as rulelib  # noqa: E402
from lib.scope import ChangeScope  # noqa: E402

HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Svc;\n\n'
LEGACY = HDR + 'class Old\n{\n    public function f($v)\n    {\n        return ( int )$v;\n    }\n}\n'


def new_file(extra=''):
    return (HDR + 'class A\n{\n    public function f($v)\n    {\n'
            '        $n = ( int )$v;\n'
            '        if ($n > 1) {\n        } else if ($n > 2) {\n        }\n'
            + extra + '        return $n;\n    }\n}\n')


def repo(tmp, mode='auto-fix'):
    path = os.path.join(tmp, 'repo')
    make_repo(path, {'composer.json': LARAVEL_COMPOSER, 'app/Svc/Old.php': LEGACY,
                     '.claude/convention-guard/config.yaml': 'mode: %s\n' % mode})
    return path


def read(path, rel):
    with open(os.path.join(path, rel), encoding='utf-8', newline='') as fh:
        return fh.read()


def case_hook_fixes_what_it_can():
    print('case_hook_fixes_what_it_can:')
    with tempdir() as tmp:
        path = repo(tmp)
        s = Session(path, os.path.join(tmp, 'data'), 'fix')
        # touch the legacy file too, so it is in scope but its old line is not added
        write(path, 'app/Svc/Old.php', LEGACY.replace('}\n', '}\n// touched\n', 1))
        s.touch('app/Svc/Old.php')
        result = s.turn('app/Svc/A.php', new_file('        dd($n);\n'), 'p1')
        body = read(path, 'app/Svc/A.php')
        check('the cast spacing was fixed', '(int)$v' in body and '( int )' not in body, body)
        check('else if became elseif', 'elseif (' in body and 'else if' not in body, body)
        check('legacy code was not touched', '( int )$v' in read(path, 'app/Svc/Old.php'))
        check('what cannot be auto-fixed still blocks', result['decision'] == 'block', result)
        check('the block says which files changed', '자동 수정 — 2건' in result['reason']
              and 'app/Svc/A.php' in result['reason'], result['reason'][:400])
        check('fixed rules are not listed as findings',
              'php-cast-spacing' not in result['reason'].split('■ 지적')[-1], result['reason'])
        check('each fix is logged', len(s.events('autofix')) == 2, s.events('autofix'))


def case_only_fixable_passes():
    print('case_only_fixable_passes:')
    with tempdir() as tmp:
        path = repo(tmp)
        s = Session(path, os.path.join(tmp, 'data'), 'clean')
        result = s.turn('app/Svc/A.php', new_file(), 'p1')
        check('nothing left to block', result['decision'] is None, result)
        check('but the user is told what changed', '자동 수정 2 (' in result['summary'],
              result['summary'])


def case_fix_mode_does_not_edit():
    print('case_fix_mode_does_not_edit:')
    with tempdir() as tmp:
        path = repo(tmp, mode='fix')
        s = Session(path, os.path.join(tmp, 'data'), 'nofix')
        s.turn('app/Svc/A.php', new_file(), 'p1')
        check('mode fix never edits files', read(path, 'app/Svc/A.php') == new_file())


def case_stale_line_and_crlf():
    print('case_stale_line_and_crlf:')
    with tempdir() as tmp:
        path = repo(tmp)
        crlf = new_file().replace('\n', '\r\n')
        write(path, 'app/Svc/A.php', crlf)
        rules = [r for r in rulelib.load(path, ROOT, {'presets': 'auto'}, {'php'}).rules
                 if r.get('fix')]
        scope = ChangeScope.working_tree(path)
        hits = detect.run(rules, scope, rulelib.Reach(detect.Stacks({'php'})), 10)
        fixes = autofix.plan(path, hits)
        check('two fixes are planned', len(fixes) == 2, [f.to_dict() for f in fixes])

        stale = crlf.replace('( int )$v', '( int )$value')
        write(path, 'app/Svc/A.php', stale)
        applied = autofix.apply(path, fixes)
        check('a line that changed after detection is skipped',
              [f.rule_id for f in applied] == ['core/php-use-elseif'],
              [f.to_dict() for f in applied])
        after = read(path, 'app/Svc/A.php')
        check('CRLF is kept', after.count('\r\n') == stale.count('\r\n') and '\n' not in
              after.replace('\r\n', ''), repr(after[:120]))


def case_bom_first_line():
    """R6 -- detection no longer sees the BOM; the fix must still find line 1."""
    print('case_bom_first_line:')
    with tempdir() as tmp:
        path = repo(tmp)
        body = '﻿<?php $n = ( int )$v;\n'
        with open(os.path.join(path, 'app/Svc/B.php'), 'w', encoding='utf-8',
                  newline='') as fh:
            fh.write(body)
        rules = [r for r in rulelib.load(path, ROOT, {'presets': 'auto'}, {'php'}).rules
                 if r.get('fix')]
        hits = detect.run(rules, ChangeScope.working_tree(path), rulelib.Reach(detect.Stacks({'php'})), 10)
        applied = autofix.apply(path, autofix.plan(path, hits))
        check('line 1 of a BOM file is fixed', len(applied) == 1,
              [f.to_dict() for f in applied])
        check('and keeps its BOM', read(path, 'app/Svc/B.php') == '﻿<?php $n = (int)$v;\n',
              repr(read(path, 'app/Svc/B.php')))


def case_bytes_are_respected():
    """R16 / CYC s7: a file auto-fix cannot read is left alone without killing
    the Stop, and a fix keeps every line ending it did not touch."""
    print('case_bytes_are_respected:')
    with tempdir() as tmp:
        path = repo(tmp)
        s = Session(path, os.path.join(tmp, 'data'), 'bytes')
        legacy = ('<?php\n// \uc124\uba85\n$n = ( int )$v;\n').encode('cp949')
        with open(os.path.join(path, 'app/Svc/K.php'), 'wb') as fh:
            fh.write(legacy)
        s.touch('app/Svc/K.php')
        out = s.stop('p1')
        check('a non-UTF-8 file does not kill the Stop', '내부 오류' not in out['summary'], out)
        with open(os.path.join(path, 'app/Svc/K.php'), 'rb') as fh:
            check('and is never written', fh.read() == legacy)

        mixed = (HDR + 'class M\n{\n    public function f($v)\n    {\n'
                 '        $n = ( int )$v;\n        return $n;\n    }\n}\n')
        mixed = mixed.replace('\n', '\r\n', 3).encode('utf-8')     # CRLF on the first 3 lines only
        with open(os.path.join(path, 'app/Svc/M.php'), 'wb') as fh:
            fh.write(mixed)
        rules = [r for r in rulelib.load(path, ROOT, {'presets': 'auto'}, {'php'}).rules
                 if r.get('fix')]
        hits = detect.run(rules, ChangeScope.files(path, ['app/Svc/M.php']),
                          rulelib.Reach(detect.Stacks({'php'})), 10)
        applied = autofix.apply(path, autofix.plan(path, hits))
        with open(os.path.join(path, 'app/Svc/M.php'), 'rb') as fh:
            after = fh.read()
        check('the fix is applied', len(applied) == 1 and b'(int)$v' in after, applied)
        check('and every other byte, line endings too, is as it was',
              after == mixed.replace(b'( int )$v', b'(int)$v'), after[:80])


def case_scan_fix():
    print('case_scan_fix:')
    with tempdir() as tmp:
        path = repo(tmp, mode='fix')
        write(path, 'app/Svc/A.php', new_file())
        env = isolated_env(os.path.join(tmp, 'data'))
        dry = run_script('scan.py', ['--cwd', path, '--no-lint', '--fix', '--json',
                                     '--fail-on', 'warn'], env=env, cwd=path)
        report = json.loads(dry.stdout)
        check('--fix lists the fixes', len(report['fixes']) == 2, report)
        check('--fix alone does not write', read(path, 'app/Svc/A.php') == new_file())
        check('and the gate still fails', dry.returncode == 1, dry.returncode)

        wet = run_script('scan.py', ['--cwd', path, '--no-lint', '--fix', '--write', '--json',
                                     '--fail-on', 'warn'], env=env, cwd=path)
        report = json.loads(wet.stdout)
        check('--fix --write applies', report['fixes_applied']
              and '(int)$v' in read(path, 'app/Svc/A.php'), report)
        check('the report shows what is left (nothing)', report['findings'] == [],
              report['findings'])
        check('and the gate passes', wet.returncode == 0, wet.returncode)
        bad = run_script('scan.py', ['--cwd', path, '--write'], env=env, cwd=path)
        check('--write without --fix is refused', bad.returncode == 2, bad.stderr)


if __name__ == '__main__':
    case_hook_fixes_what_it_can()
    case_only_fixable_passes()
    case_fix_mode_does_not_edit()
    case_stale_line_and_crlf()
    case_bom_first_line()
    case_bytes_are_respected()
    case_scan_fix()
    sys.exit(finish('자동 수정'))
