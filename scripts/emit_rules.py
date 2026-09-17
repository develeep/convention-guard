#!/usr/bin/env python3
"""Write the *preventive* subset of rules into .claude/rules/ so they are in
context while the agent writes code -- not only after it finishes.

Context and hook do different jobs and should not overlap:

    컨텍스트 = 예방 (쓰기 전에 안다)      훅 = 검출 (쓰고 나서 잡는다)

Dumping every rule into CLAUDE.md is the exact anti-pattern this plugin exists
to avoid: a long list of mechanically-checkable rules buried mid-context gets
ignored, and the hook was already going to catch those. So only rules where
*detection is hard but prevention is cheap* are emitted -- semantic rules by
default, plus anything marked `in_context: true`.

`.claude/rules/*.md` supports `paths:` frontmatter, so each generated file is
scoped to the globs its rules apply to. A Laravel file only enters context when
Claude actually touches PHP.

    python3 emit_rules.py                 # .claude/rules/ 에 쓰기
    python3 emit_rules.py --stdout        # 미리보기
    python3 emit_rules.py --claude-md     # CLAUDE.md 관리 블록으로
    python3 emit_rules.py --hook          # SessionStart 훅 JSON 으로
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import rules as rulelib, stack as stacklib  # noqa: E402
from lib.paths import plugin_root, project_dir  # noqa: E402

BEGIN = '<!-- convention-guard:begin 자동 생성 — 규칙 파일을 고친 뒤 재생성하세요 -->'
END = '<!-- convention-guard:end -->'
HEADINGS = {
    'common': '공통', 'php': 'PHP', 'js': 'JavaScript / TypeScript',
    'go': 'Go', 'local': '이 레포 전용', 'user': '개인',
}


def group_of(rule):
    """rules/php/laravel/x.yaml -> php.  로컬·개인 규칙은 소스로 묶습니다."""
    source = rule['source'].split('<-')[-1]
    if source != 'core':
        return source
    parts = rule['path'].replace(os.sep, '/').split('/rules/')
    if len(parts) < 2:
        return 'common'
    head = parts[-1].split('/')[0]
    return 'common' if head.startswith('_') else head


def should_emit(rule):
    if rule.get('in_context') is False:
        return False
    if rule.get('in_context') is True:
        return True
    # semantic rules can't be judged by pattern, so prevention is the only lever
    return rule.get('kind') == 'semantic'


def one_line(rule):
    if rule.get('context_line'):
        return rule['context_line']
    body = rule.get('injection') or rule.get('review_prompt') or ''
    for line in body.split('\n'):
        line = line.strip().lstrip('-').strip()
        if line and not line.startswith(('예)', '- ')):
            return re.sub(r'\s+', ' ', line)
    return rule['title']


def render(group, rules, paths, budget):
    out = []
    if paths:
        out.append('---')
        out.append('paths:')
        for pattern in paths:
            out.append('  - "%s"' % pattern)
        out.append('---')
    out.append(BEGIN)
    out.append('')
    out.append('# %s 컨벤션 — 쓰기 전에 알아야 할 것' % HEADINGS.get(group, group))
    out.append('')
    out.append('기계적으로 판정되는 나머지 규칙은 작업 완료 시점에 훅이 검사하므로 여기 적지 '
               '않습니다. 아래는 나중에 잡기 어렵거나, 잡혔을 때 되돌리는 비용이 큰 것들입니다.')
    out.append('')
    for rule in rules[:budget]:
        # a hand-written context_line is already imperative; a title is a
        # violation name and reads wrong as prevention
        if rule.get('context_line'):
            out.append('- %s' % rule['context_line'])
        else:
            out.append('- **%s** — %s' % (rule['title'], one_line(rule)))
    if len(rules) > budget:
        out.append('')
        out.append('<!-- 예산(%d개) 초과로 %d개 생략됨 -->'
                   % (budget, len(rules) - budget))
    out.append('')
    out.append(END)
    return '\n'.join(out) + '\n'


def repo_newline(root, existing_path=None):
    """Follow the target repo's line endings, not the plugin's."""
    probes = [existing_path] if existing_path else []
    probes += [os.path.join(root, name) for name in
               ('AGENTS.md', 'CLAUDE.md', 'README.md', 'package.json',
                'composer.json', 'go.mod')]
    for path in probes:
        if path and os.path.isfile(path):
            with open(path, 'rb') as fh:
                head = fh.read(4000)
            if head:
                return '\r\n' if b'\r\n' in head else '\n'
    return '\n'


def write_managed(path, block, newline=None):
    """Replace only our block so hand-written content survives regeneration."""
    existing = ''
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as fh:
            existing = fh.read()
    if BEGIN in existing and END in existing:
        head = existing[:existing.index(BEGIN)]
        tail = existing[existing.index(END) + len(END):]
        merged = head + block.strip() + tail
    elif existing.strip():
        merged = existing.rstrip() + '\n\n' + block
    else:
        merged = block
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    eol = newline or repo_newline(os.path.dirname(path) or '.', path)
    merged = merged.replace('\r\n', '\n')
    if eol != '\n':
        merged = merged.replace('\n', eol)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(merged)


IMPORT_LINE = '@AGENTS.md'


def ensure_claude_import(root, newline):
    """CLAUDE.md points at AGENTS.md instead of holding a second copy.

    Claude Code expands `@AGENTS.md` at load time, and other tools read
    AGENTS.md directly, so the content lives in exactly one file.
    """
    target = os.path.join(root, 'CLAUDE.md')
    existing = ''
    if os.path.isfile(target):
        with open(target, 'r', encoding='utf-8') as fh:
            existing = fh.read()
    if BEGIN not in existing and re.search(r'(?m)^\s*@AGENTS\.md\s*$', existing):
        return None             # 이미 사람이 직접 import 해 두었습니다
    block = '\n'.join([
        BEGIN, '',
        '프로젝트 컨벤션은 AGENTS.md 에 있습니다. 도구가 달라도 같은 문서를 읽도록 '
        '여기서 불러옵니다.', '',
        IMPORT_LINE, '',
        END]) + '\n'
    write_managed(target, block, newline)
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='.claude/rules',
                        help='규칙 파일을 쓸 디렉터리 (기본 .claude/rules)')
    parser.add_argument('--stdout', action='store_true', help='쓰지 않고 출력만')
    parser.add_argument('--agents-md', action='store_true',
                        help='AGENTS.md 안의 관리 블록으로 (CLAUDE.md 는 @AGENTS.md import)')
    parser.add_argument('--claude-md', action='store_true',
                        help='파일 대신 CLAUDE.md 안의 관리 블록으로')
    parser.add_argument('--hook', action='store_true',
                        help='SessionStart 훅용 JSON 출력')
    parser.add_argument('--budget', type=int, default=12, help='파일당 규칙 상한')
    parser.add_argument('--all-severities', action='store_true',
                        help='in_context 표시와 무관하게 error 규칙까지 포함')
    parser.add_argument('--cwd')
    args = parser.parse_args()

    root = project_dir(args.cwd)
    detected = stacklib.detect(plugin_root(), args.cwd,
                               forced=(rulelib.load_repo_config(args.cwd) or {}).get('stacks'))
    all_rules, notes, _ = rulelib.load_all(args.cwd)
    for level, text in notes:
        if level == 'error':
            print('[error] %s' % text, file=sys.stderr)

    tags = set(detected['tags'])
    picked = []
    for rule in all_rules:
        stack = rule.get('stack') or []
        if stack and '*' not in stack and not (set(stack) & tags):
            continue
        if should_emit(rule) or (args.all_severities and rule['severity'] == 'error'):
            picked.append(rule)

    if not picked:
        msg = ('컨텍스트에 넣을 규칙이 없습니다. semantic 규칙을 만들거나 '
               '규칙에 in_context: true 를 붙이세요.')
        print(json.dumps({}) if args.hook else msg)
        return 0

    groups = {}
    for rule in sorted(picked, key=lambda r: (rulelib.severity_rank(r), r['id'])):
        groups.setdefault(group_of(rule), []).append(rule)

    blocks = {}
    for group, rules in sorted(groups.items()):
        paths = []
        for rule in rules:
            if not rule.get('files'):
                paths = []          # 하나라도 전역이면 무조건 로드
                break
            for pattern in rule['files']:
                if pattern not in paths:
                    paths.append(pattern)
        blocks[group] = render(group, rules, paths, args.budget)

    if args.hook:
        text = '\n'.join(b.split(END)[0].split(BEGIN)[-1].strip()
                         for b in blocks.values())
        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'SessionStart',
            'additionalContext': text}}, ensure_ascii=False))
        return 0

    if args.claude_md or args.agents_md:
        # One flat list, no path scoping: every line here loads in every
        # session. That is the trade for a single file the whole team -- and
        # every other agent tool -- can read in review.
        parts = []
        for block in blocks.values():
            body = block.split(BEGIN, 1)[-1].split(END)[0].strip()
            if body:
                # one document, so the group titles are sections under the
                # project's own H1, not H1s of their own
                parts.append(re.sub(r'(?m)^# ', '## ', body))
        block = '%s\n\n%s\n\n%s\n' % (BEGIN, '\n\n'.join(parts), END)
        if args.stdout:
            print(block)
            return 0
        name = 'AGENTS.md' if args.agents_md else 'CLAUDE.md'
        target = os.path.join(root, name)
        newline = repo_newline(root, target if os.path.isfile(target) else None)
        write_managed(target, block, newline)
        print('%s 관리 블록 갱신 — 규칙 %d개' % (name, len(picked)))
        if args.agents_md:
            imported = ensure_claude_import(root, newline)
            if imported:
                print('CLAUDE.md → @AGENTS.md import 블록 갱신')
            else:
                print('CLAUDE.md 는 이미 AGENTS.md 를 import 하고 있습니다')
        print('관리 블록 밖에 쓴 내용은 재생성해도 그대로 남습니다.')
        return 0

    if args.stdout:
        for group, block in blocks.items():
            print('===== %s/convention-%s.md =====' % (args.out, group))
            print(block)
        return 0

    outdir = os.path.join(root, args.out)
    written = []
    for group, block in blocks.items():
        path = os.path.join(outdir, 'convention-%s.md' % group)
        write_managed(path, block)
        written.append(os.path.relpath(path, root))
    print('규칙 %d개를 %d개 파일로 썼습니다:' % (len(picked), len(written)))
    for rel in written:
        print('  %s' % rel)
    print('\npaths: 프론트매터가 붙은 파일은 해당 파일을 읽을 때만 컨텍스트에 들어갑니다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
