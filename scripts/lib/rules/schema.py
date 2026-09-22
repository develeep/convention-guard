"""Rule file format 1.0: parse, validate, compile.

    id: laravel-controller-needs-validation
    title: store/update 컨트롤러 액션에 검증 없음
    severity: error                         # error | warn | info
    applies_to:
      stacks: [laravel]                     # required; ["*"] = every stack
      files: ["app/Http/Controllers/**/*.php"]
      exclude: ["**/vendor/**"]
      version: ">=10"
    superseded_by: [pint.json]
    detect:                                 # exactly one anchor
      when_line_added: 'public\\s+function\\s+(store|update)\\s*\\('
      must_contain_in_file: 'FormRequest|->validated\\(\\)'
    semantic_review:                        # optional: candidates go to a reviewer
      instruction: ...
      context: [current_function, imports]
    message: 위반일 때 에이전트가 읽는 지침
    prevent: 쓰기 전에 알아야 할 한 줄 (instruction layer 로 내보냄)
    fix:
      auto: {replace: '...', with: '...'}   # when_line_added 규칙만
    tests:
      match: [...]
      no_match: [...]

Anchors decide what makes a finding *this change's* responsibility:

    anchor              condition                 kind      the change owns...
    when_line_added     -                         line      the added line
    when_line_added     must_contain_in_file      requires  the added line; file lacks the requirement
    when_file_added     must_contain_in_file      absent    the new file; it lacks the requirement
    when_changed        require_changed           paired    the change set; no paired file changed
    file_regex          -                         file      a multi-line match overlapping changed lines
"""

import difflib
import hashlib
import json
import os
import re

from .select import SEVERITIES

ANCHORS = ('when_line_added', 'when_file_added', 'when_changed', 'file_regex')
CONDITIONS = ('must_contain_in_file', 'require_changed')
# Structure conditions (3.0): filters that ask what the match sits inside.
# `CONDITIONS` above was already taken by the anchor modifiers, hence the name.
STRUCTURE = ('not_in', 'in_scope', 'block_empty')
NOT_IN_VALUES = ('comment', 'string')
IN_SCOPE_VALUES = ('loop', 'function', 'class', 'catch')
# `absent` and `paired` describe what a file lacks -- there is no match to ask
# about -- and a `block_empty` on a line anchor would be ambiguous once blocks
# nest, so it rides on `file_regex` only (components.md §2, SR-21).
STRUCTURE_KINDS = ('line', 'requires', 'file')
CONTEXT_PROVIDERS = ('snippet', 'current_function', 'imports', 'changed_hunks',
                     'related_files')

TOP_KEYS = {'id', 'title', 'severity', 'applies_to', 'superseded_by', 'detect',
            'semantic_review', 'message', 'prevent', 'fix', 'tests', 'override', 'disabled'}
LEGACY_KEYS = {'triggers', 'context_injection', 'review_prompt', 'context_line',
               'in_context'}

# A reviewer needs the candidate's surroundings, not the file. 150 lines holds
# a long controller method plus its imports; past that the pack stops being
# "minimum sufficient" and starts being the file.
DEFAULT_MAX_CONTEXT_LINES = 150

# What a cached semantic verdict depends on: the gate that produced the
# candidate (`detect`) and the question the reviewer answered
# (`semantic_review`: instruction, context providers, context budget). Change
# either and every stored verdict for the rule is about a different question,
# so it must not be reused. Title, severity and message never move a verdict --
# renaming a rule must not throw the cache away.
SEMANTIC_IDENTITY = ('detect', 'semantic_review')


class RuleError(ValueError):
    pass


def _as_list(value, field):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise RuleError('%s 는 문자열 또는 문자열 목록이어야 합니다' % field)


def _structure(rule, spec, anchor):
    """Validate the structure conditions on `detect` (DR-01~DR-08).

    Everything here fails at load time rather than at detection time: a rule
    author who writes `not_in: [comments]` should hear about it while editing
    the rule, not by wondering why it never fires (US-09).
    """
    present = [key for key in STRUCTURE if spec.get(key) not in (None, False, '', [], ())]
    if not present:
        return                                  # DR-05 -- empty is simply none
    if rule['kind'] not in STRUCTURE_KINDS:
        raise RuleError('%s 에는 구조 조건을 붙일 수 없습니다 (%s)'
                        % (anchor, ', '.join(STRUCTURE)))
    for key, allowed in (('not_in', NOT_IN_VALUES), ('in_scope', IN_SCOPE_VALUES)):
        value = spec.get(key)
        if value in (None, [], ()):
            continue
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, (list, tuple)) or \
                not all(isinstance(item, str) for item in values):
            raise RuleError('%s 는 문자열이거나 문자열 목록이어야 합니다' % key)
        for item in values:
            if item not in allowed:
                raise RuleError('%s 의 알 수 없는 값: %s%s (%s)'
                                % (key, item, _did_you_mean(item, allowed),
                                   ', '.join(allowed)))
    if 'block_empty' in spec and not isinstance(spec['block_empty'], bool):
        raise RuleError('block_empty 는 true 또는 false 여야 합니다')
    if spec.get('block_empty') and rule['kind'] != 'file':
        raise RuleError('block_empty 는 file_regex 와만 씁니다')


def _did_you_mean(value, allowed):
    close = difflib.get_close_matches(value, allowed, n=1, cutoff=0.6)
    return " — '%s' 를 쓰셨나요?" % close[0] if close else ''


def _compile(pattern, flags, field):
    if not isinstance(pattern, str) or not pattern:
        raise RuleError('%s 는 비어 있지 않은 정규식 문자열이어야 합니다' % field)
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise RuleError('%s 정규식 오류: %s' % (field, exc))


def rule_id(raw, path, source):
    rid = str(raw.get('id') or os.path.splitext(os.path.basename(path))[0])
    return rid if '/' in rid else '%s/%s' % (source, rid)


def normalize(raw, path, source):
    """raw YAML mapping -> compiled rule dict. Raises RuleError."""
    if not isinstance(raw, dict):
        raise RuleError('최상위가 매핑이 아닙니다')
    legacy = sorted(LEGACY_KEYS & set(raw))
    if legacy:
        raise RuleError('0.x 규칙 형식입니다 (%s) — scripts/migrate.py 로 변환하세요'
                        % ', '.join(legacy))
    unknown = sorted(set(raw) - TOP_KEYS)
    if unknown:
        raise RuleError('알 수 없는 키: %s' % ', '.join(unknown))

    rid = rule_id(raw, path, source)
    severity = str(raw.get('severity') or 'warn').lower()
    if severity not in SEVERITIES:
        raise RuleError('severity 는 error / warn / info 중 하나입니다: %s' % severity)

    applies = raw.get('applies_to') or {}
    if not isinstance(applies, dict):
        raise RuleError('applies_to 는 매핑이어야 합니다')
    if 'stacks' not in applies:
        raise RuleError('applies_to.stacks 가 필요합니다 (전 스택이면 ["*"])')

    rule = {
        'id': rid,
        'title': str(raw.get('title') or rid),
        'severity': severity,
        'source': source,
        'path': path,
        'disabled': bool(raw.get('disabled')),
        'stack': [str(s) for s in _as_list(applies.get('stacks'), 'applies_to.stacks')],
        'files': _as_list(applies.get('files'), 'applies_to.files'),
        'exclude': _as_list(applies.get('exclude'), 'applies_to.exclude'),
        'version': applies.get('version'),
        'superseded_by': _as_list(raw.get('superseded_by'), 'superseded_by'),
        'message': str(raw.get('message') or '').strip(),
        'prevent': str(raw.get('prevent') or '').strip(),
        'tests': raw.get('tests') or {},
        'repo_exclude': [],
    }
    _detect(rule, raw.get('detect'))
    rule['review'] = _review(raw.get('semantic_review'))
    rule['definition_hash'] = definition_hash(rule) if rule['review'] else None
    rule['fix'] = _fix(raw.get('fix'), rule)
    tests = rule['tests']
    allowed = {'match', 'no_match', 'lang_prefix', 'lang'}
    if not isinstance(tests, dict) or set(tests) - allowed:
        raise RuleError('tests 에는 %s 만 둘 수 있습니다' % ' / '.join(sorted(allowed)))
    if 'lang_prefix' in tests and not isinstance(tests['lang_prefix'], bool):
        raise RuleError('tests.lang_prefix 는 true 또는 false 여야 합니다')
    if 'lang' in tests and not isinstance(tests['lang'], str):
        # a rule whose applies_to has no file glob cannot have its fixture
        # language inferred; it says so here instead
        raise RuleError('tests.lang 은 언어 식별자 문자열이어야 합니다')
    return rule


def _detect(rule, spec):
    if not isinstance(spec, dict) or not spec:
        raise RuleError('detect 가 필요합니다')
    unknown = sorted(set(spec) - set(ANCHORS) - set(CONDITIONS) - set(STRUCTURE)
                     - {'flags'})
    if unknown:
        raise RuleError('detect 의 알 수 없는 키: %s' % ', '.join(unknown))
    anchors = [a for a in ANCHORS if spec.get(a) not in (None, False, '', [])]
    if len(anchors) != 1:
        raise RuleError('detect 에는 앵커가 정확히 하나 있어야 합니다 (%s) — 지금: %s'
                        % (' / '.join(ANCHORS), ', '.join(anchors) or '없음'))
    anchor = anchors[0]
    flags = re.M | (re.I if 'i' in str(spec.get('flags') or '') else 0)
    must = spec.get('must_contain_in_file')
    required = spec.get('require_changed')
    rule['flags'] = str(spec.get('flags') or '')

    if anchor == 'when_line_added':
        if required:
            raise RuleError('require_changed 는 when_changed 와만 씁니다')
        rule['compiled_when'] = _compile(spec[anchor], flags, 'detect.when_line_added')
        if must:
            rule['kind'] = 'requires'
            rule['compiled_must'] = _compile(must, flags | re.S, 'detect.must_contain_in_file')
        else:
            rule['kind'] = 'line'
    elif anchor == 'when_file_added':
        if spec[anchor] is not True:
            raise RuleError('when_file_added 는 true 여야 합니다')
        if not must or required:
            raise RuleError('when_file_added 에는 must_contain_in_file 이 필요합니다')
        rule['kind'] = 'absent'
        rule['compiled_must'] = _compile(must, flags | re.S, 'detect.must_contain_in_file')
    elif anchor == 'when_changed':
        if not required or must:
            raise RuleError('when_changed 에는 require_changed 가 필요합니다')
        rule['kind'] = 'paired'
        rule['when_changed'] = _as_list(spec[anchor], 'detect.when_changed')
        rule['require_changed'] = _as_list(required, 'detect.require_changed')
    else:
        if must or required:
            raise RuleError('file_regex 에는 조건을 붙일 수 없습니다')
        rule['kind'] = 'file'
        rule['compiled_file'] = _compile(spec[anchor], flags | re.S, 'detect.file_regex')
    _structure(rule, spec, anchor)
    rule['detect'] = dict(spec)


def _review(spec):
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise RuleError('semantic_review 는 매핑이어야 합니다')
    unknown = sorted(set(spec) - {'instruction', 'context', 'max_context_lines'})
    if unknown:
        raise RuleError('semantic_review 의 알 수 없는 키: %s' % ', '.join(unknown))
    instruction = str(spec.get('instruction') or '').strip()
    if not instruction:
        raise RuleError('semantic_review.instruction 이 필요합니다')
    context = spec.get('context') or ['current_function']
    if not isinstance(context, list):
        raise RuleError('semantic_review.context 는 목록이어야 합니다')
    for item in context:
        name = next(iter(item)) if isinstance(item, dict) and len(item) == 1 else item
        if name not in CONTEXT_PROVIDERS:
            raise RuleError('알 수 없는 컨텍스트: %r (가능: %s)'
                            % (item, ', '.join(CONTEXT_PROVIDERS)))
        if name == 'related_files':
            opts = item.get('related_files') if isinstance(item, dict) else None
            if not isinstance(opts, dict) or not opts.get('symbol') or not opts.get('glob'):
                raise RuleError('related_files 에는 symbol 과 glob 이 필요합니다')
            _compile(opts['symbol'], re.M, 'related_files.symbol')
    try:
        limit = int(spec.get('max_context_lines') or DEFAULT_MAX_CONTEXT_LINES)
    except (TypeError, ValueError):
        raise RuleError('max_context_lines 는 정수여야 합니다')
    return {'instruction': instruction, 'context': context, 'max_context_lines': limit}


def definition_hash(rule):
    """10-hex fingerprint of the parts of a rule a semantic verdict depends on."""
    payload = {'detect': rule.get('detect'), 'semantic_review': rule.get('review')}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:10]


def _fix(spec, rule):
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - {'auto'}:
        raise RuleError('fix 에는 auto 만 둘 수 있습니다')
    auto = spec.get('auto')
    if auto is None:
        return None
    if rule['kind'] != 'line':
        raise RuleError('fix.auto 는 when_line_added 단독 규칙에만 쓸 수 있습니다')
    if not isinstance(auto, dict) or set(auto) != {'replace', 'with'}:
        raise RuleError('fix.auto 에는 replace 와 with 가 필요합니다')
    flags = re.I if 'i' in rule['flags'] else 0
    return {'pattern': auto['replace'],
            'compiled': _compile(auto['replace'], flags, 'fix.auto.replace'),
            'with': str(auto['with'])}
