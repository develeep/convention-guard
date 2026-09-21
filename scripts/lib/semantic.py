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
It lives in the plugin data dir -- not the repo --
because a verdict is a model's opinion, not a team decision; a team decision
is a dismissal in dismissed.yaml.

The reviewer runs as a subagent whose shell does not inherit the plugin's
environment, so a batch file carries the absolute paths it needs (repo, data
dir, log) and review.py writes verdicts next to the batch and into the cache
named there.
"""

import json
import os
import time

from . import candidate, context as contextlib, gitdiff
from .candidate import FALSE_POSITIVE, VALID, VERDICTS, VIOLATION  # noqa: F401
from .log import log_path
from .paths import atomic_write, data_dir, safe_name

BATCH_VERSION = 1


# ---------------------------------------------------------------- verdict cache

def cache_path(base=None):
    return os.path.join(base or data_dir(), 'verdicts.json')


def load_cache(path, ttl_days=None):
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if ttl_days:
        cutoff = time.time() - float(ttl_days) * 86400
        for repo in list(data):
            entries = data[repo] if isinstance(data[repo], dict) else {}
            data[repo] = {k: v for k, v in entries.items()
                          if isinstance(v, dict) and v.get('at', 0) >= cutoff}
    return data


def lookup(root, review_key, ttl_days, cache=None):
    cache = cache if cache is not None else load_cache(cache_path(), ttl_days)
    entry = (cache.get(root) or {}).get(review_key)
    return entry if isinstance(entry, dict) and entry.get('verdict') in VERDICTS else None


def store(path, root, verdicts):
    """Merge {review_key: {verdict, reason}} into the cache file at `path`."""
    data = load_cache(path)
    bucket = data.setdefault(root, {})
    now = time.time()
    for key, value in verdicts.items():
        bucket[key] = {'verdict': value['verdict'], 'reason': value.get('reason', ''),
                       'at': now, 'rule_id': value.get('rule_id')}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, json.dumps(data, ensure_ascii=False))


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
    cache = load_cache(cache_path(), ttl)
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

def reviews_dir():
    path = os.path.join(data_dir(), 'reviews')
    os.makedirs(path, exist_ok=True)
    return path


def build_batch(root, session, pending, cfg, label=''):
    """Write a batch for the reviewer. Returns (path, items, deferred)."""
    limit = int(cfg['semantic_review']['max_candidates'])
    budget = int(cfg['semantic_review']['context_budget_lines'])
    items, deferred, used, rules = [], [], 0, {}
    asked = set()
    for rule, cand, pack in pending:
        if cand.review_key in asked:
            # same rule, same file, same context hash: two console.logs in one
            # function are one question, and the cached verdict covers both
            continue
        asked.add(cand.review_key)
        if len(items) >= limit or (items and used + pack.lines > budget):
            deferred.append((rule, cand, pack))
            continue
        used += pack.lines
        rules[rule['id']] = {'title': rule['title'], 'severity': rule['severity'],
                             'instruction': rule['review']['instruction'],
                             'message': rule.get('message') or ''}
        items.append({'id': len(items) + 1, 'rule_id': rule['id'], 'review_key': cand.review_key,
                      'key': cand.key, 'file': cand.file, 'line': cand.line,
                      'snippet': cand.snippet, 'context': pack.to_dict()})
    if not items:
        return None, [], deferred
    # Multiple review pages can be created within one second. Include process
    # and nanosecond identity so a later page never overwrites an earlier one.
    stamp = '%s-%d-%d' % (time.strftime('%Y%m%d-%H%M%S'), os.getpid(), time.time_ns())
    name = '%s-%s%s.json' % (safe_name(session or 'manual'), stamp,
                             ('-' + safe_name(label)) if label else '')
    path = os.path.join(reviews_dir(), name)
    batch = {'version': BATCH_VERSION, 'repo': root, 'session': session,
             'created': time.time(), 'data_dir': data_dir(), 'log': log_path(),
             'rules': rules, 'items': items}
    atomic_write(path, json.dumps(batch, ensure_ascii=False, indent=1))
    return path, items, deferred


def read_batch(path):
    with open(path, 'r', encoding='utf-8') as fh:
        batch = json.load(fh)
    if not isinstance(batch, dict) or batch.get('version') != BATCH_VERSION:
        raise ValueError('convention-guard 판정 배치 파일이 아닙니다: %s' % path)
    return batch


def verdicts_path(batch_path):
    return batch_path[:-len('.json')] + '.verdicts.json' if batch_path.endswith('.json') \
        else batch_path + '.verdicts.json'


def read_verdicts(batch_path):
    """{review_key: {...}} recorded for a batch, or None if the reviewer never ran."""
    try:
        with open(verdicts_path(batch_path), 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def gc_batches(max_age_days=7):
    cutoff = time.time() - max_age_days * 86400
    base = os.path.join(data_dir(), 'reviews')
    try:
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if os.path.getmtime(full) < cutoff:
                os.remove(full)
    except OSError:
        pass
