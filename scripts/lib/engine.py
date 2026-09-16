"""Rule matching engine, shared by the Stop hook and the standalone scanner.

Kept separate from check.py so `scan.py` (manual runs, CI) and the hook apply
byte-identical logic. A checker that disagrees with itself depending on how it
was invoked is worse than no checker.
"""

from . import dismiss as dismisslib, gitdiff, rules as rulelib


class Context:
    """What one check knows about a change, with file reads cached."""

    def __init__(self, root, changed, new_files, tags, versions, dismissed=None):
        self.root = root
        self.changed = changed              # {relpath: [(lineno, added text)]}
        self.new_files = new_files          # treated as "whole file is new"
        self.tags = tags
        self.versions = versions
        self.dismissed = dismissed or frozenset()
        self._text = {}

    def files(self):
        return sorted(self.changed)

    def text(self, relpath):
        if relpath not in self._text:
            self._text[relpath] = gitdiff.read_text(self.root, relpath)
        return self._text[relpath]

    def changed_linenos(self, relpath):
        return {lineno for lineno, _ in self.changed.get(relpath, ())}

    def added_body(self, relpath):
        return '\n'.join(text for _, text in self.changed.get(relpath, ()))

    def is_dismissed(self, rule_id, relpath, snippet):
        """A finding the team already looked at and called a false positive."""
        return self.dismissed_hash(rule_id, relpath,
                                   dismisslib.fingerprint(snippet))

    def dismissed_hash(self, rule_id, relpath, digest):
        if not self.dismissed:
            return False
        if (rule_id, relpath) in self.dismissed:
            return True
        return (rule_id, relpath, digest) in self.dismissed


def clip(text, limit=120):
    text = text.strip()
    return text[:limit] + ('…' if len(text) > limit else '')


def _span_lines(body, match):
    start = body.count('\n', 0, match.start()) + 1
    end = body.count('\n', 0, match.end()) + 1
    return start, end


def scan(rule, ctx, cap):
    """Locations this rule reports for this change. Empty means clean."""
    kind = rule.get('kind', 'line')
    locations = []

    def add(relpath, lineno, snippet):
        """Returns True once the cap is reached."""
        if ctx.is_dismissed(rule['id'], relpath, snippet):
            return False
        locations.append({'file': relpath, 'line': lineno, 'snippet': snippet})
        return len(locations) >= cap

    if kind == 'paired':
        # changeset-level: A changed, B did not. The change set is the anchor.
        # The stack gate has to be applied by hand here: this branch never
        # reaches `applies()`, so without it a Laravel rule fires in a Go repo.
        if not rulelib.stack_ok(rule, ctx.tags, ctx.versions):
            return []
        visible = [f for f in ctx.files()
                   if not rulelib._match_any(rule.get('repo_exclude'), f)
                   and not rulelib._match_any(rule.get('exclude'), f)]
        touched = [f for f in visible
                   if rulelib._match_any(rule['when_changed'], f)]
        if not touched:
            return []
        if any(rulelib._match_any(rule['require_changed'], f) for f in visible):
            return []
        for relpath in touched:
            if add(relpath, 1, '(짝이 되는 파일 변경 없음)'):
                break
        return locations

    for relpath in ctx.files():
        if not rulelib.applies(rule, relpath, ctx.tags, ctx.versions):
            continue

        if kind == 'line':
            for lineno, text in ctx.changed[relpath]:
                if rule['compiled'].search(text):
                    if add(relpath, lineno, clip(text)):
                        return locations

        elif kind == 'absent':
            # only a file the agent just created -- on an existing file the
            # missing declaration is the repo's history, not this change
            if relpath not in ctx.new_files:
                continue
            if not rule['compiled_absent'].search(ctx.added_body(relpath)):
                if add(relpath, 1, '(새 파일에 해당 선언이 없음)'):
                    return locations

        elif kind == 'file':
            # whole file, so multi-line patterns are visible -- but the match
            # must touch a changed line, or every legacy block would fire
            body = ctx.text(relpath) or ctx.added_body(relpath)
            touched_lines = ctx.changed_linenos(relpath)
            is_new = relpath in ctx.new_files
            for match in rule['compiled_file'].finditer(body):
                start, end = _span_lines(body, match)
                if not is_new and not any(start <= n <= end for n in touched_lines):
                    continue
                snippet = clip(match.group(0).replace('\n', ' ⏎ '))
                if add(relpath, start, snippet):
                    return locations

        elif kind == 'requires':
            # the condition must be in what was just added; the requirement is
            # looked for across the whole file, which is the context we lacked
            body = ctx.text(relpath) or ctx.added_body(relpath)
            if rule['compiled_must'].search(body):
                continue
            for lineno, text in ctx.changed[relpath]:
                if rule['compiled_when'].search(text):
                    add(relpath, lineno, clip(text))
                    break

        elif kind == 'semantic':
            for lineno, text in ctx.changed[relpath]:
                if rule['compiled_review'].search(text):
                    add(relpath, lineno, clip(text))
                    break

        if len(locations) >= cap:
            return locations[:cap]

    return locations


def collect(all_rules, ctx, cap, skip=(), respect_supersede=True,
            include_semantic=False):
    """Run every applicable rule. Returns hits sorted by severity."""
    hits = []
    for rule in all_rules:
        if rule['id'] in skip:
            continue
        if rule.get('kind') == 'semantic' and not include_semantic:
            continue
        if respect_supersede and rulelib.superseded(rule, ctx.root):
            continue
        locations = scan(rule, ctx, cap)
        if locations:
            hits.append({'rule': rule, 'locations': locations})
    hits.sort(key=lambda h: (rulelib.severity_rank(h['rule']), -len(h['locations'])))
    return hits
