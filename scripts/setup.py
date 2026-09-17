#!/usr/bin/env python3
"""Set a repo up for convention-guard and keep its instruction layer current.

    python3 setup.py init --stdout        # 이 레포에 맞춘 config.yaml 초안 미리보기
    python3 setup.py init                 # .claude/convention-guard/config.yaml 생성
    python3 setup.py emit                 # .claude/rules/convention-*.md (경로 스코핑)
    python3 setup.py emit --agents-md     # AGENTS.md 관리 블록 + CLAUDE.md 에 @AGENTS.md
    python3 setup.py emit --claude-md     # CLAUDE.md 관리 블록
    python3 setup.py emit --hook          # SessionStart 훅 JSON
    python3 setup.py emit --stdout        # 쓰지 않고 미리보기

Instruction vs. verification: the hook catches what can be checked after the
fact, so only rules that carry a `prevent` line -- things expensive to undo
once written -- go into context. Everything else stays out, because a long
list of mechanically-checkable rules buried in context gets ignored anyway.

Only the managed block (between the begin/end markers) is owned by this
script. Anything a person writes around it survives regeneration.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, lint, pipeline, rules as rulelib  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402

BEGIN = '<!-- convention-guard:begin 자동 생성 — 규칙을 고친 뒤 setup.py emit 으로 재생성하세요 -->'
END = '<!-- convention-guard:end -->'
MARKER = 'convention-guard:begin'
HEADINGS = {'common': '공통', 'php': 'PHP', 'js': 'JavaScript / TypeScript', 'go': 'Go',
            'local': '이 레포 전용', 'user': '개인'}
AGENTS_IMPORT = '@AGENTS.md'
# Past a dozen lines per file, prevention lines stop being read as rules and
# start being read as noise.
DEFAULT_BUDGET = 12


def group_of(rule):
    """Where a rule's context line belongs. The id decides: an overridden core
    rule has source "core<-local" but is still scoped by its stack."""
    prefix = rule['id'].split('/')[0]
    if prefix != 'core':
        return prefix
    # an override file lives in the repo; the rule's home is still the core file
    origin = rule.get('patched_from') or rule['path']
    parts = origin.replace(os.sep, '/').split('/rules/')
    head = parts[-1].split('/')[0] if len(parts) > 1 else '_common'
    return 'common' if head.startswith('_') else head


def pick(root, all_severities=False):
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, cfg, stacks)
    errors = [t for lv, t in list(cfg.notes) + list(ruleset.notes) if lv == 'error']
    picked = []
    for rule in ruleset.rules:
        if not rulelib.stack_ok(rule, stacks.tags, stacks.versions):
            continue
        if rule['prevent']:
            picked.append(rule)
        elif all_severities and rule['severity'] == 'error':
            picked.append(dict(rule, prevent='%s — %s' % (rule['title'],
                                                          rule['message'].split('\n')[0])))
    return sorted(picked, key=lambda r: (rulelib.severity_rank(r), r['id'])), errors


def body_for(group, rules, budget, heading_level=1, with_preface=True):
    out = ['%s %s 컨벤션 — 쓰기 전에 알아야 할 것' % ('#' * heading_level,
                                                  HEADINGS.get(group, group)), '']
    if with_preface:
        out += [preface(), '']
    out += ['- %s' % rule['prevent'] for rule in rules[:budget]]
    if len(rules) > budget:
        out += ['', '<!-- 예산(%d개) 초과로 %d개 생략됨 -->' % (budget, len(rules) - budget)]
    return '\n'.join(out)


def preface():
    return ('기계적으로 판정되는 규칙은 작업이 끝날 때 훅이 검사하므로 여기 적지 않습니다. '
            '아래는 나중에 잡기 어렵거나, 잡혔을 때 되돌리는 비용이 큰 것들입니다.')


def managed(body):
    return '%s\n\n%s\n\n%s' % (BEGIN, body.strip(), END)


def newline_of(text):
    return '\r\n' if '\r\n' in text else '\n'


def write_managed(path, block):
    """Replace only our block; keep the file's own line endings."""
    existing = ''
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8', newline='') as fh:
            existing = fh.read()
    nl = newline_of(existing) if existing else '\n'
    norm = existing.replace('\r\n', '\n')
    start = norm.find('<!-- %s' % MARKER)
    if start != -1 and END in norm[start:]:
        end = norm.index(END, start) + len(END)
        merged = norm[:start] + block + norm[end:]
    elif norm.strip():
        merged = norm.rstrip('\n') + '\n\n' + block + '\n'
    else:
        merged = block + '\n'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(merged.replace('\n', nl))
    return existing != merged.replace('\n', nl)


def ensure_import(claude_md):
    """CLAUDE.md pulls AGENTS.md in with one import line, so the content lives
    in one place that other agent tools also read."""
    text = ''
    if os.path.isfile(claude_md):
        with open(claude_md, 'r', encoding='utf-8', newline='') as fh:
            text = fh.read()
    if any(line.strip() == AGENTS_IMPORT for line in text.splitlines()):
        return False
    return write_managed(claude_md, managed(AGENTS_IMPORT))


def emit(args):
    root = git_toplevel(project_dir(args.cwd))
    rules, errors = pick(root, args.all_severities)
    for text in errors:
        print('[error] %s' % text, file=sys.stderr)
    if errors:
        return 2
    if not rules:
        print(json.dumps({}) if args.hook else
              '컨텍스트에 넣을 규칙이 없습니다. 규칙에 prevent 한 줄을 붙이세요.')
        return 0

    groups = {}
    for rule in rules:
        groups.setdefault(group_of(rule), []).append(rule)

    if args.hook:
        text = '\n\n'.join(body_for(g, rs, args.budget, with_preface=False)
                           for g, rs in sorted(groups.items()))
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                                 'additionalContext': text}},
                         ensure_ascii=False))
        return 0

    if args.agents_md or args.claude_md:
        # one document has no path scoping: every line loads in every session
        body = '\n\n'.join([preface()] + [body_for(g, rs, args.budget, heading_level=2,
                                                   with_preface=False)
                                          for g, rs in sorted(groups.items())])
        block = managed(body)
        target = 'AGENTS.md' if args.agents_md else 'CLAUDE.md'
        if args.stdout:
            print('===== %s =====\n%s' % (target, block))
            return 0
        write_managed(os.path.join(root, target), block)
        print('%s 관리 블록 갱신 — 규칙 %d개' % (target, len(rules)))
        if args.agents_md and ensure_import(os.path.join(root, 'CLAUDE.md')):
            print('CLAUDE.md 에 %s 가져오기를 추가했습니다' % AGENTS_IMPORT)
        return 0

    files = {}
    for group, group_rules in sorted(groups.items()):
        globs = []
        for rule in group_rules:
            if not rule['files']:
                globs = []          # one global rule makes the whole file global
                break
            globs += [g for g in rule['files'] if g not in globs]
        front = ['---', 'paths:'] + ['  - "%s"' % g for g in globs] + ['---', ''] if globs else []
        block = managed(body_for(group, group_rules, args.budget))
        files['convention-%s.md' % group] = '\n'.join(front) + block

    outdir = os.path.join(root, args.out)
    if args.stdout:
        for name, content in files.items():
            print('===== %s/%s =====\n%s\n' % (args.out, name, content))
        return 0
    written = []
    for name, content in files.items():
        path = os.path.join(outdir, name)
        _write_whole(path, content)
        written.append(os.path.relpath(path, root))
    removed = _remove_stale(outdir, set(files))
    print('규칙 %d개를 %d개 파일로 썼습니다:' % (len(rules), len(written)))
    for rel in written:
        print('  %s' % rel)
    for rel in removed:
        print('  (삭제) %s — 더 이상 해당 규칙이 없습니다' % os.path.relpath(rel, root))
    print('\npaths: 프론트매터가 붙은 파일은 그 경로의 파일을 읽을 때 컨텍스트에 들어갑니다.')
    return 0


def _write_whole(path, content):
    """Generated per-group files are ours end to end, frontmatter included --
    but a person may have added notes below the block, so those are kept."""
    tail = ''
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8', newline='') as fh:
            old = fh.read().replace('\r\n', '\n')
        if END in old:
            tail = old[old.index(END) + len(END):]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(content + (tail if tail.strip() else '\n'))


def _remove_stale(outdir, keep):
    removed = []
    if not os.path.isdir(outdir):
        return removed
    for name in sorted(os.listdir(outdir)):
        if not (name.startswith('convention-') and name.endswith('.md')) or name in keep:
            continue
        path = os.path.join(outdir, name)
        with open(path, 'r', encoding='utf-8') as fh:
            text = fh.read()
        # only a file that is nothing but our generated output; a person's
        # notes below the block mean it is theirs now
        if MARKER in text and END in text and not text[text.index(END) + len(END):].strip():
            os.remove(path)
            removed.append(path)
    return removed


# Directories that are almost always generated or frozen. Only the ones that
# exist are suggested, and only as comments: excluding code is a team call.
EXCLUDE_HINTS = ['legacy', 'app/Legacy', 'generated', 'gen', 'dist', 'build', 'storage',
                 'bootstrap/cache', 'public/build', '.next', 'coverage']
FORMATTER_MARKERS = ['pint.json', '.php-cs-fixer.php', '.php-cs-fixer.dist.php', 'biome.json',
                     '.prettierrc', '.eslintrc', '.eslintrc.js', '.eslintrc.json',
                     'eslint.config.js', 'eslint.config.mjs', '.golangci.yml', '.golangci.yaml']


def draft_config(root):
    """A commented starting config for this repo, based on what is detected."""
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, dict(cfg, presets='auto'), stacks)
    in_play = [r for r in ruleset.rules if rulelib.stack_ok(r, stacks.tags, stacks.versions)]
    superseded = sorted(r['id'] for r in in_play if rulelib.superseded(r, root))
    formatters = [m for m in FORMATTER_MARKERS if os.path.exists(os.path.join(root, m))]
    linters = [(' '.join(e['cmd']) if isinstance(e['cmd'], list) else e['cmd'], e.get('parse'))
               for e in stacks.lint if lint.binary_present(root, e)]
    hints = [d for d in EXCLUDE_HINTS if os.path.isdir(os.path.join(root, d))]

    out = ['# convention-guard 팀 설정 — setup.py init 이 만든 초안입니다.',
           '# 플러그인 기본값과 다른 키만 남기세요. 전체 키: docs/configuration.md',
           '#',
           '# 감지된 스택   : %s' % (', '.join(stacks.ids) or '(없음 — stacks 로 지정하세요)'),
           '# auto 프리셋   : %s' % (', '.join(ruleset.presets) or '-'),
           '# 적용 규칙     : %d개' % len(in_play)]
    for cmd, parse in linters:
        out.append('# 린터         : %s%s' % (cmd, '' if parse else '  ← parse 없음: 출력 전체로 차단'))
    if formatters:
        out.append('# 포맷터 설정  : %s (포맷 규칙 %d개가 물러남)' % (', '.join(formatters),
                                                                  len(superseded)))
    elif any(t in stacks.tags for t in ('php', 'js', 'go')):
        out.append('# 포맷터 설정  : 없음 — examples/formatters 의 설정을 먼저 들이는 편이 낫습니다')
    out += ['',
            '# 도입 첫 2~3주는 report 로 기록만 쌓고, log_report.py 로 확인한 뒤 fix 로 올리세요.',
            'mode: report',
            '',
            '# 구조·성능 규칙(의미 판정)까지 켜려면: [auto, architecture, performance]',
            'presets: auto',
            '']
    if not stacks.ids:
        out += ['# 감지 실패 — 이 레포의 스택을 직접 지정하세요. 예) [laravel]', 'stacks: []', '']
    out += ['# 끌 규칙 — 끄기 전에 severity 나 exclude 로 해결되는지 먼저 보고, 끄면 이유를 남기세요',
            'disable: []',
            '',
            '# 강도 조정. 예) core/php-line-too-long: warn',
            'severity: {}',
            '']
    out.append('# 검사하지 않을 경로. 예) ["legacy/**"]')
    if hints:
        out.append('# 이 레포에 있는 생성·레거시 후보: %s — 확인 후 필요한 것만 넣으세요'
                   % ', '.join('"%s/**"' % d for d in hints))
    out += ['exclude: []',
            '',
            'semantic_review:',
            '  enabled: false          # 켜면 후보가 있을 때만 convention-reviewer 에이전트가 판정',
            '']
    return '\n'.join(out)


def init(args):
    root = git_toplevel(project_dir(args.cwd))
    if rulelib.legacy_layout(root):
        print('%s 가 있습니다 — 새로 만들지 말고 scripts/migrate.py 로 옮기세요'
              % rulelib.LEGACY_DIRNAME, file=sys.stderr)
        return 2
    target = os.path.join(rulelib.repo_dir(root), 'config.yaml')
    text = draft_config(root)
    if args.stdout:
        print(text)
        return 0
    if os.path.exists(target) and not args.force:
        print('이미 있습니다: %s  (덮어쓰려면 --force, 미리보기는 --stdout)' % target,
              file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as fh:
        fh.write(text)
    print('썼습니다: %s' % os.path.relpath(target, root))
    print('다음: detect_stack.py 로 적용 규칙을 확인하고, scan.py 로 최근 변경분을 측정하세요.')
    return 0


def main():
    parser = argparse.ArgumentParser(description='convention-guard 레포 설정 도구')
    sub = parser.add_subparsers(dest='command')
    p_init = sub.add_parser('init', help='이 레포에 맞춘 config.yaml 초안을 만듭니다')
    p_init.add_argument('--stdout', action='store_true', help='쓰지 않고 출력만')
    p_init.add_argument('--force', action='store_true', help='기존 config.yaml 을 덮어씁니다')
    p_init.add_argument('--cwd')
    p_emit = sub.add_parser('emit', help='prevent 규칙을 에이전트 컨텍스트 문서로 내보냅니다')
    p_emit.add_argument('--out', default='.claude/rules', help='규칙 파일 디렉터리')
    target = p_emit.add_mutually_exclusive_group()
    target.add_argument('--agents-md', action='store_true', help='AGENTS.md 관리 블록으로')
    target.add_argument('--claude-md', action='store_true', help='CLAUDE.md 관리 블록으로')
    target.add_argument('--hook', action='store_true', help='SessionStart 훅 JSON 출력')
    p_emit.add_argument('--stdout', action='store_true', help='쓰지 않고 출력만')
    p_emit.add_argument('--budget', type=int, default=DEFAULT_BUDGET, help='그룹당 규칙 상한')
    p_emit.add_argument('--all-severities', action='store_true',
                        help='prevent 가 없는 error 규칙도 제목으로 포함')
    p_emit.add_argument('--cwd')
    args = parser.parse_args()
    if args.command == 'init':
        return init(args)
    if args.command == 'emit':
        return emit(args)
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
