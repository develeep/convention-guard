"""Candidate: a place a rule says is worth looking at. Not yet a violation.

A deterministic detector only ever produces candidates. Whether a candidate is
a real violation is decided afterwards -- by the agent reading the code, by
the semantic reviewer, or by the team through a dismissal.

Identity is (rule, file, code fingerprint), deliberately without the line
number: a suppression or a verdict must survive lines being added above it,
and must expire the moment the code itself changes.
"""

import hashlib

VALID = 'VALID'
FALSE_POSITIVE = 'FALSE_POSITIVE'
VIOLATION = 'VIOLATION'
VERDICTS = (VALID, FALSE_POSITIVE, VIOLATION)

SNIPPET_LIMIT = 120


def fingerprint(text):
    """Whitespace-insensitive 10-hex fingerprint of a code snippet."""
    norm = ' '.join(str(text).split())
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()[:10]


def clip(text, limit=SNIPPET_LIMIT):
    text = text.strip()
    return text[:limit] + ('…' if len(text) > limit else '')


class Candidate:
    __slots__ = ('rule_id', 'file', 'line', 'snippet', 'code_hash', 'context_hash')

    def __init__(self, rule_id, file, line, snippet, context_hash=None):
        self.rule_id = rule_id
        self.file = file
        self.line = int(line)
        self.snippet = snippet
        self.code_hash = fingerprint(snippet)
        self.context_hash = context_hash

    @property
    def key(self):
        """rule:file:hash -- what dismissals and the verification cycle match on."""
        return '%s:%s:%s' % (self.rule_id, self.file, self.code_hash)

    @property
    def review_key(self):
        """What a semantic verdict is cached under. Falls back to the code hash
        until a context pack has been built for the candidate."""
        return '%s:%s:%s' % (self.rule_id, self.file, self.context_hash or self.code_hash)

    def to_dict(self):
        out = {'file': self.file, 'line': self.line, 'snippet': self.snippet,
               'hash': self.code_hash}
        if self.context_hash:
            out['context_hash'] = self.context_hash
        return out

    def __repr__(self):
        return 'Candidate(%s %s:%d)' % (self.rule_id, self.file, self.line)


def parse_key(key):
    """'core/x:app/A.php:6f1c93ab24' -> (rule_id, file, hash). Rule ids and
    paths may contain ':' on no platform we support, but hashes never do."""
    head, _, digest = str(key).rpartition(':')
    rule_id, _, relpath = head.partition(':')
    if not (rule_id and relpath and digest):
        raise ValueError('키 형식은 <규칙id>:<파일>:<지문> 입니다: %s' % key)
    return rule_id, relpath, digest
