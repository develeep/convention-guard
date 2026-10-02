#!/usr/bin/env python3
"""The Stop hook's verification cycle, end to end through the real scripts.

    block -> fix -> re-scan -> verify

Each case drives collect.py / check.py turn by turn the way Claude Code does:
a new request arrives with stop_hook_active=false, the continuation after our
own block arrives with stop_hook_active=true.

Carried over from 0.x regressions:
- a long session must not go silent after a couple of blocks (cap is per
  consecutive block, and a clean turn resets it; a capped turn does not)
- one block must be measured once, not on every later turn
- report mode must never log a finding as shown
- a finding declined as a false positive is "dismissed", never "not fixed",
  and does not spend the rule's once-per-session budget
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, Session, check, commit, finish, git,  # noqa: E402
                     make_repo, run_script, store_rows, tempdir, write)
from lib import structure  # noqa: E402
from lib.candidate import clip, fingerprint  # noqa: E402

HDR = '<?php\ndeclare(strict_types=1);\nnamespace App;\n'
A = 'app/Svc/A.php'


def repo_files(config=''):
    files = {'composer.json': LARAVEL_COMPOSER}
    for name in ('A', 'B'):
        files['app/Svc/%s.php' % name] = \
            HDR + 'class %s { public function f() { return 1; } }\n' % name
    files['.claude/convention-guard/config.yaml'] = (
        config if 'mode:' in config else 'mode: fix\n' + config)
    return files


def body(code='dd(1);', cls='A'):
    return HDR + 'class %s { public function f() { %s } }\n' % (cls, code)


def outcomes(session):
    return sorted(e['outcome'] for e in session.events('verify'))


# ---------------------------------------------------------------- cases

def case_fixed_passes(repo, data):
    s = Session(repo, data, 'fixed')
    first = s.turn(A, body(), 'p1')
    check('a new error blocks', first['decision'] == 'block', first)
    check('the reason names the dismissal command', 'dismiss.py' in first['reason'])
    check('a cycle is open', s.state()['cycle'] is not None, s.state())

    done = s.turn(A, body('return 2;'), 'p1', stop_hook_active=True)
    check('after the fix the turn passes', done['decision'] is None, done)
    check('and the user sees the cycle close',
          done['summary'] == 'convention-guard ✔ 재검증 통과 — 고쳐짐 1 · 기각 0', done['summary'])
    check('the outcome is logged once as fixed', outcomes(s) == ['fixed'], s.events('verify'))
    check('the cycle is closed and the streak reset',
          s.state()['cycle'] is None and s.state()['consecutive_blocks'] == 0, s.state())

    later = s.turn(A, body('dd(3);'), 'p2')
    check('once_per_session keeps a fixed rule quiet in later requests',
          later['decision'] is None, later)
    check('no further verification is logged', outcomes(s) == ['fixed'], s.events('verify'))


def case_still_blocks_once_more(repo, data):
    s = Session(repo, data, 'still')
    s.turn(A, body(), 'p1')
    s.touch(A)
    again = s.stop('p1', stop_hook_active=True)
    check('an ignored finding blocks once more', again['decision'] == 'block', again)
    check('the verify reason says it is still there', '■ 남음' in again['reason'],
          again['reason'])
    check('and that this is the last chance', '마지막 재검증' in again['reason'])

    s.touch(A)
    last = s.stop('p1', stop_hook_active=True)
    check('after the verify attempts it stops blocking', last['decision'] is None, last)
    check('but reports what is left', '남음 1' in last['summary'], last['summary'])
    check('the cycle closed', s.state()['cycle'] is None)

    nxt = s.turn(A, body(), 'p2')
    check('an unfixed finding comes back in the next request', nxt['decision'] == 'block', nxt)
    check('marked as raised before', '지난 턴에도 지적했습니다' in nxt['reason'], nxt['reason'][:300])


def case_new_violation_from_fix(repo, data):
    s = Session(repo, data, 'newfix')
    s.turn(A, body('dd(1);'), 'p1')
    fixed = s.turn(A, body('var_dump(1);'), 'p1', stop_hook_active=True)
    check('a violation introduced by the fix blocks', fixed['decision'] == 'block', fixed)
    check('it is called out as new', '■ 새로 생김' in fixed['reason'], fixed['reason'])
    check('the original is logged fixed and the replacement new',
          outcomes(s) == ['fixed', 'new'], s.events('verify'))


def case_settled_rule_can_come_back(repo, data):
    """once_per_session used to filter the re-scan itself, not just the report.

    Every other cycle case turns it off, so nothing covered what happens when
    a later fix re-introduces a rule the session had already settled: the
    verification could not see it, and reported the cycle as clean.
    """
    s = Session(repo, data, 'settled')
    s.turn(A, body('dd(1);'), 'p1')
    done = s.turn(A, body('return 1;'), 'p1', stop_hook_active=True)
    check('the first rule is settled for the session', done['decision'] is None, done)

    second = s.turn(A, body("$password = 'p@ssw0rd-prod-1'; return 1;"), 'p2')
    check('a different rule opens a new cycle', second['decision'] == 'block', second)

    back = s.turn(A, body('dd(1);'), 'p2', stop_hook_active=True)
    check('a settled rule the fix brought back is still seen',
          back['decision'] == 'block', back)
    check('and it is reported as new', '■ 새로 생김' in back['reason'], back['reason'])


def case_over_budget_is_not_new(repo, data):
    s = Session(repo, data, 'budget')
    lines = HDR + 'class A {\n' + '\n'.join(
        '    public function f%d() { dd(%d); }' % (i, i) for i in range(6)) + '\n}\n'
    first = s.turn(A, lines, 'p1')
    check('the first block shows only the per-rule budget',
          first['reason'].count('dd(') == 3, first['reason'])
    fixed_three = HDR + 'class A {\n' + '\n'.join(
        '    public function f%d() { %s }' % (i, 'return 1;' if i < 3 else 'dd(%d);' % i)
        for i in range(6)) + '\n}\n'
    verify = s.turn(A, fixed_three, 'p1', stop_hook_active=True)
    check('candidates that existed but were not shown are not "new"',
          'new' not in outcomes(s), s.events('verify'))
    check('with the shown ones fixed the turn passes', verify['decision'] is None, verify)


def case_dismissed_in_cycle(repo, data):
    s = Session(repo, data, 'dismiss')
    first = s.turn(A, body(), 'p1')
    check('the finding blocks first', first['decision'] == 'block', first)
    proc = run_script('dismiss.py', ['--rule', 'core/php-no-debug-output', '--file', A,
                                     '--line', '4', '--reason', '일회성 디버그 도구라 예외'],
                      env=s.env, cwd=repo)
    check('dismiss.py succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    s.touch(A)
    verify = s.stop('p1', stop_hook_active=True)
    check('a dismissed finding does not block', verify['decision'] is None, verify)
    check('it is logged as dismissed, not unfixed', outcomes(s) == ['dismissed'],
          s.events('verify'))

    changed = s.turn(A, body('dd(1); dd(2);'), 'p2')
    check('changed code is judged again (the budget was not spent)',
          changed['decision'] == 'block', changed)


def case_abandoned_request(repo, data):
    s = Session(repo, data, 'abandon')
    s.turn(A, body(), 'p1')
    # the user interrupts and sends something else; the old finding is still there
    other = s.turn('app/Svc/B.php', body('return 3;', 'B'), 'p2')
    check('the old cycle is closed as abandoned',
          [e for e in s.events('abandoned')], s.events())
    check('its outcome is still measured', outcomes(s) == ['still'], s.events('verify'))
    check('the unfixed finding is raised again for the new request',
          other['decision'] == 'block', other)


def case_new_occurrence_is_not_a_repeat(repo, data):
    s = Session(repo, data, 'newloc')
    s.turn(A, body(), 'n1')
    s.turn(A, body('return 1;'), 'n1', stop_hook_active=True)
    third = s.turn('app/Svc/B.php', body('dd(2);', 'B'), 'n2')
    check('the same rule in another file is reported', third['decision'] == 'block', third)
    check('it is not labelled as a repeat', '지난 턴에 지적했는데' not in third['reason'])


def case_consecutive_cap(repo, data):
    """The cap is a loop guard inside one request (R4): continuations of the
    same request stop blocking at the cap."""
    s = Session(repo, data, 'cap')
    results = [s.turn(A, body('dd(1);'), 'q0')]
    for _ in range(3):
        s.touch(A)
        results.append(s.stop('q0', stop_hook_active=True))
    blocked = [r['decision'] == 'block' for r in results]
    check('blocks up to the consecutive cap', blocked == [True, True, True, False], blocked)
    # the verify path words it as the end of verification, not as the cap
    check('the held-back finding is still reported', '남음 1' in results[3]['summary'],
          results[3]['summary'])
    s.turn(A, body('return 1;'), 'q9')
    check('a clean turn resets the streak', s.state()['consecutive_blocks'] == 0, s.state())
    again = s.turn(A, body('dd(9);'), 'q10')
    check('the checker is alive later in the session', again['decision'] == 'block', again)


def case_cap_does_not_cross_requests(repo, data):
    """R4 / CYC s5: an error left alone in one request must not use up the
    next request's blocks."""
    s = Session(repo, data, 'cap-requests')
    s.turn(A, body('dd(1);'), 'p1')
    s.touch(A)
    s.stop('p1', stop_hook_active=True)                 # ignored, streak 2
    s.turn(A, body('dd(1);'), 'p2')                     # same error, new request
    s.touch(A)
    s.stop('p2', stop_hook_active=True)
    fresh = s.turn('app/Svc/B.php', body('var_dump(2);', 'B'), 'p3')
    check("a new request's new error blocks", fresh['decision'] == 'block', fresh)
    check('the streak counts this request only', s.state()['consecutive_blocks'] == 1,
          s.state().get('consecutive_blocks'))


def case_report_mode(repo, data):
    s = Session(repo, data, 'report', CLAUDE_PLUGIN_OPTION_REPORT_ONLY='true')
    result = s.turn(A, body(), 'r1')
    check('report mode does not block', result['decision'] is None, result)
    check('report mode says so', 'report' in result['summary'], result['summary'])
    cands = s.events('candidate')
    check('candidates are logged', len(cands) >= 1, s.events())
    check('nothing is logged as shown', all(not c['shown'] for c in cands), cands)


def case_question_turn(repo, data):
    s = Session(repo, data, 'question')
    result = s.turn(A, body(), 'p1', message='이 방식으로 진행할까요?')
    check('a turn ending in a question is not checked', result['decision'] is None, result)
    check('and no cycle is opened', s.state()['cycle'] is None)


def case_commit_before_first_stop(repo, data):
    s = Session(repo, data, 'commit-first')
    # the edit, then a commit before the Stop hook gets its first chance:
    # the ledger follows content, so committing changes nothing it knows
    s.edit(A, body())
    commit(repo, 'agent commit')
    result = s.stop('p1')
    check('a change committed before Stop is still inspected',
          result['decision'] == 'block', result)


def case_commit_during_open_cycle(repo, data):
    s = Session(repo, data, 'commit-cycle')
    first = s.turn(A, body(), 'p1')
    check('the violation opens a cycle before commit', first['decision'] == 'block', first)
    commit(repo, 'commit unresolved violation')
    s.touch(A)
    verify = s.stop('p1', stop_hook_active=True)
    check('committing an unresolved violation does not classify it as fixed',
          verify['decision'] == 'block' and '■ 남음' in verify['reason'], verify)


def case_no_prompt_ids(repo, data):
    """Claude Code does not always send prompt ids; continuation alone must work."""
    s = Session(repo, data, 'noprompt')
    first = s.turn(A, body(), None)
    check('blocks without a prompt id', first['decision'] == 'block', first)
    done = s.turn(A, body('return 1;'), None, stop_hook_active=True)
    check('verifies without a prompt id', done['decision'] is None and outcomes(s) == ['fixed'],
          (done, s.events('verify')))
    s.touch(A)
    extra = s.stop(None, stop_hook_active=True)
    check('another hook continuing the same request does not reopen a cycle',
          extra['decision'] is None and s.state()['cycle'] is None, extra)


def case_deletion_only_turn(repo, data):
    """R19 -- a turn that only deletes lines is checked: emptying a legacy
    catch is this change's doing."""
    rel = 'app/Svc/C.php'
    catch = (HDR + 'class C { public function f() {\n    try { go(); } catch (\\Throwable $e) {\n'
             '%s    }\n} }\n')
    write(repo, rel, catch % '        report($e);\n')
    commit(repo, 'legacy catch')
    s = Session(repo, data, 'deletion')
    result = s.turn(rel, catch % '', 'p1')
    if structure.engine().ok:
        check('the emptied catch is reported', 'warn 1' in (result.get('summary') or ''), result)
    else:
        # where the block ends is unknown without the engine: named, not passed
        check('without the engine the file is named instead',
              '구조 엔진 없음' in (result.get('summary') or ''), result)


def case_too_large_is_said(repo, data):
    """R20 -- a file too big to check is named, never a silent pass."""
    s = Session(repo, data, 'big')
    result = s.turn('app/Svc/Big.php', body() + '// pad\n' * 60000, 'p1')
    check('the hook says it skipped the file',
          '큰 파일 미검사 1개 파일 (app/Svc/Big.php)' in (result.get('summary') or ''), result)


def case_empty_repo_commit(_repo, data):
    """R14 -- in a repo with no commits yet, committing mid-session must not
    make the change vanish (COL R14)."""
    with tempdir() as fresh:
        git(fresh, 'init', '-q')
        git(fresh, 'config', 'user.email', 't@t')
        git(fresh, 'config', 'user.name', 't')
        write(fresh, 'composer.json', LARAVEL_COMPOSER)
        write(fresh, '.claude/convention-guard/config.yaml', 'mode: fix\n')
        s = Session(fresh, data, 'empty')
        s.edit(A, body())
        commit(fresh, 'first')
        result = s.stop('p1')
        check('the committed violation still blocks', result['decision'] == 'block', result)


def case_nested_repo_file_is_checked(repo, data):
    """A file inside the work tree that another (nested) repository owns: git
    cannot see it from here, but the ledger watched the agent write it."""
    os.makedirs(os.path.join(repo, 'vendor-src'))
    git(os.path.join(repo, 'vendor-src'), 'init', '-q')
    s = Session(repo, data, 'nested')
    result = s.turn('vendor-src/x.php', body(), 'p1')
    check('what the agent wrote there is checked', result['decision'] == 'block', result)


# ---------------------------------------------------------------- who wrote it (R12)

def method_file(*lines):
    """A with one method whose body is `lines`, one statement per line."""
    return HDR + 'class A {\n    public function f()\n    {\n' + ''.join(
        '        %s\n' % line for line in lines) + '    }\n}\n'


def case_human_lines_are_not_the_agents(repo, data):
    # uncommitted work the human left before the session started
    write(repo, A, method_file('dd($human);', 'return 1;'))
    s = Session(repo, data, 'human-first')
    s.edit(A, method_file('dd($human);', 'return 2;'))
    quiet = s.stop('p1')
    check("the human's line in a file the agent edited is not its violation",
          quiet['decision'] is None, quiet)

    s.edit(A, method_file('dd($human);', 'dd($agent);', 'return 2;'))
    loud = s.stop('p2')
    check("the agent's own line in that file still blocks",
          loud['decision'] == 'block' and 'dd($agent)' in loud['reason'], loud)
    check("and the human's line is not listed next to it",
          'dd($human)' not in loud['reason'], loud['reason'])


def case_same_line_twice_is_counted(repo, data):
    write(repo, A, method_file('dd($x);', 'return 1;'))
    s = Session(repo, data, 'counted')
    s.edit(A, method_file('dd($x);', 'dd($x);', 'return 1;'))
    out = s.stop('p1')
    check('a copy of a human line the agent writes is still checked',
          out['decision'] == 'block' and out['reason'].count('dd($x)') == 1, out)


def case_bash_keeps_human_lines_out(repo, data):
    write(repo, A, method_file('dd($human);', 'return 1;'))
    s = Session(repo, data, 'bash-human')
    s.bash_hook('PreToolUse')
    write(repo, A, method_file('dd($human);', 'dd($agent);', 'return 1;'))
    s.bash_hook('PostToolUse')
    out = s.stop('p1')
    check('a Bash change to a human-dirty file blocks on the agent line only',
          out['decision'] == 'block' and 'dd($agent)' in out['reason']
          and 'dd($human)' not in out['reason'], out)


def case_pulled_commits_are_not_the_agents(repo, data):
    with tempdir() as other:
        git(other, 'clone', '-q', repo, other)
        git(other, 'config', 'user.email', 'mate@t')
        git(other, 'config', 'user.name', 'mate')
        write(other, 'app/Svc/B.php', body('dd($mate);', 'B'))
        git(other, 'add', '-A')
        subprocess.run(['git', '-C', other, 'commit', '-qm', 'teammate'], check=True,
                       env=dict(os.environ, GIT_COMMITTER_DATE='2020-01-01T00:00:00'))
        s = Session(repo, data, 'pull')
        s.bash_hook('PreToolUse')
        git(repo, 'pull', '-q', other, 'HEAD')
        s.bash_hook('PostToolUse')
        pulled = s.stop('p1')
    check("a teammate's commit pulled through Bash does not block the agent",
          pulled['decision'] is None, pulled)

    s.edit('app/Svc/B.php', body('dd($mate); dd($agent);', 'B'))
    mine = s.stop('p2')
    check('editing that file afterwards still checks what the agent wrote',
          mine['decision'] == 'block' and 'dd($agent)' in mine['reason'], mine)


def case_agent_commit_in_bash_is_still_checked(repo, data):
    s = Session(repo, data, 'bash-commit')
    s.bash_hook('PreToolUse')
    write(repo, A, method_file('dd($agent);', 'return 1;'))
    commit(repo, 'agent commits in the same call')
    s.bash_hook('PostToolUse')
    out = s.stop('p1')
    check('a change the agent commits inside one Bash call is still its own',
          out['decision'] == 'block' and 'dd($agent)' in out['reason'], out)


def case_other_terminal_commit(repo, data):
    """COL R2: the human commits b.php elsewhere mid-session; the agent's next
    Bash call (`ls`) must not take it -- Pre and Post now share the session base."""
    s = Session(repo, data, 'other-terminal')
    s.edit(A, body('return 1;'))
    write(repo, 'app/Svc/B.php', body('dd($human);', 'B'))
    commit(repo, 'human, another terminal')
    s.bash_hook('PreToolUse')
    s.bash_hook('PostToolUse')          # `ls`: changes nothing
    out = s.stop('p1')
    check("the human's commit is not the agent's", out['decision'] is None, out)


# ---------------------------------------------------------------- collection gaps (R23c-e)

def case_base_outlives_a_week(repo, data):
    """R23c -- a live session's base is refreshed, so the 7-day GC keeps it."""
    import time
    s = Session(repo, data, 'week')
    import sqlite3
    s.edit(A, body('return 1;'))
    old = time.time() - 8 * 86400
    conn = sqlite3.connect(os.path.join(data, 'convention-guard.db'))
    conn.execute('UPDATE session_seen SET updated = ? WHERE session = ?', (old, 'week'))
    conn.commit()
    conn.close()
    s.edit(A, body('return 2;'))
    seen = store_rows(data, 'SELECT updated FROM session_seen WHERE session = ?', ('week',))
    check('touching the session refreshes it', seen and seen[0][0] > old + 86400, seen)
    s.stop('p1')
    check('so the 7-day GC keeps its ledger',
          store_rows(data, 'SELECT path FROM ledger_file WHERE session = ?', ('week',)) != [])


def case_bash_without_pre_is_said(repo, data):
    """R23d -- a Bash call whose Pre never ran is not a silent pass."""
    s = Session(repo, data, 'nopre')
    write(repo, A, body())
    s.bash_hook('PostToolUse')
    out = s.stop('p1')
    check('the Stop says a call was seen only after it ran',
          '관찰 누락 1개 파일 — 실행 전 기록 없음 (app/Svc/A.php' in (out.get('summary') or ''),
          out)
    check('and checks what changed as the agent\'s', out['decision'] == 'block', out)
    again = s.stop('p2')
    check('once', '관찰 누락' not in (again.get('summary') or ''), again)


def case_any_mcp_tool_is_watched(repo, data):
    """D5 -- an MCP tool that writes files is watched like Bash, whatever its
    name; one that writes nothing costs nothing."""
    s = Session(repo, data, 'mcp')
    s.bash_hook('PreToolUse', tool='mcp__fs__write_file')
    write(repo, A, body())
    s.bash_hook('PostToolUse', tool='mcp__fs__write_file')
    out = s.stop('p1')
    check('its write is checked', out['decision'] == 'block', out)
    s2 = Session(repo, data, 'mcp-read')
    write(repo, 'app/Svc/B.php', body(cls='B'))      # a person's work, before the call
    s2.bash_hook('PreToolUse', tool='mcp__fs__read_file')
    s2.bash_hook('PostToolUse', tool='mcp__fs__read_file')
    check('a tool that changes nothing is not', s2.stop('p1')['decision'] is None)


# ---------------------------------------------------------------- display budget (R3)

DD = 'core/php-no-debug-output'


def case_hidden_finding_is_not_a_pass(repo, data):
    """CYC s1c: fixing only what was shown must not read as a pass, and the
    rest must come back -- not stay silent for the session."""
    s = Session(repo, data, 'hidden')
    first = s.turn(A, method_file('dd(1);', 'dd(2);'), 'p1')
    check('the block says one more is not shown', '… 1곳 더' in first['reason'],
          first['reason'][:500])
    done = s.turn(A, method_file('return 1;', 'dd(2);'), 'p1', stop_hook_active=True)
    check('fixing the shown one is not "재검증 통과"',
          '재검증 통과' not in done['summary'] and '미표시 1' in done['summary'], done)
    check('and the rule is not settled for the session',
          DD not in (s.state().get('fired_rules') or []), s.state().get('fired_rules'))
    nxt = s.turn(A, method_file('return 1;', 'dd(2);'), 'p2')
    check('the hidden one blocks in the next request', nxt['decision'] == 'block'
          and 'dd(2)' in nxt['reason'] and '지난 턴에도' in nxt['reason'], nxt['reason'][:400])


def case_hidden_rules_are_counted(repo, data):
    """CYC s1: a rule past max_error_rules is named as a count in the block."""
    s = Session(repo, data, 'hidden-rules')
    first = s.turn(A, method_file('dd(1);', "$k = env('X');"), 'p1')
    check('the block counts the rule it did not show', '… 1개 규칙 더' in first['reason'],
          first['reason'][:600])


def case_verify_cap_is_not_new(repo, data):
    """C6 / CYC s8: past VERIFY_CAP, candidates that come into view after a fix
    are not "new" -- they were there all along."""
    s = Session(repo, data, 'verify-cap')
    lines = ['dd(%d);' % i for i in range(55)]
    s.turn(A, method_file(*lines), 'p1')
    s.turn(A, method_file(*(['return 0;'] * 3 + lines[3:])), 'p1', stop_hook_active=True)
    check('nothing is called new', 'new' not in outcomes(s), outcomes(s))


def case_reformat_and_move_are_still(repo, data):
    """R23f / CYC s4: a violation reformatted in place, or moved to another
    file, is the same violation -- still, not fixed plus new."""
    s = Session(repo, data, 'reformat')
    s.turn(A, method_file('dd($x);', 'return 1;'), 'p1')
    again = s.turn(A, method_file('dd( $x );', 'return 1;'), 'p1', stop_hook_active=True)
    check('reformatted in place is still', outcomes(s) == ['still'], s.events('verify'))
    check('and still blocks', again['decision'] == 'block', again)

    t = Session(repo, data, 'move')
    t.turn(A, method_file('dd($x);', 'return 1;'), 'q1')
    write(repo, A, method_file('return 1;'))
    t.touch(A)
    moved = HDR + 'class B {\n    public function g()\n    {\n        dd($x);\n    }\n}\n'
    t.turn('app/Svc/B.php', moved, 'q1', stop_hook_active=True)
    verify = sorted(e['outcome'] for e in t.events('verify') if e.get('cycle')
                    and e['cycle'] != s.events('verify')[0]['cycle'])
    check('moved to another file is still', verify == ['still'], t.events('verify'))


CASES = [
    (case_fixed_passes, ''),
    (case_still_blocks_once_more, 'once_per_session: false\n'),
    (case_new_violation_from_fix, 'once_per_session: false\n'),
    (case_settled_rule_can_come_back, ''),
    (case_over_budget_is_not_new, ''),
    (case_dismissed_in_cycle, ''),
    (case_abandoned_request, 'once_per_session: false\n'),
    (case_new_occurrence_is_not_a_repeat, 'once_per_session: false\n'),
    (case_consecutive_cap, 'once_per_session: false\nlimits:\n  max_verify_attempts: 5\n'),
    (case_cap_does_not_cross_requests, 'once_per_session: false\n'),
    (case_report_mode, 'mode: report\n'),
    (case_question_turn, ''),
    (case_commit_before_first_stop, 'once_per_session: false\n'),
    (case_commit_during_open_cycle, 'once_per_session: false\n'),
    (case_no_prompt_ids, ''),
    (case_deletion_only_turn, ''),
    (case_too_large_is_said, ''),
    (case_empty_repo_commit, ''),
    (case_nested_repo_file_is_checked, ''),
    (case_human_lines_are_not_the_agents, 'once_per_session: false\n'),
    (case_same_line_twice_is_counted, ''),
    (case_bash_keeps_human_lines_out, ''),
    (case_pulled_commits_are_not_the_agents, 'once_per_session: false\n'),
    (case_agent_commit_in_bash_is_still_checked, ''),
    (case_other_terminal_commit, ''),
    (case_base_outlives_a_week, ''),
    (case_bash_without_pre_is_said, ''),
    (case_any_mcp_tool_is_watched, ''),
    (case_hidden_finding_is_not_a_pass, 'limits:\n  max_locations_per_rule: 1\n'),
    (case_hidden_rules_are_counted, 'limits:\n  max_error_rules: 1\n'),
    (case_verify_cap_is_not_new, 'once_per_session: false\n'),
    (case_reformat_and_move_are_still, 'once_per_session: false\n'),
]


def main():
    for case, config in CASES:
        print('%s:' % case.__name__)
        with tempdir() as repo, tempdir() as data:
            make_repo(repo, repo_files(config))
            case(repo, data)
    return finish('Stop 훅 검증 사이클')


if __name__ == '__main__':
    sys.exit(main())
