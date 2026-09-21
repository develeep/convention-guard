"""Delegate deterministic checks to the repo's own linters.

Anything a linter can decide should never become a regex rule. Each stack
declares its commands; a command whose `if_exists` binary is missing is
skipped silently, so a repo without the toolchain is never blocked by it.

Each command also declares which files it owns. Handing eslint a package.json
or pint a README is not a convention failure -- it is us feeding a tool
something it was never meant to read, and the tool's complaint about that
would block the agent for no reason.

And each command declares how to read its output (`parse:`). Without that the
linter half of this plugin had no anchor: the rules only look at added lines,
but `phpstan app/Legacy.php` reports the whole file and `go vet ./...` the
whole module, so touching one line in a five-year-old file blocked the turn on
errors nobody in this change wrote. Parsed file:line pairs let the caller
block on findings that sit on changed lines and pass the rest through as
context. A command with no parser -- or one whose output does not parse --
falls back to blocking on the whole output, which is the old behaviour.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time

from .rules import match_any as _match_any

MAX_OUTPUT = 3000
UNIX_RE = re.compile(r'^(?P<file>[^\s:][^:]*):(?P<line>\d+)(?::\d+)?:\s*(?P<msg>.*)$')
GITHUB_RE = re.compile(r'file=(?P<file>[^,]+),line=(?P<line>\d+)')
DIFF_HUNK_RE = re.compile(r'^@@ -(\d+)(?:,\d+)? \+')


def binary_present(root, entry):
    marker = entry.get('if_exists')
    if not marker:
        return True
    if os.path.sep in marker or marker.startswith('./'):
        return os.path.exists(os.path.join(root, marker))
    return shutil.which(marker) is not None


def _dirs_of(files):
    out = []
    for rel in files:
        head = os.path.dirname(rel)
        token = './%s' % head if head else '.'
        if token not in out:
            out.append(token)
    return out or ['.']


def _build(entry, files):
    cmd = entry['cmd']
    parts = cmd if isinstance(cmd, list) else shlex.split(cmd)
    out = []
    for part in parts:
        if part == '{files}':
            out.extend(files)
        elif part == '{dirs}':
            out.extend(_dirs_of(files))
        elif '{files}' in part:
            out.append(part.replace('{files}', ' '.join(files)))
        else:
            out.append(part)
    return out


def entry_key(entry):
    cmd = entry.get('cmd')
    template = '\x1f'.join(map(str, cmd)) if isinstance(cmd, list) else str(cmd)
    digest = hashlib.sha1(template.encode('utf-8')).hexdigest()[:12]
    return '%s:%s' % (entry.get('stack') or '', digest)


def owned_files(entry, files):
    """The subset this command is declared to handle. No globs means all."""
    globs = entry.get('files')
    if isinstance(globs, str):
        globs = [globs]
    if not globs:
        return list(files)
    return [f for f in files if _match_any(globs, f)]


# ---------------------------------------------------------------- parsing

def _rel(root, raw):
    path = str(raw).strip().strip('"')
    if path.startswith('a/') or path.startswith('b/'):
        path = path[2:]
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, root)
        except ValueError:
            pass
    path = path.replace(os.sep, '/')
    return path[2:] if path.startswith('./') else path


def _loc(root, path, line, message):
    return {'file': _rel(root, path), 'line': int(line),
            'message': ' '.join(str(message).split())[:300]}


def _parse_eslint_json(root, text):
    out = []
    for item in json.loads(text or '[]') or []:
        for msg in item.get('messages') or []:
            if not msg.get('line'):
                continue
            label = msg.get('ruleId') or ''
            out.append(_loc(root, item.get('filePath') or '', msg['line'],
                            '%s %s' % (msg.get('message', ''),
                                       '(%s)' % label if label else '')))
    return out


def _parse_phpstan_json(root, text):
    out = []
    files = (json.loads(text or '{}') or {}).get('files') or {}
    for path, payload in files.items():
        for msg in (payload or {}).get('messages') or []:
            if msg.get('line'):
                out.append(_loc(root, path, msg['line'], msg.get('message', '')))
    return out


def _parse_golangci_json(root, text):
    out = []
    for issue in (json.loads(text or '{}') or {}).get('Issues') or []:
        pos = issue.get('Pos') or {}
        if pos.get('Line'):
            out.append(_loc(root, pos.get('Filename') or '', pos['Line'],
                            '%s (%s)' % (issue.get('Text', ''),
                                         issue.get('FromLinter', ''))))
    return out


def _parse_unix(root, text):
    out = []
    for line in (text or '').split('\n'):
        match = UNIX_RE.match(line.strip())
        if match:
            out.append(_loc(root, match.group('file'), match.group('line'),
                            match.group('msg')))
    return out


def _parse_github(root, text):
    out = []
    for line in (text or '').split('\n'):
        match = GITHUB_RE.search(line)
        if match:
            message = line.split('::')[-1] if '::' in line else line
            out.append(_loc(root, match.group('file'), match.group('line'),
                            message))
    return out


def _parse_diff(root, text):
    """Unified diff from a formatter (php-cs-fixer --diff, pint --test -v).

    The `-` side is the file as it stands, so its line numbers are the ones
    that can be compared against the change.
    """
    out, cur, minus = [], None, 0
    for line in (text or '').split('\n'):
        if line.startswith('--- '):
            raw = line[4:].strip()
            cur = None if raw == '/dev/null' else _rel(root, raw)
            continue
        if line.startswith('+++ '):
            continue
        match = DIFF_HUNK_RE.match(line)
        if match:
            minus = int(match.group(1))
            continue
        if cur is None or not minus:
            continue
        if line.startswith('-'):
            out.append(_loc(root, cur, minus, '포맷이 규약과 다릅니다'))
            minus += 1
        elif line.startswith(' '):
            minus += 1
    return out


PARSERS = {
    'eslint-json': _parse_eslint_json,
    'phpstan-json': _parse_phpstan_json,
    'golangci-json': _parse_golangci_json,
    'unix': _parse_unix,
    'github': _parse_github,
    'diff': _parse_diff,
}


def parse_output(root, entry, text):
    """[{file, line, message}] or [] when the output cannot be anchored."""
    kind = entry.get('parse')
    parser = PARSERS.get(str(kind)) if kind else None
    if not parser:
        return []
    try:
        return parser(root, text)
    except (ValueError, TypeError, KeyError):
        return []


# ---------------------------------------------------------------- running

def _unchecked(notes, argv, why):
    if notes is None:
        return
    notes.append(('warn', '린터 %s 를 돌리지 못했습니다 (%s) — 이번 변경은 이 린터로 '
                          '검사되지 않았습니다' % (argv[0], why)))


def run(root, entries, files, timeout=90, max_files=40, budget=None, notes=None):
    """Return list of failures: {stack, cmd, output, locations, anchored}.

    `timeout` is per linter and `entries` runs sequentially, so N linters can
    take N * timeout. Under a hook that is fatal: the hook is killed, prints
    nothing, and a killed hook is indistinguishable from a clean check. Pass
    `budget` to cap the whole phase, and `notes` to hear about what that cost --
    a linter that did not run must never pass for one that found nothing.
    """
    failures = []
    if not files:
        return failures
    deadline = (time.monotonic() + budget) if budget else None
    all_files = sorted(files)
    for entry in entries or []:
        if not binary_present(root, entry):
            continue
        owned = owned_files(entry, all_files)
        command_text = str(entry.get('cmd'))
        has_files = '{files}' in command_text
        has_dirs = '{dirs}' in command_text
        placeholders = has_files or has_dirs
        if not owned and placeholders:
            continue        # nothing this linter owns changed
        if has_dirs and not has_files:
            representatives = []
            seen_dirs = set()
            for rel in owned:
                directory = os.path.dirname(rel)
                if directory not in seen_dirs:
                    seen_dirs.add(directory)
                    representatives.append(rel)
            chunks = [representatives[i:i + max_files]
                      for i in range(0, len(representatives), max_files)]
        elif placeholders:
            chunks = [owned[i:i + max_files] for i in range(0, len(owned), max_files)]
        else:
            chunks = [owned[:max_files]]
        for index, mine in enumerate(chunks):
            argv = _build(entry, mine)
            if not argv:
                continue
            left = timeout
            if deadline is not None:
                left = min(timeout, deadline - time.monotonic())
                if left <= 0:
                    remaining = sum(len(chunk) for chunk in chunks[index:])
                    _unchecked(notes, argv, '시간 예산 소진으로 %d개 파일 미검사' % remaining)
                    break
            try:
                proc = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                                      errors='replace', timeout=left)
            except subprocess.TimeoutExpired:
                _unchecked(notes, argv, '%d초 안에 끝나지 않음' % round(left))
                continue
            except (OSError, ValueError) as exc:
                _unchecked(notes, argv, str(exc))
                continue
            if proc.returncode == 0:
                continue
            stdout, stderr = proc.stdout or '', proc.stderr or ''
            locations = parse_output(root, entry, stdout) or parse_output(root, entry, stderr)
            output = (stdout + stderr).strip()
            if len(output) > MAX_OUTPUT:
                output = output[:MAX_OUTPUT] + '\n... (생략)'
            failures.append({
                'stack': entry.get('stack'),
                'key': entry_key(entry),
                'cmd': ' '.join(argv[:6]) + (' ...' if len(argv) > 6 else ''),
                'output': output or '(출력 없음)',
                'locations': locations,
                'anchored': bool(locations),
                'skipped_files': 0,
            })
    return failures


def split_by_change(failures, ctx):
    """(blocking, informational).

    A finding on a line this change added is ours. A finding elsewhere in a
    file we merely touched is the repo's history: it is reported, never
    blocking. Output we could not parse keeps blocking, because silently
    dropping a real linter failure is the worse error.
    """
    blocking, informational = [], []
    for fail in failures:
        if not fail.get('anchored'):
            blocking.append(fail)
            continue
        ours, theirs = [], []
        for loc in fail['locations']:
            (ours if loc['line'] in ctx.changed_linenos(loc['file'])
             else theirs).append(loc)
        if ours:
            blocking.append(dict(fail, locations=ours, output=render(ours),
                                 carried=len(theirs)))
        elif theirs:
            informational.append(dict(fail, locations=theirs,
                                      output=render(theirs[:5])))
    return blocking, informational


def render(locations):
    return '\n'.join('%s:%d  %s' % (loc['file'], loc['line'], loc['message'])
                     for loc in locations)
