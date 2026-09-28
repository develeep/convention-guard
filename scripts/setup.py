#!/usr/bin/env python3
"""Set a repo up for convention-guard and keep its instruction layer current.

    python3 setup.py init --stdout        # 이 레포에 맞춘 config.yaml 초안 미리보기
    python3 setup.py init                 # .claude/convention-guard/config.yaml 생성
    python3 setup.py emit                 # .claude/rules/convention-*.md (경로 스코핑)
    python3 setup.py emit --agents-md     # AGENTS.md 관리 블록 + CLAUDE.md 에 @AGENTS.md
    python3 setup.py emit --claude-md     # CLAUDE.md 관리 블록
    python3 setup.py emit --stdout        # 쓰지 않고 미리보기

Every applicable rule goes into context, even the ones the hook also checks
after the fact: an agent that knows the convention before writing produces
fewer blocks than one that learns it from the block. A rule's `prevent` line
is used when it has one, otherwise its title and the first line of its
message. Each linter that would run gets one line naming its command.

Only the managed block (between the begin/end markers) is owned by this
script. Anything a person writes around it survives regeneration.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as configlib, fmt, lint, pipeline, rules as rulelib  # noqa: E402
from lib.paths import git_toplevel, project_dir  # noqa: E402

BEGIN = '<!-- convention-guard:begin 자동 생성 — 규칙을 고친 뒤 setup.py emit 으로 재생성하세요 -->'
END = '<!-- convention-guard:end -->'
MARKER = 'convention-guard:begin'
HEADINGS = {'common': '공통', 'php': 'PHP', 'js': 'JavaScript / TypeScript', 'go': 'Go',
            'local': '이 레포 전용', 'user': '개인'}
AGENTS_IMPORT = '@AGENTS.md'
LINT_GROUP = 'lint'


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


def line_of(rule):
    """`**error** `core/x` 제목 — 안내`: the severity and id say which rule the hook
    will name if this line is not followed."""
    guidance = rule['prevent']
    if not guidance:
        # the first paragraph, not the first line: YAML wraps a sentence across lines
        first = rule['message'].strip().replace('\r\n', '\n').split('\n\n')[0]
        guidance = ' '.join(l.strip() for l in first.split('\n'))
    return '**%s** `%s` %s — %s' % (rule['severity'], rule['id'], rule['title'], guidance)


def linter_lines(root, cfg, stacks):
    """One line per linter that would actually run here."""
    if not cfg['linters']['enabled']:
        return []
    out = []
    for entry in stacks.lint:
        if not lint.binary_present(root, entry):
            continue
        argv = entry['cmd'].split() if isinstance(entry['cmd'], str) else entry['cmd']
        cmd = ' '.join(a for a in argv if a != '{files}')
        scope = ', '.join(entry.get('files') or []) or '모든 파일'
        line = '`%s` 가 %s 를 검사합니다. 끝내기 전에 통과시키세요.' % (cmd, scope)
        if line not in out:
            out.append(line)
    return out


def pick(root):
    cfg = configlib.load(root)
    stacks = pipeline.detect_stacks(root, cfg)
    ruleset = pipeline.load_rules(root, cfg, stacks)
    errors = [t for lv, t in list(cfg.notes) + list(ruleset.notes) if lv == 'error']
    picked = [dict(rule, prevent=line_of(rule)) for rule in ruleset.rules
              if rulelib.stack_ok(rule, stacks.tags, stacks.versions)]
    picked.sort(key=lambda r: (rulelib.severity_rank(r), r['id']))
    return picked, linter_lines(root, cfg, stacks), errors


def body_for(group, rules, heading_level=1, with_preface=True):
    out = ['%s %s 컨벤션 — 쓰기 전에 알아야 할 것' % ('#' * heading_level,
                                                  HEADINGS.get(group, group)), '']
    if with_preface:
        out += [preface(), '']
    out += ['- %s' % rule['prevent'] for rule in rules]
    return '\n'.join(out)


def lint_body(lines, heading_level=1):
    return '\n'.join(['%s 린터' % ('#' * heading_level), ''] + ['- %s' % l for l in lines])


def preface():
    return ('이 레포에 적용되는 컨벤션 전부입니다. 작업이 끝나면 훅이 같은 규칙으로 검사하므로, '
            '쓰기 전에 지키면 차단되지 않습니다.')


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
    rules, linters, errors = pick(root)
    for text in errors:
        fmt.eprint('error', text)
    if errors:
        return 2
    style = fmt.Style.for_stream()
    if not rules and not linters:
        print(style.finish(fmt.blocks(
            [fmt.header('setup emit', ['규칙 0개'], style=style)],
            [fmt.item_head('info', '컨텍스트에 넣을 규칙이 없습니다', style=style)],
            fmt.next_section([fmt.Step('적용 규칙을 확인하세요:', fmt.command('detect_stack.py'))],
                             style=style))))
        return 0

    groups = {}
    for rule in rules:
        groups.setdefault(group_of(rule), []).append(rule)

    if args.agents_md or args.claude_md:
        # one document has no path scoping: every line loads in every session
        parts = [body_for(g, rs, heading_level=2, with_preface=False)
                 for g, rs in sorted(groups.items())]
        if linters:
            parts.append(lint_body(linters, heading_level=2))
        body = '\n\n'.join([preface()] + parts)
        block = managed(body)
        target = 'AGENTS.md' if args.agents_md else 'CLAUDE.md'
        if args.stdout:
            print('===== %s =====\n%s' % (target, block))
            return 0
        write_managed(os.path.join(root, target), block)
        written = ['  %s  (관리 블록)' % target]
        if args.agents_md and ensure_import(os.path.join(root, 'CLAUDE.md')):
            written.append('  CLAUDE.md  (%s 가져오기 추가)' % AGENTS_IMPORT)
        print(style.finish(fmt.blocks(
            [fmt.header('setup emit --%s' % ('agents-md' if args.agents_md else 'claude-md'),
                        ['규칙 %d개' % len(rules), '린터 %d개' % len(linters)], style=style)],
            [fmt.section('쓴 파일', style=style)] + written)))
        return 0

    files = {}
    for group, group_rules in sorted(groups.items()):
        globs = []
        for rule in group_rules:
            # a paired rule without `files` still only concerns its when_changed paths
            reach = rule['files'] or (rule['when_changed'] if rule['kind'] == 'paired' else [])
            if not reach:
                globs = []          # one global rule makes the whole file global
                break
            globs += [g for g in reach if g not in globs]
        front = ['---', 'paths:'] + ['  - "%s"' % g for g in globs] + ['---', ''] if globs else []
        block = managed(body_for(group, group_rules))
        files['convention-%s.md' % group] = '\n'.join(front) + block
    if linters:
        files['convention-%s.md' % LINT_GROUP] = managed(lint_body(linters))

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
    print(style.finish(fmt.blocks(
        [fmt.header('setup emit', ['규칙 %d개' % len(rules), '파일 %d개' % len(written)],
                    style=style)],
        [fmt.section('쓴 파일', style=style)] + ['  %s' % rel for rel in written],
        [fmt.section('지운 파일', '더 이상 해당 규칙이 없습니다', style=style)]
        + ['  %s' % os.path.relpath(rel, root) for rel in removed] if removed else [],
        fmt.next_section([fmt.Step('paths: 프론트매터가 붙은 파일은 그 경로의 파일을 읽을 때 컨텍스트에 '
                                   '들어갑니다. 커밋해 팀과 공유하세요.')], style=style))))
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
        fmt.eprint('error', '%s 가 있습니다 — 새로 만들지 말고 scripts/migrate.py 로 옮기세요'
                   % rulelib.LEGACY_DIRNAME)
        return 2
    target = os.path.join(rulelib.repo_dir(root), 'config.yaml')
    text = draft_config(root)
    if args.stdout:
        print(text)
        return 0
    if os.path.exists(target) and not args.force:
        fmt.eprint('error', '이미 있습니다: %s (덮어쓰려면 --force, 미리보기는 --stdout)' % target)
        return 1
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as fh:
        fh.write(text)
    style = fmt.Style.for_stream()
    print(style.finish(fmt.blocks(
        [fmt.header('setup init', ['%s 씀' % os.path.relpath(target, root).replace(os.sep, '/')],
                    style=style)],
        fmt.next_section([fmt.Step('적용 규칙을 확인하세요:', fmt.command('detect_stack.py')),
                          fmt.Step('최근 변경분을 측정하세요:',
                                   fmt.command('scan.py', '--range', 'HEAD~20..HEAD'))],
                         style=style))))
    return 0


def main():
    parser = argparse.ArgumentParser(description='convention-guard 레포 설정 도구')
    sub = parser.add_subparsers(dest='command')
    p_init = sub.add_parser('init', help='이 레포에 맞춘 config.yaml 초안을 만듭니다')
    p_init.add_argument('--stdout', action='store_true', help='쓰지 않고 출력만')
    p_init.add_argument('--force', action='store_true', help='기존 config.yaml 을 덮어씁니다')
    p_init.add_argument('--cwd')
    p_emit = sub.add_parser('emit', help='적용 규칙 전부와 린터를 에이전트 컨텍스트 문서로 내보냅니다')
    p_emit.add_argument('--out', default='.claude/rules', help='규칙 파일 디렉터리')
    target = p_emit.add_mutually_exclusive_group()
    target.add_argument('--agents-md', action='store_true', help='AGENTS.md 관리 블록으로')
    target.add_argument('--claude-md', action='store_true', help='CLAUDE.md 관리 블록으로')
    p_emit.add_argument('--stdout', action='store_true', help='쓰지 않고 출력만')
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
