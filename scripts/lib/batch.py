"""A review batch, planned without touching anything.

Which semantic candidates go to the reviewer this time, under what
budget, and the reference that names the batch -- `<database path>#<id>`,
one argument that works from any shell. decide.py plans with this and
must stay pure, so nothing here reads or writes: semantic.py stores and
reads batches.
"""

import os

# 4: stored in the database, named by reference (4.0)
BATCH_VERSION = 4


def plan_batch(root, session, pending, cfg, label='', db='', log='', ident='', now=0.0):
    """(reference, body, items, deferred) for a batch, without storing it.

    The Stop hook's decide() plans the batch it asks for; the shell stores
    the body afterwards under the reference the state already names.
    """
    limit = int(cfg['semantic_review']['max_candidates'])
    budget = int(cfg['semantic_review']['context_budget_lines'])
    items, deferred, used, rules = [], [], 0, {}
    # same rule, same file, same context hash: two console.logs in one function
    # are one question and the cached verdict covers both -- so the question
    # shows the reviewer every one of them, not just the first (R7)
    questions, covers = [], {}
    for rule, cand, pack in pending:
        if cand.review_key not in covers:
            covers[cand.review_key] = []
            questions.append((rule, cand, pack))
        covers[cand.review_key].append({'line': cand.line, 'snippet': cand.snippet})
    for rule, cand, pack in questions:
        if len(items) >= limit or (items and used + pack.lines > budget):
            deferred.append((rule, cand, pack))
            continue
        used += pack.lines
        rules[rule['id']] = {'title': rule['title'], 'severity': rule['severity'],
                             'instruction': rule['review']['instruction'],
                             'message': rule.get('message') or ''}
        items.append({'id': len(items) + 1, 'rule_id': rule['id'], 'review_key': cand.review_key,
                      'key': cand.key, 'file': cand.file, 'line': cand.line,
                      'snippet': cand.snippet,
                      'lines': sorted(covers[cand.review_key], key=lambda c: c['line']),
                      'context': pack.to_dict()})
    if not items:
        return None, None, [], deferred
    body = {'version': BATCH_VERSION, 'repo': root, 'session': session, 'label': label,
            'created': now, 'db': db, 'log': log,
            'verdict_ttl_days': cfg['semantic_review']['verdict_ttl_days'],
            'rules': rules, 'items': items}
    return reference(db, ident), body, items, deferred


def reference(db, ident):
    """What names a batch everywhere -- a block message, a reviewer's command."""
    return '%s#%s' % (str(db).replace(os.sep, '/'), ident)


def parse_reference(ref):
    """'<db>#<id>' -> (db path, id). ValueError for anything else."""
    db, sep, ident = str(ref or '').rpartition('#')
    if not (sep and db and ident.isalnum()):
        raise ValueError('판정 배치 참조는 <저장소 경로>#<배치 id> 입니다: %s' % ref)
    return db, ident
