#!/usr/bin/env python3
"""Adoption check: does every part of convention-guard work in this repo?

    python3 readiness.py                 # 전체 점검 (샌드박스 테스트 포함, ~30초)
    python3 readiness.py --quick         # 레포·설치 상태만 (샌드박스·측정 생략, ~2초)
    python3 readiness.py --all           # + 레포 전수조사 error 건수
    python3 readiness.py --json

Each line is one item of docs/production-readiness.md, by its id. The engine
behaviours that need a live Stop hook (block, verify, loop caps, dismissals,
semantic review, failure modes) are proven by the plugin's own test suites run
in a throwaway sandbox -- the same assertions, no real turns, nothing written
to this repo or to the real data directory.

Exit: 0 no FAIL / 1 at least one FAIL / 2 cannot check (not a git repo).
"""

import argparse
import concurrent.futures
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import detect_stack  # noqa: E402
from lib import config as configlib, dismiss as dismisslib, fmt, pipeline  # noqa: E402
from lib import rules as rulelib  # noqa: E402
from lib.install import (check_data_dirs, check_hooks, check_install, check_scopes,  # noqa: E402
                         check_user_config, read_json)
from lib.paths import plugin_root, project_dir  # noqa: E402

# The docs' "0~2 per commit" line: above it an agent in fix mode keeps getting blocked
FINDINGS_PER_COMMIT_WARN = 2
# Stop hook timeout (hooks.json) is 150s and the lint phase is cut at 110s
SCAN_SECONDS_WARN, SCAN_SECONDS_FAIL = 30, 110
# The sandbox suites, and the checklist items each one proves
SUITES = [
    ('A1', 'unit/test_version_guard.py'),
    ('A4', 'unit/test_yaml_parity.py'),
    ('B3', 'plugin/test_manifest.py'),
    ('B6', 'skills/test_skill_structure.py'),
    ('C2', 'unit/test_config_and_rules.py'),
    ('D3', 'rules/test_rule_scenarios.py'),
    ('D4', 'structure/test_detect_conditions.py'),
    ('D4', 'structure/test_conditions.py'),
    ('F', 'integration/test_hook_cycle.py'),
    ('F', 'integration/test_autofix.py'),
    ('F', 'integration/test_dismiss_and_report.py'),
    ('G', 'integration/test_semantic_review.py'),
    ('G', 'semantic/test_context_pack.py'),
    ('G', 'semantic/test_review_key.py'),
    ('H', 'integration/test_cli_contract.py'),
    ('H', 'integration/test_lint_anchor.py'),
    ('H', 'integration/test_self_exclude.py'),
    ('H', 'integration/test_migrate.py'),
    ('L4', 'integration/test_setup_emit.py'),
]


class Report:
    def __init__(self):
        self.items = []

    def add(self, item_id, status, text, fix=''):
        self.items.append({'id': item_id, 'status': status.lower(), 'text': text, 'fix': fix})

    def failed(self):
        return any(i['status'] == 'fail' for i in self.items)


def sandbox_env(base, keep_home=False):
    """A process that cannot write this machine's convention-guard state: its own
    cache and data dir, no userConfig or project dir from the session, and no
    GIT_* that would point a suite's `git -C <tmp>` back at the real repo.

    keep_home leaves HOME alone so ~/.claude/convention-guard/rules is still read
    -- for runs that must judge the repo the way this machine's hooks would."""
    home = tempfile.mkdtemp(prefix='home-', dir=base)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('CLAUDE_PLUGIN_OPTION_', 'GIT_'))
           and k not in ('CLAUDE_PROJECT_DIR', 'CLAUDE_PLUGIN_DATA')}
    env.update({'XDG_CACHE_HOME': os.path.join(home, '.cache'),
                'CLAUDE_PLUGIN_DATA': os.path.join(home, 'data'),
                'PYTHONDONTWRITEBYTECODE': '1'})
    if not keep_home:
        env['HOME'] = home
    return env


def run(argv, cwd, env=None, timeout=300):
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              env=env, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, '', str(exc)


# ---------------------------------------------------------------- A. 환경

def check_env(rep, root):
    exe = shutil.which('python3')
    if not exe:
        rep.add('A1', 'FAIL', '`python3` 가 PATH 에 없습니다 — 훅이 실행되지 않습니다',
                'python3 를 PATH 에 두거나 WSL 에서 Claude Code 를 쓰세요')
    else:
        code, out, _ = run([exe, '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])'],
                           root)
        version = out.strip() or '?'
        ok = code == 0 and tuple(int(x) for x in version.split('.')[:2]) >= (3, 9)
        rep.add('A1', 'PASS' if ok else 'FAIL',
                'python3 = %s (%s — 이 셸 기준. Claude Code 가 훅을 띄우는 PATH 가 다르면 다를 수 있음)'
                % (version, exe),
                '' if ok else 'Python 3.9 이상을 python3 로 잡아 주세요')
    if os.name == 'nt':
        rep.add('A2', 'WARN', 'Windows 네이티브입니다 — hooks.json 의 python3 호출이 검증되지 '
                              '않은 경로입니다', 'WSL 에서 쓰거나 scan.py + CI 로 운영하세요')
    else:
        rep.add('A2', 'PASS', '이 머신은 %s — 팀원 중 Windows 네이티브 사용자는 수동 확인'
                % sys.platform)


def check_no_deps(rep, root, script_dir, base):
    """The fallback parser must reach the same conclusion about this repo."""
    have_yaml = importlib.util.find_spec('yaml') is not None
    outs = []
    for no_yaml in ('', '1'):
        env = dict(sandbox_env(base, keep_home=True), CONVENTION_GUARD_NO_PYYAML=no_yaml)
        code, out, err = run([sys.executable, os.path.join(script_dir, 'detect_stack.py'),
                              '--json', '--cwd', root], root, env)
        try:
            info = json.loads(out)
        except ValueError:
            rep.add('A4', 'FAIL', 'detect_stack.py 가 실행되지 않습니다: %s' % err.strip()[-200:])
            return
        outs.append(sorted((r['id'], r['status'], r['severity']) for r in info['rules']))
    same = outs[0] == outs[1]
    if not have_yaml:
        rep.add('A4', 'SKIP' if same else 'FAIL', 'PyYAML 이 없어 내장 파서로만 동작 확인 — 두 파서의 '
                '판정 비교는 하지 못했습니다' if same else '내장 파서로 실행하지 못했습니다')
        return
    rep.add('A4', 'PASS' if same else 'FAIL',
            '설치 없이 동작, PyYAML 유무와 무관하게 같은 규칙 판정' if same else
            'PyYAML 과 내장 파서가 이 레포 설정을 다르게 읽습니다',
            '' if same else 'config.yaml·로컬 규칙의 YAML 문법을 단순하게 (tests/unit/test_yaml_parity.py)')


def check_skills(rep, root_dir):
    skills = sorted(os.path.basename(os.path.dirname(p))
                    for p in glob.glob(os.path.join(root_dir, 'skills', '*', 'SKILL.md')))
    agent = os.path.isfile(os.path.join(root_dir, 'agents', 'convention-reviewer.md'))
    rep.add('B6', 'PASS' if skills and agent else 'FAIL',
            '스킬 %d개 (%s), 리뷰어 에이전트 %s' % (len(skills), ', '.join(skills),
                                                 '있음' if agent else '없음'))


# ---------------------------------------------------------------- C. 레포 설정

def check_config(rep, root, info):
    cfg = configlib.load(root)
    errors = [t for lv, t in cfg.notes if lv == 'error']
    warns = [t for lv, t in cfg.notes if lv != 'error']
    where = cfg.repo_path or '없음 — 기본값'
    if errors:
        rep.add('C1', 'FAIL', 'config.yaml 오류: %s' % ' / '.join(errors),
                '훅은 이 상태에서 검사를 건너뜁니다. 오류를 고치세요')
    else:
        rep.add('C1', 'WARN' if warns else 'PASS', 'config: %s · mode: %s%s'
                % (where, cfg['mode'], (' · 경고: ' + ' / '.join(warns)) if warns else ''))
    if cfg['mode'] != 'report':
        rep.add('C1', 'WARN', 'mode: %s — 차단이 켜져 있습니다. 도입 첫 2~3주라면 report 를 권합니다'
                % cfg['mode'], 'E1 이 커밋당 2건 이하이고 rule-tune 점검을 거쳤는지 확인하세요')
    if rulelib.legacy_layout(root):
        rep.add('C1', 'FAIL', '%s (0.x 설정)이 남아 있습니다' % rulelib.LEGACY_DIRNAME,
                'convention-setup 은 이 상태에서 init 하지 않습니다. 디렉터리를 치우세요')
    stacks = info['stacks']
    rep.add('C3', 'PASS' if stacks else 'WARN', '스택: %s · 프리셋: %s' % (
        ', '.join(stacks) or '감지 실패',
        ', '.join(p['name'] for p in info['presets'] if p['active'])),
        '' if stacks else 'config.yaml 에 stacks: 로 지정하세요')
    return cfg


def check_linters(rep, info, cfg):
    if not cfg['linters']['enabled']:
        rep.add('C4', 'PASS', '린터 위임 꺼짐 (linters.enabled: false)')
        return
    if not info['linters']:
        rep.add('C4', 'PASS', '이 스택에 번들 린터 없음')
    for linter in info['linters']:
        if not linter['installed']:
            rep.add('C4', 'PASS', '%s — 설치 안 됨, 건너뜀' % linter['cmd'])
        elif linter['parse']:
            rep.add('C4', 'PASS', '%s — 변경 줄만 차단 (parse: %s)' % (linter['cmd'], linter['parse']))
        else:
            rep.add('C4', 'WARN', '%s — 출력을 읽지 못해 무관한 기존 에러로도 차단' % linter['cmd'],
                    'stacks/*.yaml 에 parse: 추가 (docs/configuration.md 린터 위임)')


def check_layers(rep, root):
    personal = list(rulelib.iter_rule_files(rulelib.user_rules_dir()))
    if personal:
        rep.add('C5', 'WARN', '개인 규칙 %d개 (%s) — 이 머신에서만 돌고 팀원에게는 없습니다'
                % (len(personal), rulelib.user_rules_dir()),
                '팀 규칙이면 .claude/convention-guard/rules/ 로 옮기세요')
    else:
        rep.add('C5', 'PASS', '개인 규칙 레이어 비어 있음 — 모든 팀원이 같은 규칙')
    dismissed = dismisslib.load(root)
    if dismissed.error:
        rep.add('C6', 'FAIL', 'dismissed.yaml 파싱 실패: %s' % dismissed.error,
                '이 상태에서는 훅이 검사를 건너뜁니다. 파일을 고치세요')
    else:
        rep.add('C6', 'PASS', '기각 기록 %d건' % len(dismissed))


# ---------------------------------------------------------------- D. 규칙이 전부 동작

def tracked_files(root):
    code, out, _ = run(['git', 'ls-files', '-z'], root)
    return [p for p in out.split('\0') if p] if code == 0 else []


def reach(rule, paths):
    if rule['kind'] == 'paired':
        return sum(1 for p in paths if rulelib.match_any(rule['when_changed'], p))
    return sum(1 for p in paths if rulelib.path_ok(rule, p))


def check_reach(rep, root, info, cfg):
    """An active rule whose globs match no file in the repo can never fire."""
    active = {r['id'] for r in info['rules'] if r['status'] == 'active'}
    ruleset = pipeline.load_rules(root, cfg, pipeline.detect_stacks(root, cfg))
    paths = tracked_files(root)
    dead = [r['id'] for r in ruleset.rules if r['id'] in active and not reach(r, paths)]
    if dead:
        rep.add('D2', 'WARN', '적용 규칙 %d개 중 %d개가 레포의 어떤 파일에도 닿지 않습니다: %s'
                % (len(active), len(dead), ', '.join(dead)),
                'applies_to.files 가 이 레포 구조와 맞는지 보세요 (override 로 경로 수정)')
    else:
        rep.add('D2', 'PASS', '적용 규칙 %d개 모두 추적 파일 %d개 중 하나 이상에 닿음'
                % (len(active), len(paths)))
    semantic = [r['id'] for r in info['rules'] if r['status'] == 'active' and r['semantic']]
    if semantic and not cfg['semantic_review']['enabled']:
        rep.add('D5', 'WARN', '의미 판정 규칙 %s 가 켜져 있지만 semantic_review 가 꺼져 있어 '
                '판정되지 않습니다' % ', '.join(semantic),
                'config.yaml 에 semantic_review: {enabled: true} 또는 해당 프리셋 제거')
    else:
        rep.add('D5', 'PASS', '의미 판정 규칙 %d개 · semantic_review %s'
                % (len(semantic), 'on' if cfg['semantic_review']['enabled'] else 'off'))


# ---------------------------------------------------------------- E. 탐지량 · I. 성능

def commit_count(root):
    code, out, _ = run(['git', 'rev-list', '--count', 'HEAD'], root)
    return int(out.strip()) if code == 0 and out.strip().isdigit() else 0


def scan_json(script_dir, root, args, base, timeout=600):
    start = time.time()
    code, out, err = run([sys.executable, os.path.join(script_dir, 'scan.py'), '--cwd', root,
                          '--fail-on', 'never', '--json'] + args, root,
                         env=sandbox_env(base, keep_home=True), timeout=timeout)
    try:
        return json.loads(out), time.time() - start
    except ValueError:
        return {'error': (err or out).strip()[-300:]}, time.time() - start


def check_volume(rep, root, script_dir, commits, base):
    n = min(commits, commit_count(root) - 1)
    if n < 1:
        rep.add('E1', 'SKIP', '비교할 커밋이 없습니다')
        rep.add('I1', 'SKIP', 'E1 검사가 없어 소요 시간을 재지 못했습니다')
        return
    result, seconds = scan_json(script_dir, root, ['--range', 'HEAD~%d..HEAD' % n], base)
    if 'error' in result:
        rep.add('E1', 'FAIL', 'scan.py 가 검사하지 못했습니다: %s' % result['error'])
        rep.add('I1', 'SKIP', 'E1 검사가 실패해 소요 시간을 재지 못했습니다')
        return
    counts = result['summary']
    per = (counts['error'] + counts['warn']) / float(n)
    top = sorted(result['findings'], key=lambda f: -len(f['locations']))[:3]
    rep.add('E1', 'WARN' if per > FINDINGS_PER_COMMIT_WARN else 'PASS',
            '최근 %d커밋: error %d · warn %d · info %d (커밋당 %.1f건)%s'
            % (n, counts['error'], counts['warn'], counts['info'], per,
               (' · 상위: ' + ', '.join(f['rule_id'] for f in top)) if top else ''),
            'convention-setup 4단계 표로 severity / exclude 를 조정하세요'
            if per > FINDINGS_PER_COMMIT_WARN else '')
    status = ('FAIL' if seconds > SCAN_SECONDS_FAIL else
              'WARN' if seconds > SCAN_SECONDS_WARN else 'PASS')
    rep.add('I1', status, '린터 포함 검사 %.1f초 (Stop 훅 린터 상한 %d초)' % (seconds, SCAN_SECONDS_FAIL),
            '' if status == 'PASS' else 'linters.timeout 을 줄이거나 무거운 린터는 CI 로')


def check_legacy_volume(rep, root, script_dir, base):
    result, _ = scan_json(script_dir, root, ['--all', '--severity', 'error', '--no-lint'], base)
    if 'error' in result:
        rep.add('E2', 'FAIL', '전수조사 실패: %s' % result['error'])
        return
    by_rule = sorted(((len(f['locations']), f['rule_id']) for f in result['findings']),
                     reverse=True)[:5]
    counts = result['summary']
    rep.add('E2', 'PASS', '전수조사 error %d건 — %s' % (
        counts['error'], ', '.join('%s %d+' % (r, n) for n, r in by_rule) or '없음'))


# ---------------------------------------------------------------- J. 보안 · K. CI

def plugin_sources(root_dir):
    return [p for p in glob.glob(os.path.join(root_dir, 'scripts', '**', '*.py'), recursive=True)
            if '__pycache__' not in p]


def check_security(rep, root, root_dir):
    shell, network = [], []
    net_re = re.compile(r'^\s*(import|from)\s+(urllib|requests|http\.client|socket)\b', re.M)
    for path in plugin_sources(root_dir):
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        rel = os.path.relpath(path, root_dir)
        if 'shell=True' in text and not rel.endswith('readiness.py'):
            shell.append(rel)
        if net_re.search(text):
            network.append(rel)
    rep.add('J1', 'FAIL' if shell else 'PASS', 'shell=True 사용: %s' % (', '.join(shell) or '없음'))
    rep.add('J2', 'FAIL' if network else 'PASS', '네트워크 모듈 import: %s'
            % (', '.join(network) or '없음'))
    artifact = re.compile(r'(firings\.jsonl|touched-|verdicts\.json|cache-yaml)')
    _, status, _ = run(['git', 'status', '--porcelain', '--untracked-files=all'], root)
    leaked = [l[3:] for l in status.splitlines() if artifact.search(l)]
    leaked += [p for p in tracked_files(root) if artifact.search(p) and p not in leaked]
    rep.add('J3', 'FAIL' if leaked else 'PASS', '레포에 잡힌 플러그인 산출물: %s'
            % (', '.join(leaked) or '없음'), '로그 위치(B5)를 레포 밖으로' if leaked else '')


def check_ci(rep, root):
    hits = []
    for path in glob.glob(os.path.join(root, '.github', 'workflows', '*.y*ml')) + \
            glob.glob(os.path.join(root, '.gitlab-ci.yml')):
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
        if 'scan.py' in text:
            hits.append((os.path.relpath(path, root), text))
    if not hits:
        rep.add('K1', 'MANUAL', 'CI 에 scan.py 가 없습니다 — 훅은 로컬 안전망, 강제는 CI',
                'docs/production-readiness.md K 절의 명령을 CI 에 넣으세요')
        return
    for rel, text in hits:
        problems = []
        if 'fetch-depth: 0' not in text and '.github' in rel:
            problems.append('fetch-depth: 0 없음 (base ref 가 없으면 exit 2)')
        if '--fail-on never' in text:
            problems.append('--fail-on never — 리포트만')
        if '|| true' in text:
            problems.append('|| true 가 exit 2(검사 불가)를 성공으로 바꿉니다')
        rep.add('K1', 'WARN' if problems else 'PASS', '%s: scan.py 있음%s'
                % (rel, (' — ' + ' · '.join(problems)) if problems else ''))


# ---------------------------------------------------------------- 샌드박스 스위트

def run_suite(root_dir, label, extra, base):
    env = sandbox_env(base)
    path = os.path.join(root_dir, 'tests', label)
    code, out, err = run([sys.executable, path] + extra, root_dir, env)
    lines = [l.strip() for l in (out + err).splitlines() if l.strip()]
    failures = [l for l in lines if 'FAIL' in l][:3]
    return code, failures or lines[-3:]


def check_suites(rep, root, root_dir, base):
    """The engine behaviours a checklist would otherwise test by ending real turns."""
    jobs = [(item, label, []) for item, label in SUITES]
    # the sandbox HOME hides personal rules, so D1 is handed the real directory
    jobs.append(('D1', 'rules/test_rule_fixtures.py',
                 ['--repo', root, '--user-dir', rulelib.user_rules_dir()]))
    missing = [label for _, label, _ in jobs
               if not os.path.isfile(os.path.join(root_dir, 'tests', label))]
    if missing:
        rep.add('S', 'SKIP', '테스트가 없는 설치본입니다: %s' % ', '.join(missing))
        jobs = [j for j in jobs if j[1] not in missing]
    workers = min(len(jobs), os.cpu_count() or 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [(item, label, pool.submit(run_suite, root_dir, label, extra, base))
                   for item, label, extra in jobs]
        for item, label, future in futures:
            code, evidence = future.result()
            rep.add(item, 'PASS' if code == 0 else 'FAIL', '샌드박스 %s' % label,
                    '' if code == 0 else ' | '.join(evidence))


def check_internal_error(rep, root_dir, base):
    """H3 live: a bug inside the Stop hook must speak, exit 0, and not crash."""
    env = sandbox_env(base)
    try:
        proc = subprocess.run([sys.executable, os.path.join(root_dir, 'scripts', 'check.py')],
                              input='{"session_id": "readiness", "cwd": 1}', text=True,
                              capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        rep.add('H3', 'FAIL', 'check.py 실행 실패: %s' % exc)
        return
    ok = proc.returncode == 0 and '내부 오류' in proc.stdout
    rep.add('H3', 'PASS' if ok else 'FAIL', 'Stop 훅 내부 오류 — exit %d, %s' % (
        proc.returncode, '사유를 말함' if ok else '침묵 또는 비정상 종료: %r' % proc.stdout[-120:]))


# ---------------------------------------------------------------- 출력

ORDER = {'fail': 0, 'warn': 1, 'manual': 2, 'skip': 3, 'pass': 4}
STATUSES = sorted(ORDER, key=ORDER.get)


def tally(items):
    return {s: sum(i['status'] == s for i in items) for s in STATUSES}


def render(rep, root, version, seconds, style=fmt.PLAIN):
    head = fmt.header('readiness', [root, '플러그인 %s' % version, '%.0f초' % seconds], style=style)
    lines = []
    for item in rep.items:
        text = item['text'].strip().split('\n')
        lead = '%s  %s ' % (style.paint('%s %s' % (fmt.GLYPH[item['status']],
                                                   fmt.pad(item['status'], 6)), item['status']),
                            fmt.pad(item['id'], 3))
        lines.append(lead + text[0])
        if len(text) > 1:
            lines.append(fmt.more(len(text) - 1, indent=14))
        if item['fix']:
            lines += fmt.aux('조치', item['fix'], indent=14, style=style)
    counts = tally(rep.items)
    table = fmt.table(STATUSES, [[counts[s] for s in STATUSES]], align=['r'] * 5, style=style)
    return style.finish(fmt.blocks([head], lines, table))


def guarded(rep, item_id, fn, *args):
    """A check that crashes is a FAIL of the check, never a missing line."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 -- any bug here must still be reported
        rep.add(item_id, 'FAIL', '점검 자체가 실패했습니다 — %s: %s' % (type(exc).__name__, exc),
                '이 줄은 판정이 아닙니다. 플러그인 이슈로 보고하세요')
        return None


def run_checks(rep, args, session, root, root_dir, version, base):
    guarded(rep, 'A1', check_env, rep, root)
    guarded(rep, 'A4', check_no_deps, rep, root, HERE, base)
    key = guarded(rep, 'B1', check_install, rep, session, version)
    guarded(rep, 'B2', check_scopes, rep, session, key)
    hook_dir = guarded(rep, 'B3', check_hooks, rep, key)
    guarded(rep, 'B4', check_data_dirs, rep, hook_dir)
    guarded(rep, 'B5', check_user_config, rep, session, root, key)
    guarded(rep, 'B6', check_skills, rep, root_dir)
    info = guarded(rep, 'C3', detect_stack.collect, root)
    cfg = info and guarded(rep, 'C1', check_config, rep, root, info)
    if cfg:
        guarded(rep, 'C4', check_linters, rep, info, cfg)
        guarded(rep, 'D2', check_reach, rep, root, info, cfg)
    guarded(rep, 'C5', check_layers, rep, root)
    guarded(rep, 'J1', check_security, rep, root, root_dir)
    guarded(rep, 'K1', check_ci, rep, root)
    if args.quick:
        return
    guarded(rep, 'E1', check_volume, rep, root, HERE, args.commits, base)
    if args.all:
        guarded(rep, 'E2', check_legacy_volume, rep, root, HERE, base)
    guarded(rep, 'S', check_suites, rep, root, root_dir, base)
    guarded(rep, 'H3', check_internal_error, rep, root_dir, base)


def main():
    parser = argparse.ArgumentParser(description='convention-guard 도입 점검')
    parser.add_argument('--cwd', help='레포 경로 (기본: 현재 디렉터리)')
    parser.add_argument('--quick', action='store_true', help='샌드박스 테스트·측정 생략')
    parser.add_argument('--all', action='store_true', help='레포 전수조사 error 건수 포함')
    parser.add_argument('--commits', type=int, default=20, help='탐지량을 잴 최근 커밋 수')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    start = time.time()
    session = project_dir(args.cwd)     # Claude Code keys settings on this, not the git root
    code, top, _ = run(['git', 'rev-parse', '--show-toplevel'], session)
    if code != 0:
        fmt.eprint('error', '검사 불가: git 레포가 아닙니다: %s' % session)
        return 2
    root = top.strip()
    root_dir = plugin_root()
    version = read_json(os.path.join(root_dir, '.claude-plugin', 'plugin.json')).get('version', '?')
    rep = Report()
    with tempfile.TemporaryDirectory(prefix='cg-readiness-') as base:
        run_checks(rep, args, session, root, root_dir, version, base)
    rep.items.sort(key=lambda i: (ORDER[i['status']], i['id']))

    if args.json:
        print(fmt.dumps(fmt.envelope('readiness', tally(rep.items),
                                     {'root': root, 'version': version, 'items': rep.items})))
    else:
        print(render(rep, root, version, time.time() - start, fmt.Style.for_stream()))
    return 1 if rep.failed() else 0


if __name__ == '__main__':
    sys.exit(main())
