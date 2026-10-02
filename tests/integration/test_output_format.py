#!/usr/bin/env python3
"""Every output follows docs/output-format.md.

Each case builds a fixture, runs the real script, and checks the rules of the
spec (F1..F16) against what came out. The checks live in helpers/outfmt.py.

1. Stop hook: block, re-verify, notices, lint, semantic, auto-fix, clipping.
2. scan.py: text, empty result, --json, --fix, --review, stderr, colour.
3. review.py show / record / summary.
4. detect_stack.py, log_report.py, readiness.py, dismiss.py, setup.py.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, SCRIPTS, Session, check, finish,  # noqa: E402
                     isolated_env, make_repo, run_script, tempdir, write)
from helpers import outfmt  # noqa: E402
from helpers.fixtures import laravel_repo  # noqa: E402
from lib import report, structure  # noqa: E402
import test_autofix as taf  # noqa: E402
import test_semantic_review as tsr  # noqa: E402

HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Svc;\n\n'
A = 'app/Svc/A.php'


def body(code='dd(1);'):
    return HDR + 'class A\n{\n    public function f()\n    {\n        %s\n    }\n}\n' % code


def php_repo(tmp, config='mode: fix\n', name='repo'):
    repo = os.path.join(tmp, name)
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER, A: body('return 1;'),
                     '.claude/convention-guard/config.yaml': config})
    return repo


def ok(name, problems):
    check(name, not problems, '\n        ' + '\n        '.join(problems[:8]))


def run(script, args, env, cwd=None):
    return run_script(script, list(args), env=env, cwd=cwd)


# ---------------------------------------------------------------- 1. Stop hook

def reason_rules(name, result, first_line_is_summary=True):
    reason, message = result['reason'], result['summary']
    ok('%s: reason 공통 문법' % name, outfmt.text_output(reason))
    ok('%s: reason 머리말' % name, outfmt.hook_header(reason.split('\n', 1)[0]))
    ok('%s: systemMessage 머리말' % name, outfmt.hook_header(message))
    if first_line_is_summary:
        check('%s: systemMessage 는 reason 첫 줄로 시작 (D11)' % name,
              message.startswith(reason.split('\n', 1)[0]), repr((message, reason[:80])))
    check('%s: systemMessage 한 줄, 접두사 한 번' % name,
          '\n' not in message and message.count('convention-guard') == 1, repr(message))
    check('%s: reason 에 요약 줄 없음' % name, outfmt.summary(reason) != [], reason[-80:])
    ok('%s: 색 없음' % name, outfmt.no_color(reason + message))


def case_hook_block_and_verify(tmp):
    repo = php_repo(tmp)
    s = Session(repo, os.path.join(tmp, 'data'), 'blk')
    code = 'dd(1);\n        try { $x = 1; } catch (\\Exception $e) { }'
    first = s.turn(A, body(code), 'p1')
    reason_rules('차단', first)
    check('차단: 머리말 개수', re.match(r'^convention-guard ✖ 차단 — error \d+ · warn \d+', first['reason']),
          first['reason'][:80])
    titles = [t for t, _ in outfmt.sections(first['reason'])]
    check('차단: 섹션 순서', titles[:3] == ['지적 — 고치거나 기각하세요', '참고 — 차단하지 않습니다', '다음'],
          repr(titles))
    check('차단: 기각 명령은 다음 섹션의 $ 줄', outfmt.has_command(first['reason'], 'dismiss.py" --key '),
          first['reason'])
    again = s.turn(A, body(code), 'p1', stop_hook_active=True)
    reason_rules('재검증 차단', again)
    check('재검증: 용어 남음', re.match(r'^convention-guard ✖ 재검증 차단 — 고쳐짐 \d+ · 기각 \d+ · 남음 \d+ · '
                                    r'새로 생김 \d+', again['reason']), again['reason'][:90])
    check('재검증: ■ 남음 섹션', outfmt.section(again['reason'], '남음') is not None, again['reason'])
    done = s.turn(A, body('return 2;'), 'p1', stop_hook_active=True)
    check('재검증 통과: 알림 (§3)', done['summary'].startswith('convention-guard ✔ 재검증 통과 — 고쳐짐 '),
          repr(done['summary']))


def case_hook_notices(tmp):
    repo = php_repo(tmp)
    s = Session(repo, os.path.join(tmp, 'data'), 'warn')
    warn = s.turn(A, body('try { $x = 1; } catch (\\Exception $e) { }\n        return 1;'), 'p1')
    ok('warn 알림 머리말', outfmt.hook_header(warn['summary']))
    check('warn 알림 모양', warn['summary'].startswith('convention-guard ⚠ 기록 — warn 1 ('),
          repr(warn['summary']))
    repo = php_repo(tmp, 'mode: report\n', 'report')
    s = Session(repo, os.path.join(tmp, 'data-r'), 'rep')
    rec = s.turn(A, body(), 'p1')
    shape = 'convention-guard ✖ 기록 — error 1 · 차단 안 함: mode=report'
    if not structure.engine().ok:     # the condition could not be applied: said after it
        shape += ' · 구조 엔진 없음 (꺼짐) — 구조 미확인 1개 파일 (%s)' % A
    check('report 알림 모양', rec['summary'] == shape, repr(rec['summary']))
    repo = php_repo(tmp, 'mode: nope\n', 'bad')
    s = Session(repo, os.path.join(tmp, 'data-b'), 'bad')
    bad = s.turn(A, body(), 'p1')
    check('설정 오류 알림 모양', bad['summary'].startswith('convention-guard ✖ 건너뜀 — 설정 오류: '),
          repr(bad['summary']))
    broken = HDR + 'class A { public function f() { return 1; } }\n$a = "oops;\ndd(1);\n'
    repo = php_repo(tmp, 'mode: fix\nseverity:\n  core/php-no-debug-output: warn\n', 'unck')
    s = Session(repo, os.path.join(tmp, 'data-u'), 'unck')
    joined = s.turn(A, broken, 'p1')
    check('노트 결합: 접두사 한 번, · 로 이음',
          joined['summary'].count('convention-guard') == 1 and ' · 구조 ' in joined['summary']
          and '구조 미확인 1개 파일' in joined['summary'],
          repr(joined['summary']))


def lint_plugin(tmp, code):
    plug = os.path.join(tmp, 'plug')
    os.makedirs(os.path.join(plug, 'rules'), exist_ok=True)
    write(plug, 'config.yaml', 'mode: fix\n')
    write(plug, 'stacks/fake.yaml',
          'id: fake\ntags: [fake]\ndetect:\n  file: marker.txt\nlint:\n'
          '  - cmd: [%s, "-c", %s, "{files}"]\n    files: ["**/*.py"]\n    parse: unix\n'
          % (json.dumps(sys.executable), json.dumps(code)))
    return plug


def case_hook_lint(tmp):
    code = ('import sys\nfor i in range(30): print("src/a.py:20: problem %d" % i)\n'
            'print("src/a.py:3: legacy")\nsys.exit(1)')
    plug = lint_plugin(tmp, code)
    lines = ['line %d' % i for i in range(1, 31)]
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, {'marker.txt': 'fake\n', 'src/a.py': '\n'.join(lines) + '\n'})
    lines[19] = 'line 20 changed'
    write(repo, 'src/a.py', '\n'.join(lines) + '\n')
    s = Session(repo, os.path.join(tmp, 'data'), 'lint', plugin_root=plug)
    s.touch('src/a.py')
    first = s.stop('p1')
    reason_rules('린터 차단', first)
    lint = outfmt.section(first['reason'], '린터 실패') or []
    check('린터: 잘림 표시 … N줄 더 (F9)', any(re.match(r'^\s+… \d+줄 더', l) for l in lint), '\n'.join(lint))
    s.touch('src/a.py')
    again = s.stop('p1', stop_hook_active=True)
    nxt = '\n'.join(outfmt.section(again['reason'], '다음') or [])
    check('린터만 남은 재검증: 린터 문장, 기각 문장 없음',
          '린터 실패는 기각할 수 없습니다' in nxt and '기각으로 남기세요' not in nxt, nxt)


def case_hook_semantic(tmp):
    repo = os.path.join(tmp, 'repo')
    make_repo(repo, tsr.repo_files('mode: fix\npresets: [auto, performance, architecture]\n'
                                   'semantic_review:\n  enabled: true\n'))
    s = Session(repo, os.path.join(tmp, 'data'), 'sem')
    first = s.turn(tsr.CTRL, tsr.controller(), 'p1')
    reason_rules('판정 대기', first)
    check('판정 대기: 섹션', outfmt.section(first['reason'], '판정 대기') is not None, first['reason'])
    check('판정 대기: review.py show 는 다음의 $ 줄', outfmt.has_command(first['reason'], 'review.py" show '),
          first['reason'])


def case_hook_autofix(tmp):
    repo = taf.repo(tmp)
    s = Session(repo, os.path.join(tmp, 'data'), 'afx')
    first = s.turn(A, taf.new_file('        dd($n);\n'), 'p1')
    reason_rules('자동 수정 차단', first)
    fixed = outfmt.section(first['reason'], '자동 수정') or []
    check('자동 수정: ✔ 규칙 머리 + 위치 줄', fixed and re.match(r'^✔ \S+$', fixed[0]) and
          outfmt.LOCATION.match(fixed[1]), '\n'.join(fixed))


def case_clip(_tmp):
    text = report.clip_reason('x' * (report.REASON_LIMIT + 50))
    check('8000자 자름 표시 (F9)', text.endswith('… 이하 생략 — 위 항목부터 처리하세요'), text[-60:])


# ---------------------------------------------------------------- 2. scan.py

def case_scan_text(tmp):
    repo = laravel_repo(os.path.join(tmp, 'repo'))
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('scan.py', ['--cwd', repo, '--no-lint'], env)
    ok('scan: 공통 문법', outfmt.text_output(out.stdout, 'scan'))
    ok('scan: 요약 줄', outfmt.summary(out.stdout))
    ok('scan: 파일 단위 후보에 줄 없음', outfmt.file_level_location(
        out.stdout, 'app/Http/Controllers/UserController.php'))
    check('scan: ■ 지적 섹션', outfmt.section(out.stdout, '지적') is not None, out.stdout[:300])
    check('scan: semantic 안내는 다음의 $ 줄', outfmt.has_command(out.stdout, 'scan.py" --review'),
          out.stdout[-400:])
    check('scan: 종료 코드 1', out.returncode == 1, out.returncode)
    clean = php_repo(tmp, name='clean')
    empty = run('scan.py', ['--cwd', clean, '--no-lint'], env)
    check('scan: 빈 결과 ✔ 지적 없음', empty.stdout.rstrip().endswith('\n\n✔ 지적 없음'), repr(empty.stdout))
    ok('scan: 빈 결과 머리말', outfmt.header(empty.stdout, 'scan'))


def case_scan_json(tmp):
    repo = laravel_repo(os.path.join(tmp, 'repo'))
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('scan.py', ['--cwd', repo, '--no-lint', '--json'], env)
    problems, data = outfmt.envelope(out.stdout, 'scan')
    ok('scan --json: 봉투', problems)
    data = data or {}
    summary = data.get('summary') or {}
    check('scan --json: summary 필드', {'total', 'error', 'warn', 'info', 'lint_failures',
                                        'review_pending', 'exit_code'} <= set(summary), summary)
    check('scan --json: exit_code 가 실제와 같음', summary.get('exit_code') == out.returncode,
          (summary.get('exit_code'), out.returncode))
    locs = [loc for f in data.get('findings', []) for loc in f.get('locations', [])]
    check('scan --json: 위치마다 file/line/snippet/key',
          locs and all({'file', 'line', 'snippet', 'key'} <= set(l) for l in locs), locs[:2])
    check('scan --json: 파일 단위 후보는 line null',
          any(l['line'] is None for l in locs) and all(l['line'] != 0 for l in locs), locs[:3])
    check('scan --json: next 에 --review', any('--review' in n.get('command', '') for n in data.get('next') or []),
          data.get('next'))
    check('scan --json: unchecked 필드', 'unchecked' in data, list(data))


def case_scan_fix_and_review(tmp):
    repo = taf.repo(tmp, mode='fix')
    write(repo, A, taf.new_file())
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('scan.py', ['--cwd', repo, '--no-lint', '--fix'], env)
    ok('scan --fix: 공통 문법', outfmt.text_output(out.stdout, 'scan'))
    check('scan --fix: ■ 자동 수정 섹션', outfmt.section(out.stdout, '자동 수정') is not None, out.stdout)
    check('scan --fix: 적용 명령은 다음의 $ 줄', outfmt.has_command(out.stdout, '--fix --write'), out.stdout)
    sem = os.path.join(tmp, 'sem')
    make_repo(sem, tsr.repo_files('mode: fix\npresets: [auto, performance, architecture]\n'
                                  'semantic_review:\n  enabled: true\n'))
    write(sem, tsr.CTRL, tsr.controller())
    rev = run('scan.py', ['--cwd', sem, '--no-lint', '--review'], env)
    ok('scan --review: 공통 문법', outfmt.text_output(rev.stdout, 'scan'))
    check('scan --review: review.py show 는 다음의 $ 줄', outfmt.has_command(rev.stdout, 'review.py" show '),
          rev.stdout[-500:])
    check('scan --review: "판정하지 않았습니다" 없음', '판정하지 않았습니다' not in rev.stdout, rev.stdout[-300:])
    ok('scan --review: 요약 줄', outfmt.summary(rev.stdout))


def case_scan_stderr(tmp):
    env = isolated_env(os.path.join(tmp, 'data'))
    plain = os.path.join(tmp, 'plain')
    os.makedirs(plain)
    out = run('scan.py', ['--cwd', plain], env)
    check('scan 검사 불가: 종료 2', out.returncode == 2, out.returncode)
    ok('scan 검사 불가: stderr', outfmt.stderr_lines(out.stderr))
    check('scan 검사 불가: stdout 비어 있음', out.stdout == '', repr(out.stdout))
    repo = php_repo(tmp, 'mode: fix\nfoo_unknown: 1\n', 'warnrepo')
    warn = run('scan.py', ['--cwd', repo, '--no-lint'], env)
    ok('scan 설정 경고: stderr', outfmt.stderr_lines(warn.stderr))
    check('scan 설정 경고: 있음', 'convention-guard: warn: ' in warn.stderr, repr(warn.stderr))


def pty_run(args, env):
    import pty
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, os.path.join(SCRIPTS, 'scan.py')] + args,
                            stdout=slave, stderr=subprocess.DEVNULL, env=env)
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    proc.wait()
    os.close(master)
    return b''.join(chunks).decode('utf-8', 'replace').replace('\r\n', '\n')


def case_color(tmp):
    if os.name == 'nt':
        print('  skip pty 없음')
        return
    repo = laravel_repo(os.path.join(tmp, 'repo'))
    env = isolated_env(os.path.join(tmp, 'data'), TERM='xterm')
    env.pop('NO_COLOR', None)
    colored = pty_run(['--cwd', repo, '--no-lint'], env)
    check('F13 TTY 면 색', '\x1b[' in colored, colored[:200])
    check('F13 TTY: $ 명령 줄 청록', re.search(r'\x1b\[36m\s*\$ ', colored) is not None, colored[-400:])
    check('F13 NO_COLOR 면 색 없음',
          '\x1b[' not in pty_run(['--cwd', repo, '--no-lint'], dict(env, NO_COLOR='1')), '')
    dumb = pty_run(['--cwd', repo, '--no-lint'], dict(env, TERM='dumb'))
    check('F13 TERM=dumb 면 색 없음', '\x1b[' not in dumb, dumb[:200])
    check('F14 TERM=dumb 면 ASCII 기호', not re.search('[■✖⚠ℹ✔○…─]', dumb) and '# 지적' in dumb, dumb[:300])


# ---------------------------------------------------------------- 3. review.py

def case_review(tmp):
    sem = os.path.join(tmp, 'sem')
    make_repo(sem, tsr.repo_files('mode: fix\npresets: [auto, performance, architecture]\n'
                                  'semantic_review:\n  enabled: true\n'))
    write(sem, tsr.CTRL, tsr.controller())
    env = isolated_env(os.path.join(tmp, 'data'))
    rev = run('scan.py', ['--cwd', sem, '--no-lint', '--review', '--json'], env)
    data = json.loads(rev.stdout)
    batch = ((data.get('head') or data).get('review') or {}).get('batch')
    check('review: 배치가 만들어짐', bool(batch), rev.stdout[:300])
    if not batch:
        return
    shown = run('review.py', ['show', batch], env)
    lines = shown.stdout.split('\n')
    check('show: 머리말', re.match(r'^# convention-guard review show — 후보 \d+건 · repo ', lines[0]),
          lines[0])
    heads = [l for l in lines if l.startswith('## ') and l != '## 다음']
    check('show: 규칙 제목은 ## <아이콘> 강도[규칙]: 제목',
          heads and all(re.match(r'^## (✖ error|⚠ warn|ℹ info)\[[^\]]+\]: \S', h) for h in heads), heads)
    check('show: 컨텍스트 절 제목 ####', any(l.startswith('#### ') for l in lines), shown.stdout[:600])
    check('show: 끝에 ## 다음', '## 다음' in lines, lines[-12:])
    widths = []
    block = []
    for line in lines + ['']:
        match = re.match(r'^( *\d+)\| ', line)
        if match:
            block.append(len(match.group(1)))
        elif block:
            widths.append(block)
            block = []
    check('show: 절 안의 줄 번호 폭이 같음', widths and all(len(set(b)) == 1 for b in widths),
          [b for b in widths if len(set(b)) > 1][:2])
    ids = [int(i) for i in re.findall(r'^### 후보 (\d+)', shown.stdout, re.M)]
    answers = json.dumps([{'id': i, 'verdict': 'VIOLATION', 'reason': '근거 %d' % i} for i in ids])
    recorded = run_script('review.py', ['record', batch], stdin=answers, env=env)
    ok('record: 머리말', outfmt.header(recorded.stdout, 'review record'))
    ok('record: 공통 문법', outfmt.text_output(recorded.stdout))
    check('record: 이유는 = 이유:', '  = 이유: 근거 ' in recorded.stdout, recorded.stdout)
    summ = run('review.py', ['summary', batch], env)
    ok('summary: 머리말', outfmt.header(summ.stdout, 'review summary'))
    bad = run_script('review.py', ['record', batch], stdin='[]', env=env)
    ok('record 거부: stderr', outfmt.stderr_lines(bad.stderr))
    js = run('review.py', ['show', batch, '--json'], env)
    ok('show --json: 봉투', outfmt.envelope(js.stdout, 'review-show')[0])


# ---------------------------------------------------------------- 4. reports

def case_detect_stack(tmp):
    repo = php_repo(tmp, 'mode: fix\nfoo_unknown: 1\n')
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('detect_stack.py', ['--cwd', repo], env)
    ok('detect_stack: 공통 문법', outfmt.text_output(out.stdout, 'detect_stack'))
    titles = [t for t, _ in outfmt.sections(out.stdout)]
    check('detect_stack: 섹션', [t.split(' — ')[0] for t in titles][:3] == ['설정', '린터', '규칙']
          or [t.split(' — ')[0] for t in titles][:2] == ['설정', '규칙'], titles)
    ok('detect_stack: 규칙 표', outfmt.table(outfmt.section(out.stdout, '규칙') or []))
    ok('detect_stack: 설정 경고는 stderr', outfmt.stderr_lines(out.stderr))
    check('detect_stack: 설정 경고가 stdout 에 없음', 'foo_unknown' not in out.stdout, out.stdout[-200:])
    js = run('detect_stack.py', ['--cwd', repo, '--json'], env)
    ok('detect_stack --json: 봉투', outfmt.envelope(js.stdout, 'detect-stack')[0])


def case_log_report(tmp):
    repo = php_repo(tmp)
    data = os.path.join(tmp, 'data')
    s = Session(repo, data, 'lr')
    s.turn(A, body(), 'p1')
    s.turn(A, body('return 2;'), 'p1', stop_hook_active=True)
    env = isolated_env(data)
    out = run('log_report.py', [], env)
    ok('log_report: 공통 문법', outfmt.text_output(out.stdout, 'log_report'))
    ok('log_report: 건강도 표 (한글 폭)', outfmt.table(outfmt.section(out.stdout, '규칙 건강도') or []))
    js = run('log_report.py', ['--json'], env)
    ok('log_report --json: 봉투', outfmt.envelope(js.stdout, 'log-report')[0])
    empty_env = isolated_env(os.path.join(tmp, 'empty'))
    empty = run('log_report.py', [], empty_env)
    ok('log_report 빈 로그: 머리말', outfmt.header(empty.stdout, 'log_report'))
    ok('log_report 빈 로그 --json: 봉투', outfmt.envelope(run('log_report.py', ['--json'], empty_env).stdout,
                                                     'log-report')[0])


def case_readiness(tmp):
    repo = php_repo(tmp)
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('readiness.py', ['--quick', '--cwd', repo], env)
    ok('readiness: 공통 문법', outfmt.text_output(out.stdout, 'readiness'))
    rows = [l for l in out.stdout.split('\n') if re.match(r'^[✖⚠?○✔] ', l)]
    check('readiness: 항목 줄 <아이콘> <상태 6칸>  <id 3칸> <내용>',
          rows and all(re.match(r'^(✖ fail  |⚠ warn  |\? manual|○ skip  |✔ pass  )  [A-Z]\d?\s{1,3}\S', r)
                       for r in rows), rows[:3])
    tail = out.stdout.rstrip('\n').split('\n')[-3:]
    ok('readiness: 끝의 개수 표', outfmt.table(tail))
    check('readiness: 개수 표 머리', tail[0].split() == ['fail', 'warn', 'manual', 'skip', 'pass'], tail)
    js = run('readiness.py', ['--quick', '--cwd', repo, '--json'], env)
    ok('readiness --json: 봉투', outfmt.envelope(js.stdout, 'readiness')[0])


def case_dismiss(tmp):
    repo = php_repo(tmp)
    write(repo, A, body())
    env = isolated_env(os.path.join(tmp, 'data'))
    out = run('dismiss.py', ['--cwd', repo, '--rule', 'core/php-no-debug-output', '--file', A,
                             '--line', '11', '--reason', '디버그 도구', '--by', 'agent'], env)
    ok('dismiss 기록: 공통 문법', outfmt.text_output(out.stdout, 'dismiss'))
    check('dismiss 기록: ✔ 규칙 + 위치 줄 + 키', re.search(
        r'^✔ core/php-no-debug-output\n  app/Svc/A\.php:11  .*\n  = 참고: 키 core/php-no-debug-output:'
        r'app/Svc/A\.php:[0-9a-f]{10}$', out.stdout, re.M) is not None, out.stdout)
    listed = run('dismiss.py', ['--cwd', repo, '--list'], env)
    ok('dismiss --list: 머리말', outfmt.header(listed.stdout, 'dismiss --list'))
    ok('dismiss --list: 표', outfmt.table(listed.stdout.split('\n')))
    check('dismiss --list: 파일:지문 혼용 없음', not re.search(r'\.php:[0-9a-f]{10}', listed.stdout),
          listed.stdout)
    bad = run('dismiss.py', ['--cwd', repo, '--key', 'nonsense', '--reason', 'x'], env)
    ok('dismiss 입력 오류: stderr', outfmt.stderr_lines(bad.stderr))


def case_setup(tmp):
    repo = php_repo(tmp)
    os.remove(os.path.join(repo, '.claude/convention-guard/config.yaml'))
    env = isolated_env(os.path.join(tmp, 'data'))
    init = run('setup.py', ['init', '--cwd', repo], env)
    ok('init: 공통 문법', outfmt.text_output(init.stdout, 'setup init'))
    check('init: 다음 명령', outfmt.has_command(init.stdout, 'detect_stack.py"'), init.stdout)
    again = run('setup.py', ['init', '--cwd', repo], env)
    check('init 이미 있음: 종료 1', again.returncode == 1, again.returncode)
    ok('init 이미 있음: stderr', outfmt.stderr_lines(again.stderr))
    emit = run('setup.py', ['emit', '--cwd', repo], env)
    ok('emit: 공통 문법', outfmt.text_output(emit.stdout, 'setup emit'))
    rules_dir = os.path.join(repo, '.claude', 'rules')
    lines = []
    for name in sorted(os.listdir(rules_dir)):
        with open(os.path.join(rules_dir, name), encoding='utf-8') as fh:
            lines += [l for l in fh.read().split('\n') if l.startswith('- ') and 'convention-lint' not in name]
    check('emit md: 규칙 줄 - **강도** `id` 제목 — 안내',
          lines and all(re.match(r'^- \*\*(error|warn|info)\*\* `[^`]+` \S', l) for l in lines), lines[:3])


if __name__ == '__main__':
    cases = [case_hook_block_and_verify, case_hook_notices, case_hook_lint, case_hook_semantic,
             case_hook_autofix, case_clip, case_scan_text, case_scan_json, case_scan_fix_and_review,
             case_scan_stderr, case_color, case_review, case_detect_stack, case_log_report,
             case_readiness, case_dismiss, case_setup]
    for case in cases:
        print('%s:' % case.__name__)
        with tempdir() as tmp:
            case(tmp)
    sys.exit(finish('출력 형식'))
