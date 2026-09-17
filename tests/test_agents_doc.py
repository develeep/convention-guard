#!/usr/bin/env python3
"""AGENTS.md 생성이 사람이 쓴 내용을 건드리지 않는지.

생성기가 한 번이라도 사람 문단을 날리면 다시는 안 씁니다. 그래서 관리 블록
(`<!-- convention-guard:begin -->` ~ `end`) 안만 교체되는지, CLAUDE.md 는 본문을
복사하지 않고 `@AGENTS.md` 로 가리키는지, 대상 레포의 줄바꿈 형식을 따르는지를 봅니다.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []
BEGIN = '<!-- convention-guard:begin'
END = '<!-- convention-guard:end -->'


def check(name, condition, detail=''):
    if condition:
        print('  ok   %s' % name)
    else:
        print('  FAIL %s  %s' % (name, detail))
        FAILED.append(name)


def make_repo(tmp, crlf=False):
    subprocess.run(['git', 'init', '-q', tmp], check=True)
    for key, value in (('user.email', 't@t'), ('user.name', 't')):
        subprocess.run(['git', '-C', tmp, 'config', key, value], check=True)
    eol = '\r\n' if crlf else '\n'
    with open(os.path.join(tmp, 'composer.json'), 'w', newline='') as fh:
        fh.write(eol.join(['{', '  "require": {"laravel/framework": "^11.0"}', '}']))
    with open(os.path.join(tmp, 'README.md'), 'w', newline='') as fh:
        fh.write(eol.join(['# proj', '']))
    os.makedirs(os.path.join(tmp, 'app'), exist_ok=True)
    with open(os.path.join(tmp, 'app', 'X.php'), 'w') as fh:
        fh.write('<?php\n')
    subprocess.run(['git', '-C', tmp, 'add', '-A'], check=True)
    subprocess.run(['git', '-C', tmp, 'commit', '-q', '-m', 'init'], check=True)


def emit(tmp, *args):
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT, CLAUDE_PROJECT_DIR=tmp)
    return subprocess.run(
        ['python3', os.path.join(ROOT, 'scripts', 'emit_rules.py')] + list(args),
        cwd=tmp, capture_output=True, text=True, env=env)


def read(tmp, name):
    path = os.path.join(tmp, name)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8', newline='') as fh:
        return fh.read()


def case_fresh_repo(tmp):
    print('case_fresh_repo:')
    make_repo(tmp)
    proc = emit(tmp, '--agents-md')
    check('실행 성공', proc.returncode == 0, proc.stderr[:300])
    agents, claude = read(tmp, 'AGENTS.md'), read(tmp, 'CLAUDE.md')
    check('AGENTS.md 생성', agents and BEGIN in agents and END in agents, agents)
    check('규칙이 실제로 들어감', agents and '- ' in agents, agents)
    check('H1 을 쓰지 않음 (프로젝트 제목 자리를 비워둠)',
          agents and not any(l.startswith('# ') for l in agents.split('\n')),
          agents)
    check('CLAUDE.md 는 본문이 아니라 import',
          claude and '@AGENTS.md' in claude and '쓰기 전에' not in claude, claude)


def case_preserves_human_text(tmp):
    print('case_preserves_human_text:')
    make_repo(tmp)
    emit(tmp, '--agents-md')
    agents = read(tmp, 'AGENTS.md')
    with open(os.path.join(tmp, 'AGENTS.md'), 'w', encoding='utf-8') as fh:
        fh.write('# my-project\n\n## 명령\n\n- `composer test`\n\n'
                 + agents + '\n## 배포\n\n사람이 쓴 내용.\n')
    with open(os.path.join(tmp, 'CLAUDE.md'), 'a', encoding='utf-8') as fh:
        fh.write('\n사람이 덧붙인 메모.\n')

    proc = emit(tmp, '--agents-md')
    check('재생성 성공', proc.returncode == 0, proc.stderr[:300])
    agents, claude = read(tmp, 'AGENTS.md'), read(tmp, 'CLAUDE.md')
    check('앞쪽 사람 내용 보존', '# my-project' in agents and 'composer test' in agents,
          agents[:200])
    check('뒤쪽 사람 내용 보존', '## 배포' in agents and '사람이 쓴 내용' in agents,
          agents[-200:])
    check('관리 블록은 하나만', agents.count(END) == 1, agents.count(END))
    check('CLAUDE.md 사람 메모 보존', '사람이 덧붙인 메모' in claude, claude)

    before = agents
    emit(tmp, '--agents-md')
    check('두 번 돌려도 같은 결과', read(tmp, 'AGENTS.md') == before)


def case_existing_manual_import(tmp):
    print('case_existing_manual_import:')
    make_repo(tmp)
    with open(os.path.join(tmp, 'CLAUDE.md'), 'w', encoding='utf-8') as fh:
        fh.write('@AGENTS.md\n\n## Claude 전용\n\n플랜 모드를 쓰세요.\n')
    proc = emit(tmp, '--agents-md')
    claude = read(tmp, 'CLAUDE.md')
    check('이미 import 가 있으면 CLAUDE.md 를 건드리지 않음',
          BEGIN not in claude and claude.count('@AGENTS.md') == 1, claude)
    check('그 사실을 알려줌', '이미' in proc.stdout, proc.stdout)


def case_follows_repo_eol(tmp):
    print('case_follows_repo_eol:')
    make_repo(tmp, crlf=True)
    emit(tmp, '--agents-md')
    agents = read(tmp, 'AGENTS.md')
    check('CRLF 레포에는 CRLF 로 씀',
          '\r\n' in agents and '\n' not in agents.replace('\r\n', ''),
          repr(agents[:80]))


LOCAL_RULE = """id: local-service-returns-dto
title: 서비스는 DTO 를 반환한다
severity: warn
applies_to:
  stack: ["*"]
  files: ["app/**/*.php"]
triggers:
  code_regex: ':\\s*array\\b'
context_injection: |
  서비스가 배열을 반환하고 있습니다. 이 레포는 DTO 를 반환합니다.
  호출부가 키 철자에 의존하지 않도록 DTO 로 감싸세요.
"""


def adopt_local_rule(tmp):
    base = os.path.join(tmp, '.claude', 'convention-rules')
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, 'local-service-returns-dto.yaml'), 'w',
              encoding='utf-8') as fh:
        fh.write(LOCAL_RULE)


def case_include_local(tmp):
    print('case_include_local:')
    make_repo(tmp)
    adopt_local_rule(tmp)

    emit(tmp, '--agents-md')
    check('기본 모드는 채택 규칙을 넣지 않음 (훅이 잡는다)',
          '서비스는 DTO' not in (read(tmp, 'AGENTS.md') or ''),
          read(tmp, 'AGENTS.md'))

    emit(tmp, '--agents-md', '--include', 'local')
    agents = read(tmp, 'AGENTS.md') or ''
    check('--include local 은 채택 규칙을 넣음', '서비스는 DTO' in agents, agents)
    # a context_injection is a wrapped block scalar: taking only its first
    # line cuts the advice mid-sentence and the agent has to guess the rest
    check('여러 줄 설명이 문장 단위로 들어감',
          'DTO 로 감싸세요' in agents, agents)
    check('관리 블록은 여전히 하나', agents.count(END) == 1, agents)


def case_budget_zero(tmp):
    print('case_budget_zero:')
    make_repo(tmp)
    emit(tmp, '--agents-md', '--include', 'all', '--budget', '1')
    capped = read(tmp, 'AGENTS.md') or ''
    check('예산을 넘으면 생략을 알림', '생략됨' in capped, capped)

    emit(tmp, '--agents-md', '--include', 'all', '--budget', '0')
    full = read(tmp, 'AGENTS.md') or ''
    bullets = [l for l in full.split('\n') if l.startswith('- ')]
    check('--budget 0 은 상한 해제 (0개가 아니라 전부)',
          len(bullets) > 12 and '생략됨' not in full, len(bullets))


CASES = [case_fresh_repo, case_preserves_human_text, case_existing_manual_import,
         case_follows_repo_eol, case_include_local, case_budget_zero]


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
    print('\n통과 — AGENTS.md / CLAUDE.md 생성')
    return 0


if __name__ == '__main__':
    sys.exit(main())
