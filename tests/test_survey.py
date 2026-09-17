#!/usr/bin/env python3
"""추천이 숫자에 근거하는지, 채택한 것이 진짜 규칙이 되는지.

규칙 추천의 실패 모드는 하나뿐입니다 — 레포가 실제로 반대로 쓰고 있는데 추천하는 것.
그러면 첫 턴부터 오탐이 쏟아지고, 도입 첫날에 신뢰를 잃습니다. 그래서 여기서 보는 것은
"준수율을 제대로 세는가"와 "채택 결과가 그대로 규칙으로 동작하는가" 둘입니다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import survey as surveylib  # noqa: E402
from lib import engine, gitdiff, rules as rulelib  # noqa: E402

FAILED = []

CANDIDATE = """id: test-use-service-layer
title: 컨트롤러에서 직접 조회 금지
severity: warn
applies_to:
  stack: ["*"]
  files: ["app/**/*.php"]
triggers:
  code_regex: '\\b[A-Z]\\w+::(where|find)\\s*\\('
context_injection: |
  서비스를 거치세요.
probe:
  conforming: '\\$this->\\w*[sS]ervice\\w*->'
rationale: 테스트용 후보입니다.
tests:
  should_match:
    - '$x = Order::where("a", 1)->get();'
  should_not_match:
    - '$x = $this->orderService->all();'
"""


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def git(tmp, *args):
    return subprocess.run(['git', '-C', tmp] + list(args), check=True,
                          capture_output=True, text=True)


def write(tmp, rel, body):
    path = os.path.join(tmp, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)


def make_repo(tmp, conforming, violating):
    git(tmp, 'init', '-q')
    git(tmp, 'config', 'user.email', 't@t')
    git(tmp, 'config', 'user.name', 't')
    write(tmp, 'composer.json', '{}')
    for i in range(conforming):
        write(tmp, 'app/Ok%d.php' % i,
              '<?php\nclass Ok%d { function f() { return $this->orderService->all(); } }\n'
              % i)
    for i in range(violating):
        write(tmp, 'app/Bad%d.php' % i,
              '<?php\nclass Bad%d { function f() { return Order::where("a", 1)->get(); } }\n'
              % i)
    git(tmp, 'add', '-A')
    git(tmp, 'commit', '-q', '-m', 'init')


def catalog(tmp):
    """A candidate directory outside the plugin, so the test owns its input."""
    base = os.path.join(tmp, 'catalog')
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, 'test-use-service-layer.yaml'), 'w',
              encoding='utf-8') as fh:
        fh.write(CANDIDATE)
    return [(base, 'candidate')]


def row_for(tmp, dirs):
    report, candidates = surveylib.survey(tmp, dirs=dirs)
    row = next((r for r in report['rows']
                if r['id'].endswith('test-use-service-layer')), None)
    return report, row, candidates


def case_verdicts(_tmp):
    print('case_verdicts:')
    cases = [
        (4, 1, 'recommend', '4:1 은 컨벤션이 있는 것'),
        (5, 0, 'already', '위반이 없으면 회귀 방지용'),
        (2, 3, 'undecided', '반반이면 합의가 먼저'),
        (0, 4, 'against', '레포가 반대로 쓰면 추천 안 함'),
        (1, 1, 'thin', '한 건씩은 컨벤션이 아니라 표본 부족'),
        (2, 0, 'thin', '준수만 둘이어도 회귀 방지용으로 단정하지 않음'),
        (0, 0, 'absent', '해당 코드가 없으면 판단 불가'),
    ]
    for conforming, violating, expected, why in cases:
        repo = tempfile.mkdtemp()
        try:
            make_repo(repo, conforming, violating)
            dirs = catalog(repo)
            _report, row, _c = row_for(repo, dirs)
            check('준수 %d / 위반 %d → %s (%s)'
                  % (conforming, violating, expected, why),
                  row is not None and row['verdict'] == expected,
                  row and (row['verdict'], row['adherence']))
        finally:
            shutil.rmtree(repo, ignore_errors=True)


def case_adopt(tmp):
    print('case_adopt:')
    make_repo(tmp, 4, 1)
    dirs = catalog(tmp)
    _report, row, candidates = row_for(tmp, dirs)
    cand = next(c for c in candidates if c['id'].endswith('test-use-service-layer'))
    check('추천 판정', row['verdict'] == 'recommend', row)
    check('준수/위반을 파일 단위로 셈',
          (row['conforming'], row['violating']) == (4, 1), row)
    check('채택 후 규칙 id 를 미리 알려줌',
          row['adopted_id'] == 'local/test-use-service-layer', row)

    path = surveylib.adopt(tmp, cand, 'warn')
    check('레포 규칙 디렉터리에 씀',
          os.path.dirname(path).endswith(os.path.join('.claude', 'convention-rules')),
          path)
    body = open(path, encoding='utf-8').read()
    for key in surveylib.CATALOG_KEYS:
        check('카탈로그 전용 키 %s 제거' % key, '\n%s:' % key not in body, body)
    check('픽스처는 함께 따라옴', 'should_match' in body, body)
    check('강도가 적용됨', 'severity: warn' in body, body)

    rules, notes, _cfg = rulelib.load_all(tmp)
    adopted = [r for r in rules if r['id'] == 'local/test-use-service-layer']
    check('엔진이 규칙으로 로드', len(adopted) == 1,
          [r['id'] for r in rules if r['source'] != 'core'])
    check('로드 경고 없음', not [n for n in notes if n[0] == 'error'], notes)

    # the file is committed, so measuring it needs the audit-style whole-file
    # context -- the same one survey.py builds
    changed = {'app/Bad0.php': gitdiff._whole_file(tmp, 'app/Bad0.php')}
    ctx = engine.Context(tmp, changed, set(changed), {'php'}, {})
    check('채택한 규칙이 위반 파일에서 발동',
          len(engine.collect(adopted, ctx, 5)) == 1, changed)

    clean = {'app/Ok0.php': gitdiff._whole_file(tmp, 'app/Ok0.php')}
    ctx_clean = engine.Context(tmp, clean, set(clean), {'php'}, {})
    check('준수 파일에서는 발동하지 않음',
          engine.collect(adopted, ctx_clean, 5) == [], clean)

    _report2, row2, _c2 = row_for(tmp, dirs)
    check('재조사에서 이미 채택됨으로 표시', row2['verdict'] == 'adopted', row2)


def case_cli(tmp):
    print('case_cli:')
    make_repo(tmp, 4, 1)
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT, CLAUDE_PROJECT_DIR=tmp)
    script = os.path.join(ROOT, 'scripts', 'survey.py')
    proc = subprocess.run(['python3', script, '--json'], cwd=tmp,
                          capture_output=True, text=True, env=env)
    check('--json 이 성공적으로 끝남', proc.returncode == 0, proc.stderr[:300])
    try:
        report = json.loads(proc.stdout)
    except ValueError as exc:
        check('--json 파싱', False, '%s / %s' % (exc, proc.stdout[:200]))
        return
    check('플러그인 카탈로그 후보를 읽음', report['candidates_total'] > 0, report)
    check('조사한 파일 수를 보고함', report['files_scanned'] >= 5, report)

    proc = subprocess.run(['python3', script, '--adopt', 'candidate/nope'],
                          cwd=tmp, capture_output=True, text=True, env=env)
    check('없는 후보를 채택하려 하면 실패', proc.returncode == 2, proc.stdout)


def case_candidate_is_not_a_rule(tmp):
    print('case_candidate_is_not_a_rule:')
    make_repo(tmp, 4, 1)
    # a repo-local candidate lives under the rules directory. It must not be
    # loaded as a rule: an unadopted candidate firing in the hook would mean
    # the recommendation enforced itself.
    local = os.path.join(tmp, rulelib.LOCAL_DIRNAME, 'candidates')
    os.makedirs(local, exist_ok=True)
    with open(os.path.join(local, 'test-use-service-layer.yaml'), 'w',
              encoding='utf-8') as fh:
        fh.write(CANDIDATE)

    rules, notes, _cfg = rulelib.load_all(tmp)
    check('후보는 규칙으로 로드되지 않음',
          not [r for r in rules if 'test-use-service-layer' in r['id']],
          [r['id'] for r in rules if r['source'] != 'core'])
    check('로드 경고도 없음', not notes, notes)

    report, _cands = surveylib.survey(tmp)
    row = next((r for r in report['rows']
                if r['id'] == 'local-candidate/test-use-service-layer'), None)
    check('그래도 후보로는 측정됨', row is not None and row['verdict'] == 'recommend',
          row)


CASES = [case_verdicts, case_adopt, case_cli, case_candidate_is_not_a_rule]


def main():
    for case in CASES:
        tmp = tempfile.mkdtemp()
        try:
            case(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print('\n실패 %d건: %s' % (len(FAILED), ', '.join(FAILED)))
        return 1
    print('\n통과 — 규칙 후보 추천/채택')
    return 0


if __name__ == '__main__':
    sys.exit(main())
