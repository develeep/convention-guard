#!/usr/bin/env python3
"""The store: one database for all plugin state, safe under parallel hooks.

- a whole session -- edits, a Bash call, a block, a review batch, a verdict --
  leaves the database and the firing log in the data dir, nothing else
- 3.x state files are cleared the first time 4.0 opens a data dir
- a database of another schema version is rebuilt, not read
- parallel collect hooks lose no touched path
"""

import json
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, ROOT, Session, check, make_repo, run_cases,  # noqa: E402
                     run_script, store_rows, write)
from lib import store  # noqa: E402

CTRL = 'app/Http/Controllers/OrderController.php'
HDR = '<?php\n\ndeclare(strict_types=1);\n\nnamespace App\\Http\\Controllers;\n\n'


def laravel(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    os.makedirs(data)
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER,
                     '.claude/convention-guard/config.yaml':
                         'mode: fix\nsemantic_review:\n  enabled: true\n',
                     CTRL: HDR + 'class OrderController\n{\n}\n'})
    return repo, data


def leftovers(data):
    """Files in the data dir besides the database and the log. `home` is the
    test's fake $HOME (isolated_env); anything written under it counts too."""
    allowed = {store.FILENAME, store.FILENAME + '-wal', store.FILENAME + '-shm', 'firings.jsonl',
               'home'}
    found = sorted(set(os.listdir(data)) - allowed)
    for dirpath, _dirs, files in os.walk(os.path.join(data, 'home')):
        found += [os.path.relpath(os.path.join(dirpath, f), data) for f in files]
    return found


def case_one_database(tmp):
    repo, data = laravel(tmp)
    s = Session(repo, data, 'all')
    s.bash_hook('PreToolUse')
    write(repo, 'app/Svc/A.php', HDR.replace('Http\\Controllers', 'Svc') + 'dd(1);\n')
    s.bash_hook('PostToolUse')
    out = s.edit(CTRL, HDR + 'class OrderController\n{\n    public function index($orders)\n'
                 '    {\n        foreach ($orders as $order) {\n'
                 '            $order->items->count();\n        }\n    }\n}\n')
    out = s.stop('p1')
    check('the turn blocks (a finding and a review batch)', out['decision'] == 'block', out)
    batch = next((part.split('"')[0] for part in out['reason'].split('show "')[1:]), None)
    if batch:
        shown = run_script('review.py', ['show', batch], env=s.env, cwd=repo)
        ids = [line.split()[2] for line in shown.stdout.splitlines() if line.startswith('### 후보 ')]
        run_script('review.py', ['record', batch], env=s.env, cwd=repo, stdin=json.dumps(
            [{'id': int(i), 'verdict': 'VALID', 'reason': 'x'} for i in ids]))
    s.stop('p1', stop_hook_active=True)
    check('a batch and a verdict were stored',
          store_rows(data, 'SELECT COUNT(*) FROM review_batch')[0][0] >= 1
          and store_rows(data, 'SELECT COUNT(*) FROM verdict')[0][0] >= 1)
    check('the data dir holds the database and the log, nothing else', leftovers(data) == [],
          leftovers(data))


def case_legacy_files_cleared(tmp):
    data = os.path.join(tmp, 'data')
    os.makedirs(os.path.join(data, 'reviews'))
    for name in ('session-x.json', 'touched-x.txt', 'foreign-x.jsonl', 'bash-x-1.json',
                 'base-x.json', 'bashmiss-x.txt', 'verdicts.json', 'cache-yaml.json',
                 'firings.jsonl', 'notes.txt'):
        write(data, name, '{}\n')
    write(data, 'reviews/s-1.json', '{}\n')
    store.connect(os.path.join(data, store.FILENAME))
    store.close_all()
    left = set(os.listdir(data)) - {store.FILENAME + '-wal', store.FILENAME + '-shm'}
    check('3.x state is gone, the log and unrelated files stay',
          left == {store.FILENAME, 'firings.jsonl', 'notes.txt'}, sorted(left))


def case_other_schema_is_rebuilt(tmp):
    db = os.path.join(tmp, store.FILENAME)
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.execute("INSERT INTO meta VALUES ('schema', '0')")
    conn.execute('CREATE TABLE verdict (whatever TEXT)')
    conn.execute("INSERT INTO verdict VALUES ('old')")
    conn.commit()
    conn.close()
    live = store.connect(db)
    cols = [row[1] for row in live.execute('PRAGMA table_info(verdict)')]
    check('a database of another version is rebuilt', 'review_key' in cols, cols)
    check('and nothing of it is read', live.execute('SELECT COUNT(*) FROM verdict').fetchone()[0]
          == 0)
    check('the version is now this one', live.execute(
        "SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == str(store.SCHEMA_VERSION))
    store.close_all()


def case_parallel_hooks(tmp):
    repo, data = laravel(tmp)
    s = Session(repo, data, 'par')
    paths = ['app/P%02d.php' % i for i in range(16)]
    for rel in paths:
        write(repo, rel, '<?php\n')
    procs = []
    for rel in paths:
        payload = json.dumps({'session_id': 'par', 'cwd': repo, 'hook_event_name': 'PostToolUse',
                              'tool_name': 'Edit', 'tool_input': {'file_path': rel}})
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, 'scripts', 'collect.py')],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=s.env, cwd=repo, text=True)
        proc.stdin.write(payload)
        proc.stdin.close()
        procs.append(proc)
    errors = []
    for proc in procs:
        err = proc.stderr.read()
        if proc.wait() != 0 or err:
            errors.append(err)
    got = {rel for (rel,) in store_rows(data, "SELECT path FROM touched WHERE session = 'par'")}
    check('16 collect hooks at once lose no path', got == set(paths) and not errors,
          (sorted(set(paths) - got), errors))


if __name__ == '__main__':
    sys.exit(run_cases([case_one_database, case_legacy_files_cleared,
                        case_other_schema_is_rebuilt, case_parallel_hooks], '상태 저장소'))
