"""Layered rule loading: bundled (core) + repo-local (local) + user.

Precedence, lowest to highest:
  1. core   -- plugin's rules/**            id auto-namespaced "core/..."
  2. user   -- ~/.claude/convention-rules/  id auto-namespaced "user/..."
  3. local  -- <repo>/.claude/convention-rules/   id auto-namespaced "local/..."

A local file adds a rule when its id is new, and patches a core rule when it
carries `override: core/<id>` -- a partial merge, so a repo can relax one field
without copy-pasting the regex. Repo-wide switches live in
<repo>/.claude/convention-rules/config.yaml and cover the common cases
(turn a rule off, lower its severity, exclude a legacy directory).
"""

import os
import re

from .paths import plugin_root, project_dir, read_yaml
from .stack import version_ok

LOCAL_DIRNAME = os.path.join('.claude', 'convention-rules')
SEVERITIES = ('error', 'warn', 'info')


# ---------------------------------------------------------------- globs

def glob_re(pattern):
    out, i = ['(?s)\\A'], 0
    p = pattern.replace('\\', '/')
    if p.startswith('./'):
        p = p[2:]
    while i < len(p):
        c = p[i]
        if p.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif p.startswith('**', i):
            out.append('.*')
            i += 2
        elif c == '*':
            out.append('[^/]*')
            i += 1
        elif c == '?':
            out.append('[^/]')
            i += 1
        elif c == '{':
            end = p.find('}', i)
            if end == -1:
                out.append(re.escape(c))
                i += 1
            else:
                alts = p[i + 1:end].split(',')
                out.append('(?:%s)' % '|'.join(re.escape(a) for a in alts))
                i = end + 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append('\\Z')
    return re.compile(''.join(out))


def _match_any(patterns, relpath):
    for pat in patterns or []:
        if glob_re(pat).match(relpath):
            return True
    return False


# ---------------------------------------------------------------- loading

# not rules: the candidate catalog is what survey.py recommends *from*, and
# dismissed.yaml records judgments. Loading either as a rule would fire
# unadopted candidates in the hook.
NON_RULE_NAMES = ('config.yaml', 'config.yml', 'dismissed.yaml', 'dismissed.yml')
NON_RULE_DIRS = ('candidates',)


def _iter_rule_files(base, skip_dirs=NON_RULE_DIRS):
    if not base or not os.path.isdir(base):
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.') and d not in (skip_dirs or ())]
        for name in sorted(filenames):
            if name in NON_RULE_NAMES:
                continue
            if name.endswith(('.yaml', '.yml')):
                yield os.path.join(dirpath, name)


def _normalize(raw, path, source):
    applies = raw.get('applies_to') or {}
    triggers = raw.get('triggers') or {}
    rid = str(raw.get('id') or os.path.splitext(os.path.basename(path))[0])
    if '/' not in rid:
        rid = '%s/%s' % (source, rid)

    stack = applies.get('stack') or applies.get('tags') or []
    if isinstance(stack, str):
        stack = [stack]
    files = applies.get('files') or []
    if isinstance(files, str):
        files = [files]
    exclude = applies.get('exclude') or []
    if isinstance(exclude, str):
        exclude = [exclude]

    severity = str(raw.get('severity') or 'warn').lower()
    if severity not in SEVERITIES:
        severity = 'warn'

    superseded_by = raw.get('superseded_by') or []
    if isinstance(superseded_by, str):
        superseded_by = [superseded_by]

    return {
        'id': rid,
        'title': raw.get('title') or rid,
        'severity': severity,
        'source': source,
        'path': path,
        'override': raw.get('override'),
        'disabled': bool(raw.get('disabled')),
        'stack': [str(s) for s in stack],
        'files': files,
        'exclude': exclude,
        'version': applies.get('version'),
        'regex': triggers.get('code_regex'),
        'file_regex': triggers.get('file_regex'),
        'absent_regex': triggers.get('absent_in_new_file'),
        'when_line': triggers.get('when_line_added'),
        'must_contain': triggers.get('must_contain_in_file'),
        'when_changed': _as_list(triggers.get('when_changed')),
        'require_changed': _as_list(triggers.get('require_changed')),
        'review_when': triggers.get('review_when'),
        'review_prompt': (raw.get('review_prompt') or '').strip(),
        'in_context': raw.get('in_context'),
        'context_line': (raw.get('context_line') or '').strip(),
        'regex_flags': triggers.get('flags') or '',
        'superseded_by': [str(p) for p in superseded_by],
        'injection': (raw.get('context_injection') or '').strip(),
        'tests': raw.get('tests') or {},
    }


def _as_list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


_PATCHABLE = ('severity', 'stack', 'files', 'exclude', 'version', 'regex',
              'file_regex', 'absent_regex', 'when_line', 'must_contain',
              'when_changed', 'require_changed', 'review_when', 'review_prompt',
              'in_context', 'context_line', 'regex_flags', 'superseded_by',
              'injection', 'title', 'disabled', 'tests')


def _patch(base, patch, raw_keys):
    merged = dict(base)
    for key in _PATCHABLE:
        if key in raw_keys:
            merged[key] = patch[key]
    merged['source'] = '%s<-%s' % (base['source'], patch['source'])
    merged['path'] = patch['path']
    merged['patched_from'] = base['path']
    merged['base_severity'] = base['severity']
    return merged


def _raw_keys(raw):
    keys = set(raw.keys())
    applies = raw.get('applies_to') or {}
    triggers = raw.get('triggers') or {}
    if 'stack' in applies or 'tags' in applies:
        keys.add('stack')
    for k in ('files', 'exclude', 'version'):
        if k in applies:
            keys.add(k)
    for src, dst in (('code_regex', 'regex'), ('file_regex', 'file_regex'),
                     ('absent_in_new_file', 'absent_regex'),
                     ('when_line_added', 'when_line'),
                     ('must_contain_in_file', 'must_contain'),
                     ('when_changed', 'when_changed'),
                     ('require_changed', 'require_changed'),
                     ('review_when', 'review_when'),
                     ('flags', 'regex_flags')):
        if src in triggers:
            keys.add(dst)
    for key in ('review_prompt', 'in_context', 'context_line'):
        if key in raw:
            keys.add(key)
    if 'context_injection' in raw:
        keys.add('injection')
    return keys


def local_dir(cwd=None):
    return os.path.join(project_dir(cwd), LOCAL_DIRNAME)


def user_dir():
    return os.path.expanduser(os.path.join('~', '.claude', 'convention-rules'))


def load_repo_config(cwd=None):
    base = local_dir(cwd)
    for name in ('config.yaml', 'config.yml'):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            try:
                cfg = read_yaml(path) or {}
                cfg['_path'] = path
                return cfg
            except Exception as exc:
                return {'_path': path, '_error': str(exc)}
    return {}


def load_plugin_config(root=None):
    root = root or plugin_root()
    for name in ('config.yaml', 'config.yml'):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            try:
                return read_yaml(path) or {}
            except Exception:
                return {}
    return {}


def load_all(cwd=None, root=None, include_disabled=False):
    """Load every layer and return (rules, notes, repo_config). Notes feed --explain."""
    root = root or plugin_root()
    notes = []
    by_id = {}
    order = []

    def ingest(base, source):
        for path in _iter_rule_files(base):
            try:
                raw = read_yaml(path) or {}
            except Exception as exc:
                notes.append(('error', '%s: 파싱 실패 (%s)' % (path, exc)))
                continue
            if not isinstance(raw, dict):
                notes.append(('error', '%s: 최상위가 매핑이 아님' % path))
                continue
            rule = _normalize(raw, path, source)
            target = raw.get('override')
            if target:
                target = str(target)
                if target not in by_id:
                    notes.append(('warn', '%s: override 대상 %s 없음 (무시)' % (path, target)))
                    continue
                merged = _patch(by_id[target], rule, _raw_keys(raw))
                merged['id'] = target
                by_id[target] = merged
                notes.append(('info', '%s ← %s 로 패치됨' % (target, source)))
                continue
            if rule['id'] in by_id:
                notes.append(('warn', '%s: id 중복 %s (뒤에 온 것이 이김)'
                              % (path, rule['id'])))
            else:
                order.append(rule['id'])
            by_id[rule['id']] = rule

    ingest(os.path.join(root, 'rules'), 'core')
    ingest(user_dir(), 'user')
    ingest(local_dir(cwd), 'local')

    cfg = load_repo_config(cwd)
    if cfg.get('_error'):
        notes.append(('error', 'config.yaml 파싱 실패: %s' % cfg['_error']))

    for rid in cfg.get('disable') or []:
        if str(rid) in by_id:
            by_id[str(rid)]['disabled'] = True
            by_id[str(rid)]['disabled_by'] = 'config.yaml'
        else:
            notes.append(('warn', 'config.yaml disable: 없는 규칙 %s' % rid))

    for rid, sev in (cfg.get('severity') or {}).items():
        rid, sev = str(rid), str(sev).lower()
        if rid in by_id and sev in SEVERITIES:
            rule = by_id[rid]
            rule.setdefault('base_severity', rule['severity'])
            rule['severity'] = sev
            rule['severity_by'] = 'config.yaml'

    repo_exclude = cfg.get('exclude') or []
    if isinstance(repo_exclude, str):
        repo_exclude = [repo_exclude]

    # convention-guard's own config/output paths are never scanned as content.
    # Before a repo commits .claude/convention-rules/, git sees it as
    # untracked -- so the whole-file "new file" path treats it as added, and
    # a rule with no `files` filter (most of them) would then read its own
    # YAML comments as code. That is how a plain-language note explaining why
    # a rule was downgraded ends up tripping the very rule it explains.
    repo_exclude = list(repo_exclude) + [
        '%s/**' % LOCAL_DIRNAME.replace(os.sep, '/'),
        '.claude/rules/**',
    ]

    rules = []
    for rid in order:
        rule = by_id.get(rid)
        if not rule:
            continue
        if rule.get('disabled'):
            if include_disabled:
                rule['repo_exclude'] = repo_exclude
                rules.append(rule)
            continue
        try:
            kind = _compile(rule)
        except re.error as exc:
            notes.append(('error', '%s: 정규식 오류 (%s)' % (rid, exc)))
            continue
        except ValueError as exc:
            notes.append(('warn', '%s: %s (건너뜀)' % (rid, exc)))
            continue
        rule['kind'] = kind
        rule['repo_exclude'] = repo_exclude
        rules.append(rule)

    return rules, notes, cfg


# ---------------------------------------------------------------- matching

def stack_ok(rule, tags, versions):
    """Stack/version gate, independent of any single file.

    Changeset-level triggers (`paired`) have no relpath to test, so they need
    this half of `applies()` on its own.
    """
    stack = rule.get('stack') or []
    if stack and '*' not in stack and not (set(stack) & set(tags)):
        return False
    return version_ok(rule.get('version'), versions, stack)


def applies(rule, relpath, tags, versions):
    if _match_any(rule.get('repo_exclude'), relpath):
        return False
    if _match_any(rule.get('exclude'), relpath):
        return False
    if rule.get('files') and not _match_any(rule['files'], relpath):
        return False
    return stack_ok(rule, tags, versions)


KINDS = ('line', 'file', 'requires', 'absent', 'paired', 'semantic')


def _compile(rule):
    """Compile a rule's trigger and return its kind. Raises on a bad shape.

    Five kinds, differing in what they look at and what anchors the finding to
    *this* change rather than to the repo's history:

      line      추가된 줄            줄 자체가 앵커
      file      파일 전체 (다줄 패턴)  매치 구간이 변경된 줄과 겹쳐야 함
      requires  조건 + 파일 전체       조건이 '추가된 줄'에 있어야 함
      absent    새 파일 전체          파일이 새것이어야 함
      paired    변경 집합             변경 집합 자체가 앵커
    """
    flags = re.M
    if 'i' in str(rule.get('regex_flags', '')):
        flags |= re.I
    dotall = flags | re.S

    if rule.get('review_when'):
        # the regex is only a gate deciding whether a judgment is worth paying
        # for; the verdict comes from a subagent, never from this pattern
        if not rule.get('review_prompt'):
            raise ValueError('review_when 규칙에는 review_prompt 가 필요합니다')
        rule['compiled_review'] = re.compile(rule['review_when'], flags)
        return 'semantic'

    if rule.get('when_changed') or rule.get('require_changed'):
        if not (rule.get('when_changed') and rule.get('require_changed')):
            raise ValueError('when_changed 와 require_changed 는 함께 있어야 합니다')
        return 'paired'

    if rule.get('when_line') or rule.get('must_contain'):
        if not (rule.get('when_line') and rule.get('must_contain')):
            raise ValueError('when_line_added 와 must_contain_in_file 은 함께 있어야 합니다')
        rule['compiled_when'] = re.compile(rule['when_line'], flags)
        rule['compiled_must'] = re.compile(rule['must_contain'], dotall)
        return 'requires'

    if rule.get('absent_regex'):
        rule['compiled_absent'] = re.compile(rule['absent_regex'], flags)
        return 'absent'

    if rule.get('file_regex'):
        rule['compiled_file'] = re.compile(rule['file_regex'], dotall)
        return 'file'

    if rule.get('regex'):
        rule['compiled'] = re.compile(rule['regex'], flags)
        return 'line'

    raise ValueError('트리거 없음')


def superseded(rule, root):
    """A formatting rule steps aside when the repo already runs a formatter.

    Pint / php-cs-fixer fix these deterministically; a regex firing on the same
    thing is pure noise. The rule stays as a safety net for repos without one.
    Returns the marker that matched, or None.
    """
    for marker in rule.get('superseded_by') or []:
        if os.path.exists(os.path.join(root, marker)):
            return marker
    return None


def severity_rank(rule):
    return {'error': 0, 'warn': 1, 'info': 2}.get(rule['severity'], 3)
