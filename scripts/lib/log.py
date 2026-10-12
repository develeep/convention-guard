"""The JSONL firing log the tuning cycle reads."""

import json
import os
import time

from .paths import data_dir, user_option

# The log only ever grows; past this size it is rotated once to firings.jsonl.1
# so a year of sessions cannot turn log_report.py into a memory problem.
MAX_BYTES = 5 * 1024 * 1024

# 2 = 1.0 events: candidate / block / verify / verdict / review_requested /
# dismissed / lint / autofix / abandoned, and one `stop` per Stop
# (outcome, hook_ms, prompt; wait_s/fix_s/review_s/stops on the Stop that ends
# the turn). New event types are additive -- readers ignore events they do not
# know -- so they do not bump the schema. Readers skip rows without it.
SCHEMA = 2


def log_path():
    """Where firings.jsonl lives. The log_dir option moves only this file --
    session state stays in the plugin data dir, so a shared team log never
    collides with another machine's in-flight session. A relative log_dir is
    ignored: it would resolve against each hook's cwd and scatter the log
    into every repo, so the data dir keeps it in one place."""
    override = user_option('log_dir')
    path = os.path.expanduser(override) if isinstance(override, str) and override else ''
    if os.path.isabs(path):
        try:
            os.makedirs(path, exist_ok=True)
            return os.path.join(path, 'firings.jsonl')
        except OSError:
            pass
    return os.path.join(data_dir(), 'firings.jsonl')


def _rotate(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + '.1')
    except OSError:
        pass


def event(record):
    """Append one record. Never raises: logging must not break a hook."""
    record = dict(record)
    record.setdefault('ts', time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    record.setdefault('schema', SCHEMA)
    path = log_path()
    _rotate(path)
    try:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    except OSError:
        pass


def read(path=None):
    """All records from the log and its rotated predecessor, oldest first."""
    path = path or log_path()
    rows = []
    for candidate in (path + '.1', path):
        try:
            with open(candidate, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
    return rows
