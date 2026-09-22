"""0.x -> 1.0 conversion for rule files, repo config and the repo layout.

The conversion is line-based on purpose: rule and config files carry
comments that explain *why* ("disable 에는 이유를 남기세요"), and a parse ->
dump round trip would silently drop every one of them. Each converted rule is
then parsed with the 1.0 schema and compared field by field with how 0.x read
the original, so a conversion that changes meaning is refused, not written.
"""

import difflib
import os
import re

from . import rules as rulelib, structure
from .rules import fixtures
from .structure import conditions as conditionlib
from .yamlio import load as yaml_load

KEY_RE = re.compile(r'^(?P<indent> *)(?P<key>[A-Za-z_][\w-]*)\s*:(?P<rest>.*)$')
BLOCK_SCALAR_RE = re.compile(r'^\s*[|>][-+]?\d*\s*(#.*)?$')


# ---------------------------------------------------------------- line blocks

class Block:
    """One mapping entry at a given indent: its key line, the lines under it,
    and the comment/blank lines that sit directly above it."""

    def __init__(self, lead, key, rest, head, body, indent):
        self.lead, self.key, self.rest = lead, key, rest
        self.head, self.body, self.indent = head, body, indent

    def lines(self):
        return self.lead + [self.head] + self.body

    def value(self):
        """The inline value without a trailing comment."""
        return _strip_inline_comment(self.rest).strip()

    def comment(self):
        rest = self.rest
        stripped = _strip_inline_comment(rest)
        return rest[len(stripped):].strip()


def _strip_inline_comment(text):
    quote = None
    for i, c in enumerate(text):
        if quote:
            if c == quote:
                quote = None
        elif c in '"\'':
            quote = c
        elif c == '#' and (i == 0 or text[i - 1] in ' \t'):
            return text[:i].rstrip()
    return text.rstrip()


def split_blocks(lines, indent=0):
    """(preamble, [Block], trailer) for the entries at exactly `indent`."""
    blocks, pending, preamble = [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = KEY_RE.match(line)
        stripped = line.strip()
        if match and len(match.group('indent')) == indent and not stripped.startswith('#'):
            body = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == '' or nxt.lstrip().startswith('#'):
                    body.append(nxt)
                    j += 1
                    continue
                if len(nxt) - len(nxt.lstrip(' ')) > indent or nxt.lstrip().startswith('- ') \
                        and len(nxt) - len(nxt.lstrip(' ')) == indent and indent > 0:
                    body.append(nxt)
                    j += 1
                    continue
                break
            # comments/blanks at the end of a body belong to the next entry
            tail = []
            while body and (body[-1].strip() == '' or (body[-1].lstrip().startswith('#')
                                                       and _indent(body[-1]) <= indent)):
                tail.insert(0, body.pop())
            blocks.append(Block(pending, match.group('key'), match.group('rest'),
                                line, body, indent))
            pending = tail
            i = j
            continue
        if blocks or pending or stripped == '' or stripped.startswith('#'):
            pending.append(line)
        else:
            preamble.append(line)
        i += 1
    if not blocks:
        return preamble + pending, [], []
    return preamble, blocks, pending


def _indent(line):
    return len(line) - len(line.lstrip(' '))


def _reindent(lines, delta):
    return [(' ' * delta + line) if line.strip() else line for line in lines]


def _rename(block, new_key):
    block.head = '%s%s:%s' % (' ' * block.indent, new_key, block.rest)
    block.key = new_key
    return block


def _child_lines(block):
    """The block's body split into its own child entries."""
    return split_blocks(block.body, _child_indent(block))


def _child_indent(block):
    for line in block.body:
        if line.strip() and not line.lstrip().startswith('#'):
            return _indent(line)
    return block.indent + 2


def _join(preamble, blocks, trailer):
    out = list(preamble)
    for block in blocks:
        out += block.lines()
    return out + list(trailer)


def _synthetic(key, value, indent, comment=''):
    head = '%s%s: %s%s' % (' ' * indent, key, value, ('  ' + comment) if comment else '')
    return Block([], key, ' ' + value, head, [], indent)


# ---------------------------------------------------------------- rules

TRIGGER_RENAMES = {'code_regex': 'when_line_added', 'review_when': 'when_line_added'}
TEST_RENAMES = {'should_match': 'match', 'should_not_match': 'no_match'}


def needs_rule_migration(raw):
    return isinstance(raw, dict) and bool(rulelib.schema.LEGACY_KEYS & set(raw)) or (
        isinstance(raw, dict) and isinstance(raw.get('applies_to'), dict)
        and ('stack' in raw['applies_to'] or 'tags' in raw['applies_to']))


def convert_rule_text(text):
    """0.x rule YAML text -> 1.0 rule YAML text, comments preserved."""
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n')
    trailing_newline = lines and lines[-1] == ''
    if trailing_newline:
        lines = lines[:-1]
    preamble, blocks, trailer = split_blocks(lines, 0)
    keys = {b.key for b in blocks}
    is_override = 'override' in keys
    in_context_false = any(b.key == 'in_context' and b.value().lower() == 'false'
                           for b in blocks)

    out = []
    for block in blocks:
        if block.key == 'triggers':
            out.append(_convert_triggers(block))
        elif block.key == 'context_injection':
            out.append(_rename(block, 'message'))
        elif block.key == 'context_line':
            if not in_context_false:
                out.append(_rename(block, 'prevent'))
        elif block.key == 'in_context':
            continue
        elif block.key == 'review_prompt':
            out.append(_convert_review_prompt(block))
        elif block.key == 'applies_to':
            out.append(_convert_applies_to(block, is_override))
        elif block.key == 'tests':
            out.append(_convert_children(block, TEST_RENAMES))
        else:
            out.append(block)

    if 'applies_to' not in keys and not is_override:
        anchor = next((i for i, b in enumerate(out) if b.key in ('severity', 'title', 'id')), -1)
        synthetic = Block([], 'applies_to', '', 'applies_to:', ['  stacks: ["*"]'], 0)
        out.insert(anchor + 1, synthetic)

    result = _join(preamble, out, trailer)
    body = newline.join(result)
    return body + (newline if trailing_newline else '')


def _convert_children(block, renames):
    pre, children, post = _child_lines(block)
    for child in children:
        if child.key in renames:
            _rename(child, renames[child.key])
    block.body = _join(pre, children, post)
    return block


def _convert_applies_to(block, is_override):
    pre, children, post = _child_lines(block)
    has_stack = False
    for child in children:
        if child.key in ('stack', 'tags'):
            _rename(child, 'stacks')
            has_stack = True
    if not has_stack and not is_override:
        children.insert(0, _synthetic('stacks', '["*"]', _child_indent(block)))
    block.body = _join(pre, children, post)
    return block


def _convert_triggers(block):
    _rename(block, 'detect')
    pre, children, post = _child_lines(block)
    out = []
    for child in children:
        if child.key in TRIGGER_RENAMES:
            out.append(_rename(child, TRIGGER_RENAMES[child.key]))
        elif child.key == 'absent_in_new_file':
            flag = _synthetic('when_file_added', 'true', child.indent)
            flag.lead = child.lead
            child.lead = []
            out.append(flag)
            out.append(_rename(child, 'must_contain_in_file'))
        else:
            out.append(child)
    block.body = _join(pre, out, post)
    return block


def _convert_review_prompt(block):
    inner = Block([], 'instruction', block.rest, '  instruction:%s' % block.rest,
                  _reindent(block.body, 2), 2)
    return Block(block.lead, 'semantic_review', '', 'semantic_review:', inner.lines(), 0)


# -- verification: 0.x meaning == 1.0 meaning

def _v0_view(raw):
    applies = raw.get('applies_to') or {}
    trig = raw.get('triggers') or {}
    stack = applies.get('stack') or applies.get('tags') or []
    stack = [stack] if isinstance(stack, str) else list(stack)
    if raw.get('in_context') is False:
        prevent = ''
    else:
        prevent = (raw.get('context_line') or '').strip()
    if trig.get('review_when'):
        anchor = ('line', trig['review_when'], trig.get('must_contain_in_file'))
    elif trig.get('when_changed') or trig.get('require_changed'):
        anchor = ('paired', _lst(trig.get('when_changed')), _lst(trig.get('require_changed')))
    elif trig.get('when_line_added'):
        anchor = ('line', trig['when_line_added'], trig.get('must_contain_in_file'))
    elif trig.get('absent_in_new_file'):
        anchor = ('absent', trig['absent_in_new_file'])
    elif trig.get('file_regex'):
        anchor = ('file', trig['file_regex'])
    else:
        anchor = ('line', trig.get('code_regex'), None)
    tests = raw.get('tests') or {}
    return {
        'severity': str(raw.get('severity') or 'warn').lower(),
        'title': raw.get('title'),
        'stack': stack or ['*'],
        'files': _lst(applies.get('files')), 'exclude': _lst(applies.get('exclude')),
        'version': applies.get('version'),
        'superseded_by': _lst(raw.get('superseded_by')),
        'anchor': anchor, 'flags': str(trig.get('flags') or ''),
        'message': (raw.get('context_injection') or '').strip(),
        'prevent': prevent,
        'review': (raw.get('review_prompt') or '').strip() or None,
        'match': tests.get('should_match') or [], 'no_match': tests.get('should_not_match') or [],
    }


def _v1_view(raw):
    applies = raw.get('applies_to') or {}
    det = raw.get('detect') or {}
    if det.get('when_changed'):
        anchor = ('paired', _lst(det.get('when_changed')), _lst(det.get('require_changed')))
    elif det.get('when_line_added'):
        anchor = ('line', det['when_line_added'], det.get('must_contain_in_file'))
    elif det.get('when_file_added'):
        anchor = ('absent', det.get('must_contain_in_file'))
    elif det.get('file_regex'):
        anchor = ('file', det['file_regex'])
    else:
        anchor = None
    tests = raw.get('tests') or {}
    review = raw.get('semantic_review') or {}
    return {
        'severity': str(raw.get('severity') or 'warn').lower(),
        'title': raw.get('title'),
        'stack': _lst(applies.get('stacks')),
        'files': _lst(applies.get('files')), 'exclude': _lst(applies.get('exclude')),
        'version': applies.get('version'),
        'superseded_by': _lst(raw.get('superseded_by')),
        'anchor': anchor, 'flags': str(det.get('flags') or ''),
        'message': (raw.get('message') or '').strip(),
        'prevent': (raw.get('prevent') or '').strip(),
        'review': (review.get('instruction') or '').strip() or None,
        'match': tests.get('match') or [], 'no_match': tests.get('no_match') or [],
    }


def _lst(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def verify_rule(old_text, new_text, path='rule.yaml', source='local'):
    """[] when the conversion preserved meaning, else human-readable differences."""
    problems = []
    try:
        old = yaml_load(old_text) or {}
        new = yaml_load(new_text) or {}
    except Exception as exc:
        return ['변환 결과를 YAML 로 읽을 수 없습니다: %s' % exc]
    if rulelib.schema.LEGACY_KEYS & set(new):
        problems.append('0.x 키가 남아 있습니다: %s'
                        % ', '.join(sorted(rulelib.schema.LEGACY_KEYS & set(new))))
    if old.get('override'):
        return problems           # partial patch: validated once merged into its target
    try:
        rulelib.normalize(new, path, source)
    except rulelib.RuleError as exc:
        problems.append('1.0 스키마 검증 실패: %s' % exc)
    before, after = _v0_view(old), _v1_view(new)
    for key in before:
        if before[key] != after[key]:
            problems.append('%s 가 바뀜: %r -> %r' % (key, before[key], after[key]))
    return problems


# ---------------------------------------------------------------- config

CONFIG_MOVES = {
    'max_rules': ('limits', 'max_error_rules'),
    'max_warns': ('limits', 'max_warn_rules'),
    'max_hits_per_rule': ('limits', 'max_locations_per_rule'),
    'max_consecutive_blocks': ('limits', 'max_consecutive_blocks'),
    'max_blocks_per_session': ('limits', 'max_consecutive_blocks'),
    'run_linters': ('linters', 'enabled'),
    'lint_timeout': ('linters', 'timeout'),
    'base_ref': ('scope', 'base_ref'),
    'semantic_review': ('semantic_review', 'enabled'),
    'max_semantic_rules': ('semantic_review', 'max_candidates'),
}
CONFIG_DROPS = {
    'max_semantic_reviews_per_session': '세션당 판정 횟수 대신 후보 지문으로 중복 판정을 막습니다',
}


def convert_config_text(text):
    """0.x repo config text -> (1.0 text, [notes])."""
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.replace('\r\n', '\n').split('\n')
    trailing_newline = lines and lines[-1] == ''
    if trailing_newline:
        lines = lines[:-1]
    preamble, blocks, trailer = split_blocks(lines, 0)
    notes, kept, groups = [], [], {}
    for block in blocks:
        if block.key == 'block_level':
            mode = 'report' if block.value().strip('\'"') == 'report' else 'fix'
            head = 'mode: %s' % mode + ('  %s' % block.comment() if block.comment() else '')
            kept.append(Block(block.lead, 'mode', ' ' + mode, head, block.body, 0))
            notes.append('block_level: %s -> mode: %s' % (block.value(), mode))
        elif block.key in CONFIG_MOVES and not (block.key == 'semantic_review'
                                               and not block.value()):
            group, key = CONFIG_MOVES[block.key]
            lead = [line for line in block.lead if line.strip()]
            child = Block(lead, key, block.rest, '  %s:%s' % (key, block.rest), [], 2)
            groups.setdefault(group, []).append(child)
            notes.append('%s -> %s.%s' % (block.key, group, key))
        elif block.key in CONFIG_DROPS:
            kept.append(Block(block.lead, '#', '', '# (1.0 에서 삭제됨) %s:%s — %s'
                              % (block.key, block.rest, CONFIG_DROPS[block.key]), [], 0))
            notes.append('%s 삭제 — %s' % (block.key, CONFIG_DROPS[block.key]))
        else:
            kept.append(block)
    out = _join(preamble, kept, trailer)
    if groups:
        out += ['', '# ---- scripts/migrate.py 가 0.x 설정에서 옮긴 값 ----']
        for group in ('scope', 'limits', 'linters', 'semantic_review'):
            if group in groups:
                out.append('%s:' % group)
                for child in groups[group]:
                    out += [line.strip() and ('  ' + line.lstrip()) or line
                            for line in child.lead] + [child.head]
    body = newline.join(out)
    return body + (newline if trailing_newline else ''), notes


# ------------------------------------------------- 1.x -> 3.0 structure conditions

# Tokens that mean "this rule is hunting for the very thing the condition
# would hide". The regex is never interpreted, only read: interpreting it
# needs a regex parser, and a parser that is wrong breaks someone's rule.
# Being wrong in the other direction only costs a rule that stays as it was.
COMMENT_TOKENS = ('//', '/\\*', '/*', '#', '--')
QUOTE_TOKENS = ('"', "'", '`')

BLOCKED_HELP = {
    'would_break': '이 규칙은 주석/문자열 자체를 찾습니다. 조건을 넣으면 탐지가 사라집니다',
    'no_fixture': '`tests.match` 를 하나 추가하면 변환이 안전한지 확인할 수 있습니다',
    'anchor_rejects': '이 앵커는 판정할 위치가 없어 구조 조건을 쓸 수 없습니다',
    'no_structure': '이 규칙이 겨냥하는 파일은 구조 분석이 없는 언어입니다. 조건을 넣어도 '
                    '걸러지는 것이 없습니다 — 지원 언어는 docs/rules.md 를 보세요',
}


class Verdict:
    """What to do with one rule, and why."""

    def __init__(self, rule_id, conditions=None, reasons=None, blocked=None, fixture=None):
        self.rule_id = rule_id
        self.conditions = conditions or {}
        self.reasons = reasons or []
        self.blocked = blocked
        self.fixture = fixture

    def help(self):
        return BLOCKED_HELP.get(self.blocked, self.blocked or '')


def _patterns(rule):
    """Every regex the rule carries, as the source text the author wrote."""
    detect = rule.get('detect') or {}
    return [v for k, v in detect.items()
            if isinstance(v, str) and k not in conditionlib.CONDITION_KEYS]


def judge(rule):
    """Which structure conditions this rule can safely carry (MR-01..MR-07)."""
    rid = rule.get('id')
    if rule['kind'] in ('absent', 'paired'):
        return Verdict(rid, blocked='anchor_rejects')
    if conditionlib.has_conditions(rule):
        # the author already decided; two runs must agree (MR-02)
        return Verdict(rid, reasons=['이미 구조 조건이 있어 건드리지 않습니다'])
    samples = (rule.get('tests') or {}).get('match') or []
    if not samples:
        return Verdict(rid, blocked='no_fixture')
    text, language = fixtures.synthesise(rule, samples[0])
    if not structure.analyze(text, language).ok:
        # `passes_conditions` keeps a match when the file did not parse (D5),
        # so validation would pass a condition that filters nothing (MR-05b)
        return Verdict(rid, blocked='no_structure')

    sources = _patterns(rule)
    targets, reasons = [], []
    if any(token in src for src in sources for token in COMMENT_TOKENS):
        reasons.append('정규식이 주석 토큰을 포함합니다 — 주석을 보는 규칙일 수 있어 '
                       '`comment` 는 넣지 않습니다')
    else:
        targets.append('comment')
        reasons.append('정규식에 주석 토큰이 없어 주석 안의 매치를 걸러도 안전합니다')
    if any(token in src for src in sources for token in QUOTE_TOKENS):
        reasons.append('정규식이 따옴표를 포함합니다 — 문자열 안을 보는 규칙일 수 있어 '
                       '`string` 은 넣지 않습니다')
    else:
        targets.append('string')
        reasons.append('정규식에 따옴표가 없어 문자열 안의 매치를 걸러도 안전합니다')

    if not targets:
        return Verdict(rid, blocked='would_break')
    return Verdict(rid, conditions={'not_in': targets}, reasons=reasons)


def build_text(text, verdict):
    """The rule file with the condition line inserted under `detect`.

    Line based on purpose, like every other conversion here: a parse and dump
    round trip would take the author's comments with it (MR-22).
    """
    if not verdict.conditions:
        return text
    lines = text.split('\n')
    preamble, blocks, trailer = split_blocks(lines)
    for block in blocks:
        if block.key != 'detect':
            continue
        indent = _child_indent(block)
        head, children, tail = _child_lines(block)
        for key, value in verdict.conditions.items():
            rendered = '[%s]' % ', '.join(value) if isinstance(value, list) else str(value)
            added = _synthetic(key, rendered, indent)
            added.lead = ['%s# 3.0: 주석·문자열 안의 매치는 위반이 아닙니다 (migrate.py 가 추가)'
                          % (' ' * indent)]
            children.append(added)
        block.body = _join(head, children, tail)
        break
    return '\n'.join(_join(preamble, blocks, trailer))


def _reparse(old_rule, new_text):
    return rulelib.normalize(yaml_load(new_text), old_rule['path'], old_rule['source'])


def validate(old_rule, new_text):
    """Does the rewritten rule still judge the rule's OWN fixtures the same way?

    Only the fixtures the author already wrote count here. Checking a
    condition against a fixture the tool generated to suit it proves nothing,
    so generation waits until this has passed (MR-10).
    """
    try:
        new_rule = _reparse(old_rule, new_text)
    except Exception as exc:                            # noqa: BLE001
        return ['변환된 규칙을 읽을 수 없습니다: %s' % exc]
    hit = fixtures.matcher(new_rule)                    # the suite's matcher (MR-09)
    tests = old_rule.get('tests') or {}
    problems = []
    for sample in tests.get('match') or []:
        if not hit(sample):
            problems.append('match 픽스처 %r 가 조건 적용 후 걸리지 않습니다' % sample)
    for sample in tests.get('no_match') or []:
        if hit(sample):
            problems.append('no_match 픽스처 %r 가 걸립니다' % sample)
    return problems


# The comment token a generated fixture is wrapped in. `blade` shares PHP's.
FIXTURE_COMMENT = {'php': '//', 'blade': '//', 'js': '//', 'go': '//', 'java': '//',
                   'rust': '//', 'c': '//', 'py': '#'}


def _fixture_lines(indent, sample):
    """A block scalar item, indented the way the bundled rules write theirs."""
    return (['%s  - |' % (' ' * indent)]
            + ['%s    %s' % (' ' * indent, line) for line in sample.split('\n')])


def grow_fixture(new_text, old_rule, verdict):
    """(text with a false-positive fixture added, problems) -- or (None, []).

    The rule said comments are not violations; this writes down a comment that
    used to be one. If the new fixture still fires the condition does not work
    and the whole conversion comes off (MR-11).
    """
    if 'comment' not in (verdict.conditions.get('not_in') or ()):
        return None, []
    samples = (old_rule.get('tests') or {}).get('match') or []
    token = FIXTURE_COMMENT.get(fixtures.fixture_language(old_rule))
    if not samples or not token:
        return None, []
    sample = '\n'.join('%s %s' % (token, line.strip())
                        for line in str(samples[0]).split('\n') if line.strip())

    lines = new_text.split('\n')
    preamble, blocks, trailer = split_blocks(lines)
    for block in blocks:
        if block.key != 'tests':
            continue
        head, children, tail = _child_lines(block)
        indent = _child_indent(block)
        for child in children:
            if child.key != 'no_match':
                continue
            child.body = child.body + _fixture_lines(indent, sample)
            break
        else:
            added = _synthetic('no_match', '', indent)
            added.rest, added.head = '', '%sno_match:' % (' ' * indent)
            added.body = _fixture_lines(indent, sample)
            children.append(added)
        block.body = _join(head, children, tail)
        break
    grown = '\n'.join(_join(preamble, blocks, trailer))

    # re-run the whole check with the new fixture in place (FD 7, step 4)
    try:
        new_rule = _reparse(old_rule, grown)
    except Exception as exc:                            # noqa: BLE001
        return None, ['픽스처를 추가한 규칙을 읽을 수 없습니다: %s' % exc]
    problems = validate(old_rule, grown)
    if fixtures.matcher(new_rule)(sample):
        problems.append('생성한 오탐 픽스처가 여전히 걸립니다 — 조건이 동작하지 않습니다')
    return grown, problems


# ---------------------------------------------------------------- plan

# One vocabulary of actions, read from three places: `apply()` here, and
# `actionable` / `show()` in scripts/migrate.py. They used to each spell the
# list out, so adding `enhance` meant three edits and forgetting one of them
# failed quietly -- an unwritten file, a wrong exit code, a KeyError.
WRITABLE = ('convert', 'move', 'enhance')
LABELS = {'convert': '변환', 'move': '이동', 'leave': '남김', 'error': '실패',
          'enhance': '조건 추가'}


class Change:
    def __init__(self, action, src, dst, old_text=None, new_text=None, problems=None,
                 notes=None):
        self.action, self.src, self.dst = action, src, dst
        self.old_text, self.new_text = old_text, new_text
        self.problems = problems or []
        self.notes = notes or []

    def diff(self):
        if self.old_text is None or self.new_text is None or self.old_text == self.new_text:
            return ''
        return ''.join(difflib.unified_diff(
            self.old_text.splitlines(True), self.new_text.splitlines(True),
            fromfile=self.src, tofile=self.dst))


def _read(path):
    with open(path, 'r', encoding='utf-8', newline='') as fh:
        return fh.read()


def plan_rules_dir(src_dir, dst_dir, source='local'):
    changes = []
    for path in rulelib.iter_rule_files(src_dir):
        name = os.path.basename(path)
        if name in ('config.yaml', 'config.yml', 'dismissed.yaml', 'dismissed.yml'):
            continue
        rel = os.path.relpath(path, src_dir)
        dst = os.path.join(dst_dir, rel)
        text = _read(path)
        try:
            raw = yaml_load(text)
        except Exception as exc:
            changes.append(Change('error', path, dst, problems=['YAML 파싱 실패: %s' % exc]))
            continue
        if not needs_rule_migration(raw):
            if os.path.abspath(path) != os.path.abspath(dst):
                changes.append(Change('move', path, dst, text, text))
            continue
        new_text = convert_rule_text(text)
        changes.append(Change('convert', path, dst, text, new_text,
                              verify_rule(text, new_text, dst, source)))
    return changes


def plan_conditions(rules_dir, source='local'):
    """1.x -> 3.0: give each rule the structure conditions it can safely hold.

    Only rules the user owns. The bundled ones were gone through by hand,
    rule by rule, because the tool cannot see what a rule is *for* -- and for
    the same reason it only ever adds `not_in` (MR-03).
    """
    changes = []
    if not os.path.isdir(rules_dir):
        return changes
    for path in rulelib.iter_rule_files(rules_dir):
        name = os.path.basename(path)
        if name in ('config.yaml', 'config.yml', 'dismissed.yaml', 'dismissed.yml'):
            continue
        text = _read(path)
        try:
            rule = rulelib.normalize(yaml_load(text), path, source)
        except Exception as exc:                        # noqa: BLE001
            changes.append(Change('error', path, path, problems=['규칙을 읽을 수 없습니다: %s' % exc]))
            continue
        verdict = judge(rule)
        if verdict.blocked:
            changes.append(Change('leave', path, path,
                                  problems=['%s — %s' % (verdict.blocked, verdict.help())]))
            continue
        if not verdict.conditions:
            continue                                    # already decided; stay quiet (MR-02)
        new_text = build_text(text, verdict)
        problems = validate(rule, new_text)
        if not problems:
            grown, problems = grow_fixture(new_text, rule, verdict)
            if grown is not None and not problems:
                new_text = grown
        changes.append(Change('enhance', path, path, text, new_text,
                              problems, list(verdict.reasons)))
    return changes


def plan_repo(root):
    """Everything needed to bring a 0.x repo layout to 1.0."""
    old_dir = os.path.join(root, *rulelib.LEGACY_DIRNAME.split('/'))
    new_dir = rulelib.repo_dir(root)
    changes = []
    if not os.path.isdir(old_dir):
        return changes
    for name in ('config.yaml', 'config.yml'):
        src = os.path.join(old_dir, name)
        if os.path.isfile(src):
            text = _read(src)
            new_text, notes = convert_config_text(text)
            problems = []
            try:
                yaml_load(new_text)
            except Exception as exc:
                problems.append('변환된 config 를 읽을 수 없습니다: %s' % exc)
            changes.append(Change('convert', src, os.path.join(new_dir, 'config.yaml'),
                                  text, new_text, problems, notes))
            break
    for name in ('dismissed.yaml', 'dismissed.yml'):
        src = os.path.join(old_dir, name)
        if os.path.isfile(src):
            text = _read(src)
            changes.append(Change('move', src, os.path.join(new_dir, 'dismissed.yaml'),
                                  text, text))
            break
    rule_changes = []
    for entry in sorted(os.listdir(old_dir)):
        full = os.path.join(old_dir, entry)
        if entry in ('candidates',) or entry.startswith('.'):
            continue
        if os.path.isdir(full):
            # 0.x read rules recursively, so a `rules/` subdirectory was common
            target = os.path.join(new_dir, 'rules') if entry == 'rules'                 else os.path.join(new_dir, 'rules', entry)
            rule_changes += plan_rules_dir(full, target)
        elif entry.endswith(('.yaml', '.yml')) and not entry.startswith(('config.', 'dismissed.')):
            rule_changes += [c for c in plan_rules_dir(old_dir, os.path.join(new_dir, 'rules'))
                             if c.src == full]
    changes += rule_changes
    for dirpath, _dirs, files in os.walk(old_dir):
        for name in files:
            full = os.path.join(dirpath, name)
            if not any(c.src == full for c in changes):
                changes.append(Change('leave', full, None,
                                      notes=['1.0 이 읽지 않는 파일 — 직접 확인하세요']))
    return changes


def apply(changes, remove_sources=True):
    written = []
    for change in changes:
        if change.action not in WRITABLE or change.problems:
            continue
        os.makedirs(os.path.dirname(change.dst), exist_ok=True)
        with open(change.dst, 'w', encoding='utf-8', newline='') as fh:
            fh.write(change.new_text)
        written.append(change.dst)
        if remove_sources and os.path.abspath(change.src) != os.path.abspath(change.dst):
            os.remove(change.src)
    return written
