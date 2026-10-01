#!/usr/bin/env python3
"""The edit ledger end to end: who wrote a line, and every gap in seeing it.

One case per row of docs/design-4.0.md §1.8 and §2, driven through the real
collect.py and check.py the way Claude Code calls them:

- a person's edit between the agent's calls is not checked, and is named
- a Bash call's change is the agent's; a file it only moved is not written
- a Pre with no Post, a Post with no Pre: checked as the agent's, and named
- a call that never ran (denied) leaves nothing to say
- a write outside every call is named, not checked
- parallel calls, a failed call, a collect hook that broke, a path outside
  the work tree
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, commit, finish, make_repo,  # noqa: E402
                     tempdir, write)

HDR = '<?php\ndeclare(strict_types=1);\nnamespace App;\n'
A = 'app/Svc/A.php'
B = 'app/Svc/B.php'


def methods(*lines, cls='A'):
    """A class with one method whose body is `lines`, one statement per line."""
    return (HDR + 'class %s {\n    public function f()\n    {\n' % cls
            + ''.join('        %s\n' % line for line in lines) + '    }\n}\n')


def repo_files():
    return {'composer.json': LARAVEL_COMPOSER, A: methods('return 1;'),
            B: methods('return 1;', cls='B'),
            '.claude/convention-guard/config.yaml': 'mode: fix\nonce_per_session: false\n'}


def case_person_between_calls(repo, data):
    s = Session(repo, data, 'person')
    s.edit(A, methods('$a = 1;'))
    write(repo, A, methods('$a = 1;', 'dd($human);'))           # the person, in an editor
    s.edit(A, methods('$a = 1;', 'dd($human);', '$b = 2;'))
    out = s.stop('p1')
    check("a person's line in a file the agent is editing is not checked",
          out['decision'] is None, out)
    check('and it is named', '출처 미확인 변경 1개 파일' in out['summary']
          and A in out['summary'], out['summary'])
    s.edit(A, methods('$a = 1;', 'dd($human);', '$b = 2;', 'dd($agent);'))
    out = s.stop('p2')
    check("the agent's own line next to it blocks", out['decision'] == 'block'
          and 'dd($agent)' in out['reason'] and 'dd($human)' not in out['reason'], out)


def case_person_elsewhere(repo, data):
    s = Session(repo, data, 'elsewhere')
    s.edit(A, methods('$a = 1;'))
    write(repo, B, methods('dd($human);', cls='B'))               # never part of any call
    out = s.stop('p1')
    check("a file only a person changed is not checked", out['decision'] is None, out)
    check('but named', '출처 미확인 변경 1개 파일' in out['summary'] and B in out['summary'],
          out['summary'])
    again = s.stop('p2')
    check('once', '출처 미확인' not in again['summary'], again['summary'])


def case_bash_writes(repo, data):
    s = Session(repo, data, 'sed')
    s.bash_hook('PreToolUse')
    write(repo, A, methods('dd($agent);'))                        # `sed -i` and the like
    s.bash_hook('PostToolUse')
    out = s.stop('p1')
    check('what a Bash call wrote is checked', out['decision'] == 'block'
          and 'dd($agent)' in out['reason'], out)


def case_moved_file(repo, data):
    legacy = methods('dd($legacy);', cls='Old').replace('declare(strict_types=1);\n', '')
    write(repo, 'app/Svc/Old.php', legacy)
    commit(repo, 'legacy')
    s = Session(repo, data, 'mv')
    s.bash_hook('PreToolUse')
    os.rename(os.path.join(repo, 'app/Svc/Old.php'), os.path.join(repo, 'app/Svc/Moved.php'))
    s.bash_hook('PostToolUse')
    out = s.stop('p1')
    check('moving a file writes none of it', out['decision'] is None, out)
    check('not even as a new file', 'strict' not in (out['summary'] + out['reason']), out)
    s.edit('app/Svc/Moved.php', legacy.replace('dd($legacy);', 'dd($legacy);\n        dd($new);'))
    out = s.stop('p2')
    check('its next edit is checked alone', out['decision'] == 'block'
          and 'dd($new)' in out['reason'] and 'dd($legacy)' not in out['reason'], out)


def case_post_without_pre(repo, data):
    s = Session(repo, data, 'nopre')
    write(repo, A, methods('dd($agent);'))
    s.touch(A)
    out = s.stop('p1')
    check('a Post with no Pre is checked as the agent\'s', out['decision'] == 'block', out)
    check('and named', '관찰 누락 1개 파일 — 실행 전 기록 없음' in out['summary'], out['summary'])


def case_pre_without_post(repo, data):
    s = Session(repo, data, 'nopost')
    s.pre(A)
    write(repo, A, methods('dd($agent);'))                        # the Post hook died
    out = s.stop('p1')
    check('a Pre with no Post: what changed is checked', out['decision'] == 'block', out)
    check('and named', '관찰 누락 1개 파일 — 실행 후 기록 없음' in out['summary'], out['summary'])


def case_denied_call(repo, data):
    s = Session(repo, data, 'denied')
    s.pre(A)                                                       # never ran
    out = s.stop('p1')
    check('a call that changed nothing leaves nothing to say',
          out['decision'] is None and out['summary'] == '', out)


def case_background_write(repo, data):
    s = Session(repo, data, 'background')
    s.bash_hook('PreToolUse')
    s.bash_hook('PostToolUse')                                     # `npm run dev &`
    write(repo, 'app/Svc/C.php', methods('dd($later);', cls='C'))  # written after the call
    out = s.stop('p1')
    check('a write after every call is not the agent\'s', out['decision'] is None, out)
    check('and is named', '출처 미확인 변경 1개 파일' in out['summary']
          and 'app/Svc/C.php' in out['summary'], out['summary'])


def case_parallel_calls(repo, data):
    s = Session(repo, data, 'parallel')
    s.pre(A)
    s.bash_hook('PreToolUse', tool_use_id='bash-p')
    write(repo, A, methods('dd($edit);'))
    write(repo, B, methods('dd($bash);', cls='B'))
    s.touch(A)
    s.bash_hook('PostToolUse', tool_use_id='bash-p')
    out = s.stop('p1')
    check('two overlapping calls: both are checked', out['decision'] == 'block'
          and 'dd($edit)' in out['reason'] and 'dd($bash)' in out['reason'], out)
    check('and nothing is called a gap', '관찰 누락' not in out['summary'], out['summary'])


def case_failed_call(repo, data):
    s = Session(repo, data, 'failed')
    s.bash_hook('PreToolUse')
    write(repo, A, methods('dd($half);'))                          # wrote, then exited 1
    s.bash_hook('PostToolUseFailure')
    out = s.stop('p1')
    check('a failed call still changed the file: checked', out['decision'] == 'block', out)
    check('without calling it a gap', '관찰 누락' not in out['summary'], out['summary'])


def case_collect_error(repo, data):
    from lib import ledger, store
    old = os.environ.get('CLAUDE_PLUGIN_DATA')
    os.environ['CLAUDE_PLUGIN_DATA'] = data
    try:
        ledger.record_failure({'session_id': 'broken'}, 'internal_error:OSError')
        store.close_all()
    finally:
        if old is None:
            os.environ.pop('CLAUDE_PLUGIN_DATA', None)
        else:
            os.environ['CLAUDE_PLUGIN_DATA'] = old
    s = Session(repo, data, 'broken')
    s.edit(A, methods('$a = 1;'))
    out = s.stop('p1')
    check('a collect hook that failed is said', '수집 훅 오류 1회 (internal_error:OSError)'
          in out['summary'], out['summary'])


def case_outside_root(repo, data):
    s = Session(repo, data, 'outside')
    elsewhere = os.path.join(data, 'elsewhere.php')
    s.edit(elsewhere, methods('dd($x);'))
    out = s.stop('p1')
    check('a file outside the work tree is named', '검사되지 않음 1개 파일 (레포 밖' in out['summary'],
          out['summary'])


def case_new_file_is_the_agents(repo, data):
    s = Session(repo, data, 'created')
    s.edit('app/Svc/N.php', '<?php\nnamespace App;\nclass N {}\n')
    out = s.stop('p1')
    check('a file the agent creates is held to new-file rules',
          'php-strict-types-required' in (out['reason'] + out['summary']), out)
    write(repo, 'app/Svc/H.php', '<?php\nnamespace App;\nclass H {}\n')   # a person's new file
    s.edit('app/Svc/H.php', '<?php\nnamespace App;\nclass H { public $x; }\n')
    out = s.stop('p2')
    check("one a person created is not, though the agent edits it",
          'app/Svc/H.php' not in out['reason'], out['reason'])


CASES = [case_person_between_calls, case_person_elsewhere, case_bash_writes, case_moved_file,
         case_post_without_pre, case_pre_without_post, case_denied_call, case_background_write,
         case_parallel_calls, case_failed_call, case_collect_error, case_outside_root,
         case_new_file_is_the_agents]


def main():
    for case in CASES:
        print('%s:' % case.__name__)
        with tempdir() as repo, tempdir() as data:
            make_repo(repo, repo_files())
            case(repo, data)
    return finish('편집 사건 원장')


if __name__ == '__main__':
    sys.exit(main())
