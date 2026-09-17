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


CASES = [case_fresh_repo, case_preserves_human_text, case_existing_manual_import,
         case_follows_repo_eol]


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
