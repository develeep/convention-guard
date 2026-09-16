"""Delegate deterministic checks to the repo's own linters.

Anything a linter can decide should never become a regex rule. Each stack
declares its commands; a command whose `if_exists` binary is missing is
skipped silently, so a repo without the toolchain is never blocked by it.

Each command also declares which files it owns. Handing eslint a package.json
or pint a README is not a convention failure -- it is us feeding a tool
something it was never meant to read, and the tool's complaint about that
would block the agent for no reason.
"""

import os
import shlex
import shutil
import subprocess

from .rules import _match_any

MAX_OUTPUT = 3000


def _binary_present(root, entry):
    marker = entry.get('if_exists')
    if not marker:
        return True
    if os.path.sep in marker or marker.startswith('./'):
        return os.path.exists(os.path.join(root, marker))
    return shutil.which(marker) is not None


def _build(entry, files):
    cmd = entry['cmd']
    parts = cmd if isinstance(cmd, list) else shlex.split(cmd)
    out = []
    for part in parts:
        if part == '{files}':
            out.extend(files)
        elif '{files}' in part:
            out.append(part.replace('{files}', ' '.join(files)))
        else:
            out.append(part)
    return out


def owned_files(entry, files):
    """The subset this command is declared to handle. No globs means all."""
    globs = entry.get('files')
    if isinstance(globs, str):
        globs = [globs]
    if not globs:
        return list(files)
    return [f for f in files if _match_any(globs, f)]


def run(root, entries, files, timeout=90, max_files=40):
    """Return list of {stack, cmd, output} for commands that failed."""
    failures = []
    if not files:
        return failures
    all_files = sorted(files)
    for entry in entries or []:
        if not _binary_present(root, entry):
            continue
        mine = owned_files(entry, all_files)[:max_files]
        if not mine and '{files}' in str(entry.get('cmd')):
            continue        # nothing this linter owns changed
        files = mine
        argv = _build(entry, files)
        if not argv:
            continue
        try:
            proc = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                                  errors='replace', timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        except (OSError, ValueError):
            continue
        if proc.returncode != 0:
            output = (proc.stdout or '') + (proc.stderr or '')
            output = output.strip()
            if len(output) > MAX_OUTPUT:
                output = output[:MAX_OUTPUT] + '\n... (생략)'
            failures.append({
                'stack': entry.get('stack'),
                'cmd': ' '.join(argv[:6]) + (' ...' if len(argv) > 6 else ''),
                'output': output or '(출력 없음)',
            })
    return failures
