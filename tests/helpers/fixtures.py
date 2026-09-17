"""Throwaway repos that exercise most bundled rules at once.

Each builder commits a small legacy baseline (violations that are the repo's
history and must NOT be reported for a change) and then leaves a working-tree
change on top (violations this change is responsible for).
"""

from . import LARAVEL_COMPOSER, make_repo, write

LARAVEL_LEGACY = {
    'composer.json': LARAVEL_COMPOSER,
    'app/Legacy/OldController.php': (
        '<?php\n'
        'class OldController\n'
        '{\n'
        '    public function index($request)\n'
        '    {\n'
        '        dd($request);\n'
        '        return User::create($request->all());\n'
        '    }\n'
        '}\n'),
    'routes/web.php': "<?php\n\ndeclare(strict_types=1);\n\nRoute::get('/', fn () => 1);\n",
    'config/app.php': "<?php\n\nreturn ['key' => env('APP_KEY')];\n",
}

LARAVEL_CHANGE = {
    'app/Http/Controllers/UserController.php': (
        '<?php\n'
        '\n'
        'class UserController extends Controller\n'
        '{\n'
        '    public function store(Request $request)\n'
        '    {\n'
        '        $key = env(\'STRIPE_KEY\');\n'
        '        $password = \'p@ssw0rd-prod-1\';\n'
        '        $count = ( int )$request->input(\'count\');\n'
        '        // TODO 나중에 정리\n'
        '        foreach ($request->users as $user) {\n'
        '            $user->posts->count();\n'
        '        }\n'
        '        try {\n'
        '            $this->sync();\n'
        '        } catch (\\Throwable $e) {\n'
        '        }\n'
        '        if ($count > 1) {\n'
        '        } else if ($count > 2) {\n'
        '        }\n'
        '        $result = $this->repository->whereHas("orders", fn ($q) => $q->where("status", "paid"))'
        '->with(["user", "items"])->get();\n'
        '        dd($result);\n'
        '        return User::create($request->all());\n'
        '    }\n'
        '}\n'),
    'routes/api.php': "<?php\n\ndeclare(strict_types=1);\n\nRoute::post('/users', [UserController::class, 'store']);\n",
    'resources/views/home.blade.php': "<h1>{{ User::where('id', 1)->first()->name }}</h1>\n",
    'database/migrations/2026_01_01_000000_create_orders.php': (
        '<?php\n'
        '\n'
        'return new class extends Migration\n'
        '{\n'
        '    public function up(): void\n'
        '    {\n'
        "        Schema::create('orders', fn () => null);\n"
        '    }\n'
        '};\n'),
}

# an existing legacy file gets one new offending line; its old dd() must stay silent
LARAVEL_LEGACY_EDIT = ('app/Legacy/OldController.php', (
    '<?php\n'
    'class OldController\n'
    '{\n'
    '    public function index($request)\n'
    '    {\n'
    '        dd($request);\n'
    '        var_dump($request->ip());\n'
    '        return User::create($request->all());\n'
    '    }\n'
    '}\n'))


def laravel_repo(path):
    make_repo(path, LARAVEL_LEGACY)
    for rel, body in LARAVEL_CHANGE.items():
        write(path, rel, body)
    write(path, *LARAVEL_LEGACY_EDIT)
    return path


NEXT_LEGACY = {
    'package.json': '{"dependencies": {"next": "15.0.0", "react": "19.0.0"}}',
    'tsconfig.json': '{}\n',
    'app/layout.tsx': 'export default function Layout({ children }) {\n  return children;\n}\n',
    'app/legacy.tsx': ("export function Legacy() {\n"
                       "  console.log('old');\n"
                       "  return null;\n"
                       "}\n"),
}

NEXT_CHANGE = {
    'app/page.tsx': (
        "import { useState } from 'react';\n"
        "\n"
        "const apiKey = \"sk-live-9f2b41c8aa\";\n"
        "\n"
        "export default function Page() {\n"
        "  const [n, setN] = useState(0);\n"
        "  const rows: any[] = [];\n"
        "  console.log(process.env.NEXT_PUBLIC_STRIPE_SECRET);\n"
        "  try {\n"
        "    setN(1);\n"
        "  } catch (e) {\n"
        "  }\n"
        "  return rows.map((row, index) => <img key={index} src={row} />);\n"
        "}\n"),
    'app/legacy.tsx': ("export function Legacy() {\n"
                       "  console.log('old');\n"
                       "  return null;\n"
                       "}\n"
                       "export function debug(x: any) {\n"
                       "  return x;\n"
                       "}\n"),
}


def next_repo(path):
    make_repo(path, NEXT_LEGACY)
    for rel, body in NEXT_CHANGE.items():
        write(path, rel, body)
    return path


GO_LEGACY = {
    'go.mod': 'module example.com/x\n\ngo 1.22\n',
    'pkg/store/legacy.go': ('package store\n'
                            '\n'
                            'func Legacy() {\n'
                            '\tpanic("legacy")\n'
                            '}\n'),
}

GO_CHANGE = {
    'pkg/store/store.go': (
        'package store\n'
        '\n'
        'import (\n'
        '\t"context"\n'
        '\t"encoding/json"\n'
        '\t"fmt"\n'
        ')\n'
        '\n'
        'type Store struct{}\n'
        '\n'
        'func (s *Store) Fetch(\n'
        '\tid string,\n'
        '\tctx context.Context,\n'
        ') error {\n'
        '\tvar v map[string]any\n'
        '\t_ = json.Unmarshal([]byte(id), &v)\n'
        '\t// TODO 캐시\n'
        '\tif err := ctx.Err(); err != nil {\n'
        '\t\treturn fmt.Errorf("fetch: %v", err)\n'
        '\t}\n'
        '\tpanic("unreachable")\n'
        '}\n'),
    'main.go': 'package main\n\nfunc main() {\n\tpanic("boot")\n}\n',
}


def go_repo(path):
    make_repo(path, GO_LEGACY)
    for rel, body in GO_CHANGE.items():
        write(path, rel, body)
    return path


NEST_LEGACY = {
    'package.json': '{"dependencies": {"@nestjs/core": "10.0.0"}}',
    'tsconfig.json': '{}\n',
}

NEST_CHANGE = {
    'src/users/users.controller.ts': (
        "import { Controller, Get, Res } from '@nestjs/common';\n"
        "\n"
        "@Controller('users')\n"
        "export class UsersController {\n"
        "  constructor(private readonly repo: Repository<User>) {}\n"
        "\n"
        "  @Get()\n"
        "  findAll(@Res() res: Response) {\n"
        "    return this.repo.find();\n"
        "  }\n"
        "}\n"),
}


def nest_repo(path):
    make_repo(path, NEST_LEGACY)
    for rel, body in NEST_CHANGE.items():
        write(path, rel, body)
    return path


BUILDERS = {'laravel': laravel_repo, 'next': next_repo, 'go': go_repo, 'nest': nest_repo}
