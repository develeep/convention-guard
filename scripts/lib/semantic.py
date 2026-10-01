"""Semantic review: which candidates need a reviewer, and what reviewers said.

    candidates of rules with semantic_review
      -> context pack + context_hash         (context.py)
      -> verdict cache by review key          VALID / FALSE_POSITIVE -> dropped
                                              VIOLATION              -> a finding
                                              none                   -> review batch
      -> batch file for the reviewer          (scripts/review.py show / record)

The cache is what keeps a Stop from paying for the same judgment twice: the
key is rule:file:review_hash, where review_hash folds together the rule
definition that asked the question (schema.definition_hash: detect gate +
semantic_review) and the context the answer used (the primary region and the
related files/imports the pack carried). So an unchanged function judged under
an unchanged rule is never re-reviewed, and an edit to the function, to the
Model it queries, or to the rule's instruction sends it back to the reviewer.
It lives in the store (store.py) -- not the repo --
because a verdict is a model's opinion, not a team decision; a team decision
is a dismissal in dismissed.yaml.

The reviewer runs as a subagent whose shell does not inherit the plugin's
environment, so a batch is named by one self-contained reference,
`<database path>#<batch id>`, and carries the repo and log paths it needs;
review.py records verdicts against the batch and into the cache in that
same database.
"""

import json
import os
import time
import uuid

from . import candidate, context as contextlib, gitdiff, store as storelib
from .batch import BATCH_VERSION, parse_reference, plan_batch, reference  # noqa: F401
from .candidate import FALSE_POSITIVE, VALID, VERDICTS, VIOLATION  # noqa: F401
from .log import log_path



# ---------------------------------------------------------------- verdict cache

def _cutoff(ttl_days):
    return time.time() - float(ttl_days) * 86400 if ttl_days else 0.0


def load_cache(root, ttl_days=None, db=None):
    """{review_key: {verdict, reason, at, rule_id}} for one repo, unexpired."""
    rows = storelib.connect(db).execute(
        'SELECT review_key, verdict, reason, rule_id, at FROM verdict WHERE root = ? AND at >= ?',
        (root, _cutoff(ttl_days)))
    return {key: {'verdict': verdict, 'reason': reason or '', 'rule_id': rule_id, 'at': at}
            for key, verdict, reason, rule_id, at in rows}


def lookup(root, review_key, ttl_days, cache=None):
    cache = cache if cache is not None else load_cache(root, ttl_days)
    entry = cache.get(review_key)
    return entry if isinstance(entry, dict) and entry.get('verdict') in VERDICTS else None


def store(root, verdicts, ttl_days=None, db=None):
    """Merge {review_key: {verdict, reason}} into the cache, in one transaction.

    This repo's expired verdicts are dropped on the way, so the table does not
    grow for ever; other repos are pruned by their own TTL when they write (R23j).
    """
    conn = storelib.connect(db)
    now = time.time()
    with storelib.transaction(conn):
        if ttl_days:
            conn.execute('DELETE FROM verdict WHERE root = ? AND at < ?',
                         (root, _cutoff(ttl_days)))
        conn.executemany(
            'INSERT OR REPLACE INTO verdict (root, review_key, verdict, reason, rule_id, at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [(root, key, value['verdict'], value.get('reason', ''), value.get('rule_id'), now)
             for key, value in verdicts.items()])


# ---------------------------------------------------------------- annotate

def tracked_files(root):
    try:
        return sorted(set(gitdiff.tracked(root)) | gitdiff.untracked(root))
    except gitdiff.GitError:
        return []


def review_hash(rule, pack):
    """Identity of one semantic judgment: the rule definition that asked the
    question, plus the context the reviewer answered it from."""
    return candidate.fingerprint('%s|%s|%s' % (rule.get('definition_hash') or '',
                                               pack.context_hash, pack.related_hash))


def annotate(result):
    """[(rule, cand, pack)] for every semantic candidate; sets the candidate's
    context_hash and review_hash."""
    listing = {}

    def list_files():
        if 'files' not in listing:
            listing['files'] = tracked_files(result.scope.root)
        return listing['files']

    out = []
    for rule, cands in result.semantic_hits:
        for cand in cands:
            pack = contextlib.build(result.scope, cand, rule['review'], list_files)
            cand.context_hash = pack.context_hash
            cand.review_hash = review_hash(rule, pack)
            out.append((rule, cand, pack))
    return out


class Triage:
    def __init__(self):
        self.violations = []   # [(rule, cand, verdict)]  -> handled like deterministic findings
        self.cleared = []      # [(rule, cand, verdict)]  -> VALID / FALSE_POSITIVE
        self.pending = []      # [(rule, cand, pack)]     -> need a reviewer


def triage(result, cfg):
    """Split semantic candidates by what the cache already knows.

    Everything is triaged, including rules the session has already settled:
    hiding them here would also hide them from the verification cycle, which
    has to see the code as it actually is.
    """
    out = Triage()
    root = result.scope.root
    ttl = cfg['semantic_review']['verdict_ttl_days']
    cache = load_cache(root, ttl)
    for rule, cand, pack in annotate(result):
        verdict = lookup(root, cand.review_key, ttl, cache)
        if verdict is None:
            out.pending.append((rule, cand, pack))
        elif verdict['verdict'] == VIOLATION:
            out.violations.append((rule, cand, verdict))
        else:
            out.cleared.append((rule, cand, verdict))
    return out


# ---------------------------------------------------------------- batches

def build_batch(root, session, pending, cfg, label=''):
    """Plan and store a batch now. Returns (reference, items, deferred)."""
    db = storelib.path()
    ref, body, items, deferred = plan_batch(root, session, pending, cfg, label=label, db=db,
                                            log=log_path(), ident=new_batch_id(),
                                            now=time.time())
    if ref:
        save_batch(ref, body)
    return ref, items, deferred


def new_batch_id():
    return uuid.uuid4().hex[:16]


def save_batch(ref, body):
    db, ident = parse_reference(ref)
    conn = storelib.connect(db)
    with storelib.transaction(conn):
        conn.execute('INSERT OR REPLACE INTO review_batch (id, session, root, created, body) '
                     'VALUES (?, ?, ?, ?, ?)',
                     (ident, body.get('session'), body['repo'], body['created'],
                      json.dumps(body, ensure_ascii=False)))


def read_batch(ref):
    db, ident = parse_reference(ref)
    if not os.path.isfile(db):
        raise ValueError('상태 저장소가 없습니다: %s' % db)
    row = storelib.connect(db).execute('SELECT body FROM review_batch WHERE id = ?',
                                       (ident,)).fetchone()
    if row is None:
        raise ValueError('판정 배치가 없습니다 (지났거나 정리됨): %s' % ref)
    batch = json.loads(row[0])
    if not isinstance(batch, dict) or batch.get('version') != BATCH_VERSION:
        raise ValueError('판정 배치가 아닙니다: %s' % ref)
    return batch


def write_verdicts(ref, verdicts):
    """Record what the reviewer said for a batch: {review_key: {...}}."""
    db, ident = parse_reference(ref)
    conn = storelib.connect(db)
    with storelib.transaction(conn):
        conn.execute('INSERT OR REPLACE INTO review_verdicts (batch_id, recorded, body) '
                     'VALUES (?, ?, ?)',
                     (ident, time.time(), json.dumps(verdicts, ensure_ascii=False)))


def read_verdicts(ref):
    """{review_key: {...}} recorded for a batch, or None if the reviewer never ran."""
    try:
        db, ident = parse_reference(ref)
    except ValueError:
        return None
    if not os.path.isfile(db):
        return None
    row = storelib.connect(db).execute('SELECT body FROM review_verdicts WHERE batch_id = ?',
                                       (ident,)).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
