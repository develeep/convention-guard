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

from . import rules as rulelib
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


# ---------------------------------------------------------------- plan

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
        if change.action not in ('convert', 'move') or change.problems:
            continue
        os.makedirs(os.path.dirname(change.dst), exist_ok=True)
        with open(change.dst, 'w', encoding='utf-8', newline='') as fh:
            fh.write(change.new_text)
        written.append(change.dst)
        if remove_sources and os.path.abspath(change.src) != os.path.abspath(change.dst):
            os.remove(change.src)
    return written
