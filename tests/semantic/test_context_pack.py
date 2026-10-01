#!/usr/bin/env python3
"""Context packs: what a reviewer sees, and when a cached verdict goes stale.

The pack must contain what decides the verdict (the eager load three lines
above the loop, the model's relation method) and must not grow into the file.
The context hash must change when the function changes -- that is how a
VIOLATION that was fixed gets judged again -- and must not change when an
unrelated function in the same file does.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import context  # noqa: E402
from lib.candidate import Candidate  # noqa: E402


class FakeScope:
    def __init__(self, files, added=None):
        self.root = '/repo'
        self.files = files
        self.added = added or {}

    def text(self, rel):
        return self.files.get(rel, '')

    def lines(self, rel):
        return self.added.get(rel, ())


CONTROLLER = """<?php

declare(strict_types=1);

namespace App\\Http\\Controllers;

use App\\Models\\Order;
use Illuminate\\Http\\Request;

class OrderController extends Controller
{
    public function index(Request $request)
    {
        $orders = Order::query()
            ->with('items')
            ->latest()
            ->get();

        foreach ($orders as $order) {
            $total = $order->items->sum('price');
        }

        return view('orders.index', compact('orders'));
    }

    public function show(Order $order)
    {
        return view('orders.show', compact('order'));
    }
}
"""

MODEL = """<?php

namespace App\\Models;

class Order extends Model
{
    public function items()
    {
        return $this->hasMany(OrderItem::class);
    }
}
"""

REVIEW = {'context': ['current_function', 'imports',
                      {'related_files': {'symbol': r'\b([A-Z]\w+)::(?:query|with)\b',
                                         'glob': 'app/Models/{1}.php'}}],
          'max_context_lines': 150}


def pack_for(files, rel, line, review=REVIEW, added=None):
    scope = FakeScope(files, added)
    cand = Candidate('core/x', rel, line, files[rel].split('\n')[line - 1].strip())
    return context.build(scope, cand, review, list_files=lambda: sorted(files))


def text_of(pack, kind):
    return '\n'.join(s['text'] for s in pack.sections if s['kind'] == kind)


IMPORTS = {'context': ['current_function', 'imports'], 'max_context_lines': 150}


def case_imports_are_imports():
    """R21 / SEM r9 -- the import section holds the imports, all of them, and nothing else."""
    print('case_imports_are_imports:')
    go = ('package store\n\nimport (\n\t"context"\n\t"database/sql"\n)\n\n'
          'func Load(ctx context.Context) {\n\tpanic(1)\n}\n')
    pack = pack_for({'pkg/store.go': go}, 'pkg/store.go', 9, IMPORTS)
    got = text_of(pack, 'imports')
    check('a Go import block is read to its closing paren',
          '"context"' in got and '"database/sql"' in got and ')' in got, got)

    php = ('<?php\n\nnamespace App\\Models;\n\nuse Illuminate\\Database\\Eloquent\\Model;\n\n'
           'class Order extends Model\n{\n    use SoftDeletes;\n\n'
           '    public function f()\n    {\n        return 1;\n    }\n}\n')
    got = text_of(pack_for({'app/Order.php': php}, 'app/Order.php', 13, IMPORTS), 'imports')
    check('a trait inside the class is not an import', 'Eloquent' in got
          and 'SoftDeletes' not in got, got)

    py = ('"""Module.\n\nimport this is prose, not code\n"""\nimport os\n\n\n'
          'def f():\n    return os.sep\n')
    got = text_of(pack_for({'a.py': py}, 'a.py', 9, IMPORTS), 'imports')
    check('an import inside a docstring is not one', 'import os' in got
          and 'import this' not in got, got)

    js = "import {\n  a,\n  b,\n} from './x';\n\nexport function f() {\n  return a + b;\n}\n"
    got = text_of(pack_for({'a.js': js}, 'a.js', 7, IMPORTS), 'imports')
    check('a multi-line JS import is read whole', "from './x'" in got and '  b,' in got, got)


def case_python_blocks():
    """R21 / SEM r1, r5 -- decorators belong to the function they decorate."""
    print('case_python_blocks:')
    py = ('import os\n\n\n@transaction.atomic\ndef save(\n    order,\n    items,\n):\n'
          '    for item in items:\n        item.save()\n')
    body = text_of(pack_for({'a.py': py}, 'a.py', 10, IMPORTS), 'current_function')
    check('the decorator is part of the function', '@transaction.atomic' in body, body)
    check('a Black-style signature does not swallow the file', 'import os' not in body, body)
    bare = py.replace('@transaction.atomic\n', '')
    check('removing the decorator changes the context hash',
          pack_for({'a.py': bare}, 'a.py', 9, IMPORTS).context_hash
          != pack_for({'a.py': py}, 'a.py', 10, IMPORTS).context_hash)

    broken = ('@cache\ndef f(\n    a,\n):\n    x = 1\n# a comment at column 0\n'
              '    return a\n\nmatch = (\n')     # does not parse: the indent fallback
    body = text_of(pack_for({'b.py': broken}, 'b.py', 7, IMPORTS), 'current_function')
    check('the fallback keeps the decorator and reads past a column-0 comment',
          '@cache' in body and 'return a' in body, body)


def case_php_method():
    print('case_php_method:')
    files = {'app/Http/Controllers/OrderController.php': CONTROLLER, 'app/Models/Order.php': MODEL}
    pack = pack_for(files, 'app/Http/Controllers/OrderController.php', 19)
    body = text_of(pack, 'current_function')
    check('the enclosing method is the primary section', 'public function index' in body, body)
    check('the eager load above the loop is in the pack', "->with('items')" in body, body)
    check('the sibling method is not', 'public function show' not in body, body)
    check('imports are included', 'use App\\Models\\Order;' in text_of(pack, 'imports'))
    related = text_of(pack, 'related_files')
    check('the model named in the query is included', 'hasMany(OrderItem::class)' in related,
          related)
    check('lines are numbered for reference', '19| ' in body, body)

    edited_sibling = CONTROLLER.replace("compact('order')", "['order' => $order]")
    other = pack_for(dict(files, **{'app/Http/Controllers/OrderController.php': edited_sibling}),
                     'app/Http/Controllers/OrderController.php', 19)
    check('editing another method keeps the context hash', other.context_hash == pack.context_hash)

    without_load = CONTROLLER.replace("            ->with('items')\n", '')
    changed = pack_for(dict(files, **{'app/Http/Controllers/OrderController.php': without_load}),
                       'app/Http/Controllers/OrderController.php', 18)
    check('editing this method changes the context hash',
          changed.context_hash != pack.context_hash)


def case_closure_inside_method():
    print('case_closure_inside_method:')
    src = CONTROLLER.replace(
        "        foreach ($orders as $order) {\n            $total = $order->items->sum('price');\n        }",
        "        $orders->each(function ($order) {\n            $order->items->count();\n        });")
    files = {'app/Http/Controllers/OrderController.php': src}
    line = src.split('\n').index('        $orders->each(function ($order) {') + 1
    pack = pack_for(files, 'app/Http/Controllers/OrderController.php', line)
    body = text_of(pack, 'current_function')
    check('a callback on the candidate line does not hide the query above it',
          "->with('items')" in body, body)


def case_long_function_is_elided():
    print('case_long_function_is_elided:')
    filler = '\n'.join('        $x%d = %d;' % (i, i) for i in range(200))
    src = ('<?php\nclass A\n{\n    public function big()\n    {\n' + filler +
           '\n        foreach ($rows as $row) {\n        }\n' + filler + '\n    }\n}\n')
    line = src.split('\n').index('        foreach ($rows as $row) {') + 1
    pack = pack_for({'app/A.php': src}, 'app/A.php', line,
                    {'context': ['current_function'], 'max_context_lines': 150})
    body = text_of(pack, 'current_function')
    check('the pack stays within budget', pack.lines <= 150, pack.lines)
    check('the candidate line is kept', 'foreach ($rows as $row)' in body)
    check('the signature is kept', 'public function big()' in body)
    check('the cut is marked', '줄 더 — 필요하면 Read' in body, body[:400])
    check('the pack says it was truncated', pack.truncated)
    # R23l / SEM r12: what is left of the function budget goes to the window
    # around the candidate, not to waste
    check('the clipped function uses its budget',
          context.FUNCTION_MAX_LINES - 5 <= pack.lines <= context.FUNCTION_MAX_LINES, pack.lines)
    check('centred on the candidate', '$x170 = 170;' in body and '$x29 = 29;' in body, body[:300])


def case_typescript_and_go():
    print('case_typescript_and_go:')
    ts = ("import { db } from './db';\n\n"
          "export async function listUsers(limit: number): Promise<User[]> {\n"
          "  const users = await db.user.findMany({ take: limit });\n"
          "  for (const user of users) {\n"
          "    await db.post.count({ where: { userId: user.id } });\n"
          "  }\n"
          "  return users;\n"
          "}\n\n"
          "export function other() {\n  return 1;\n}\n")
    pack = pack_for({'src/users.ts': ts}, 'src/users.ts', 5,
                    {'context': ['current_function', 'imports'], 'max_context_lines': 80})
    body = text_of(pack, 'current_function')
    check('a TypeScript function is found', 'listUsers' in body and 'return users' in body, body)
    check('and ends at its closing brace', 'other()' not in body, body)

    go = ('package store\n\n'
          'func (s *Store) Fetch(\n'
          '\tctx context.Context,\n'
          '\tid string,\n'
          ') error {\n'
          '\tfor _, x := range s.items {\n'
          '\t\t_ = x\n'
          '\t}\n'
          '\treturn nil\n'
          '}\n')
    pack = pack_for({'pkg/store.go': go}, 'pkg/store.go', 7,
                    {'context': ['current_function'], 'max_context_lines': 80})
    body = text_of(pack, 'current_function')
    check('a Go method with a multi-line signature is found',
          'func (s *Store) Fetch(' in body and 'return nil' in body, body)


def case_js_methods_and_callbacks():
    """R2: a JS method is a function; R21: an iteration callback is not the unit."""
    print('case_js_methods_and_callbacks:')
    js = ("class OrderService {\n"
          "  constructor(db) {\n"
          "    this.db = db;\n"
          "  }\n\n"
          "  async totals(orders) {\n"
          "    const rows = await this.db.with('items');\n"
          "    orders.forEach((order) => {\n"
          "      order.items.length;\n"
          "    });\n"
          "  }\n"
          "}\n")
    for line, what in ((7, 'the method'), (9, 'an arrow callback inside it')):
        pack = pack_for({'src/orders.js': js}, 'src/orders.js', line,
                        {'context': ['current_function'], 'max_context_lines': 80})
        body = text_of(pack, 'current_function')
        check('the pack for %s is the whole method' % what,
              'async totals(orders)' in body and "with('items')" in body
              and 'constructor' not in body, body or pack.sections)


def case_python_and_fallback():
    print('case_python_and_fallback:')
    py = ('import os\n\n'
          'def outer():\n'
          '    for x in range(3):\n'
          '        print(x)\n'
          '    return 1\n\n'
          'def later():\n'
          '    return 2\n')
    pack = pack_for({'a.py': py}, 'a.py', 4, {'context': ['current_function'],
                                               'max_context_lines': 80})
    body = text_of(pack, 'current_function')
    check('a Python function is found by indentation', 'def outer' in body and 'later' not in body,
          body)

    txt = '\n'.join('line %d' % i for i in range(1, 100))
    pack = pack_for({'notes.txt': txt}, 'notes.txt', 50,
                    {'context': ['current_function'], 'max_context_lines': 150})
    check('an unknown language falls back to a window around the candidate',
          [s['kind'] for s in pack.sections] == ['snippet'] and 'line 50' in pack.sections[0]['text'],
          pack.sections)


if __name__ == '__main__':
    case_php_method()
    case_imports_are_imports()
    case_python_blocks()
    case_closure_inside_method()
    case_long_function_is_elided()
    case_typescript_and_go()
    case_js_methods_and_callbacks()
    case_python_and_fallback()
    sys.exit(finish('컨텍스트 팩'))
