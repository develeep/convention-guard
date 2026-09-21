#!/usr/bin/env python3
"""Verdict cache identity: what a cached semantic verdict is allowed to answer.

A verdict is one model's answer to one question about one piece of code. It may
only be reused while the question and the code are the same, so the cache key
folds together:

    rule definition   detect gate + semantic_review (schema.definition_hash)
    primary context   the function the candidate sits in
    related context   the related files / imports the pack carried

Anything else -- the rule's title or severity, another function in the file, a
file the pack never carried -- must leave the verdict usable, or every rename
and every unrelated edit pays for a new review.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import context, semantic  # noqa: E402
from lib.candidate import Candidate, VALID  # noqa: E402
from lib.rules import schema  # noqa: E402

CTRL = 'app/Http/Controllers/OrderController.php'
MODEL = 'app/Models/Order.php'

CONTROLLER = """<?php

namespace App\\Http\\Controllers;

use App\\Models\\Order;

class OrderController extends Controller
{
    public function index()
    {
        $orders = Order::query()->get();

        foreach ($orders as $order) {
            $total = $order->items->sum('price');
        }

        return $orders;
    }

    public function show(Order $order)
    {
        return $order;
    }
}
"""

ORDER_MODEL = """<?php

namespace App\\Models;

class Order extends Model
{
}
"""

RAW_RULE = {
    'id': 'n-plus-one',
    'title': '반복문 안에서 로드되지 않은 관계 접근',
    'severity': 'warn',
    'applies_to': {'stacks': ['laravel']},
    'detect': {'when_line_added': r'\bforeach\s*\('},
    'semantic_review': {
        'instruction': '관계를 eager load 하지 않고 반복 접근하면 VIOLATION.',
        'context': ['current_function', 'imports',
                    {'related_files': {'symbol': r'\b([A-Z]\w+)::(?:query|with)\b',
                                       'glob': 'app/Models/{1}.php'}}],
    },
    'message': '반복문 밖에서 with() 로 로드하세요',
}

FILES = {CTRL: CONTROLLER, MODEL: ORDER_MODEL}
LOOP_LINE = CONTROLLER.split('\n').index('        foreach ($orders as $order) {') + 1


class FakeScope:
    def __init__(self, files):
        self.root = '/repo'
        self.files = files

    def text(self, rel):
        return self.files.get(rel, '')

    def lines(self, rel):
        return ()


def patched(base, patch):
    """A rule raw mapping with `patch` deep-merged in, as a local override would."""
    out = dict(base)
    for key, value in patch.items():
        out[key] = dict(out.get(key), **value) if isinstance(value, dict) else value
    return out


def key_for(files=None, raw=None, line=LOOP_LINE, rel=CTRL):
    """The cache key one candidate would be judged under, the way annotate() builds it."""
    files = files or FILES
    rule = schema.normalize(raw or RAW_RULE, 'rules/n-plus-one.yaml', 'core')
    scope = FakeScope(files)
    cand = Candidate(rule['id'], rel, line, files[rel].split('\n')[line - 1].strip())
    pack = context.build(scope, cand, rule['review'], list_files=lambda: sorted(files))
    cand.context_hash = pack.context_hash
    cand.review_hash = semantic.review_hash(rule, pack)
    return cand.review_key


# ---------------------------------------------------------------- cases

def case_rule_definition():
    print('case_rule_definition:')
    base = key_for()
    check('a rule with semantic_review gets a definition hash',
          schema.normalize(RAW_RULE, 'p.yaml', 'core')['definition_hash'])
    check('a rule without one does not',
          schema.normalize({k: v for k, v in RAW_RULE.items() if k != 'semantic_review'},
                           'p.yaml', 'core')['definition_hash'] is None)

    changed_instruction = patched(RAW_RULE, {'semantic_review': dict(
        RAW_RULE['semantic_review'], instruction='관계 접근은 Service 내부에서만 허용.')})
    check('changing the instruction makes the old verdict unusable',
          key_for(raw=changed_instruction) != base)

    changed_context = patched(RAW_RULE, {'semantic_review': dict(
        RAW_RULE['semantic_review'], context=['current_function'])})
    check('changing the context providers does too', key_for(raw=changed_context) != base)

    changed_budget = patched(RAW_RULE, {'semantic_review': dict(
        RAW_RULE['semantic_review'], max_context_lines=40)})
    check('and changing the context budget', key_for(raw=changed_budget) != base)

    changed_gate = patched(RAW_RULE, {'detect': {'when_line_added': r'\bforeach\s*\(|->each\s*\('}})
    check('changing the detect gate does too', key_for(raw=changed_gate) != base)

    cosmetic = patched(RAW_RULE, {'title': '다른 제목', 'severity': 'error',
                                  'message': '다른 안내'})
    check('renaming the rule or changing its severity keeps the verdict',
          key_for(raw=cosmetic) == base)


def case_context():
    print('case_context:')
    base = key_for()
    check('the same rule on the same code is the same key', key_for() == base)

    fixed = CONTROLLER.replace("Order::query()->get()", "Order::query()->with('items')->get()")
    check('editing the candidate function invalidates it',
          key_for(dict(FILES, **{CTRL: fixed})) != base)

    sibling = CONTROLLER.replace('        return $order;', '        return [$order];')
    check('editing another method in the same file does not',
          key_for(dict(FILES, **{CTRL: sibling})) == base)

    with_relation = ORDER_MODEL.replace('{\n}', '{\n    public function items()\n    {\n'
                                                '        return $this->hasMany(Item::class);\n'
                                                '    }\n}')
    moved = key_for(dict(FILES, **{MODEL: with_relation}))
    check('the pack carries the model', 'hasMany' in with_relation)
    check('editing a related file the pack carried invalidates the verdict', moved != base)

    unrelated = dict(FILES, **{'app/Services/Mailer.php': '<?php\nclass Mailer {}\n',
                               'app/Models/Invoice.php': ORDER_MODEL})
    check('a file the pack never carried does not', key_for(unrelated) == base)

    imports = CONTROLLER.replace('use App\\Models\\Order;',
                                 'use App\\Models\\Order;\nuse App\\Support\\Money;')
    check('changing the imports the pack showed invalidates the verdict',
          key_for(dict(FILES, **{CTRL: imports})) != base)


def case_cache_roundtrip():
    print('case_cache_roundtrip:')
    key = key_for()
    cache = {'/repo': {key: {'verdict': VALID, 'reason': '이미 로드됨', 'at': 2e9}}}
    check('an unchanged candidate hits the cache',
          (semantic.lookup('/repo', key, None, cache) or {}).get('verdict') == VALID)

    changed = patched(RAW_RULE, {'semantic_review': dict(
        RAW_RULE['semantic_review'], instruction='관계 접근은 Service 내부에서만 허용.')})
    check('the same code under a changed rule misses and is reviewed again',
          semantic.lookup('/repo', key_for(raw=changed), None, cache) is None)
    check('and so does the same rule after the model changed',
          semantic.lookup('/repo', key_for(dict(FILES, **{
              MODEL: ORDER_MODEL.replace('{\n}', '{\n    public function items() {}\n}')})),
              None, cache) is None)

    check('a candidate with no pack yet still has a usable key',
          Candidate('core/x', CTRL, 3, 'foreach ($a as $b) {').review_key
          == 'core/x:%s:%s' % (CTRL, Candidate('core/x', CTRL, 3,
                                               'foreach ($a as $b) {').code_hash))


if __name__ == '__main__':
    case_rule_definition()
    case_context()
    case_cache_roundtrip()
    sys.exit(finish('판정 캐시 키'))
