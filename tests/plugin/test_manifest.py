#!/usr/bin/env python3
"""The plugin manifests and hooks.json, which nothing else checks.

These four files are the whole contract with Claude Code, and none of them is
exercised by any other suite: a typo in a hook command path, a matcher that
drifts from the tool set hooks.py watches, or a version bumped in one manifest
and not the other all ship silently and only surface on a user's machine.

Fields are checked against the hook schema Claude Code actually accepts:
command entries take type/command/timeout/statusMessage, and a Stop hook
blocks with {"decision": "block", "reason": ...} plus an optional top-level
systemMessage.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish  # noqa: E402
from lib import hooks as hooklib  # noqa: E402

HOOK_KEYS = {'type', 'command', 'timeout', 'statusMessage'}
SCRIPT_RE = re.compile(r'\$\{CLAUDE_PLUGIN_ROOT\}/([\w/.-]+\.py)')


def load(*parts):
    path = os.path.join(ROOT, *parts)
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def case_hooks():
    print('hooks/hooks.json:')
    config = load('hooks', 'hooks.json')
    events = config.get('hooks') or {}
    check('declares Bash snapshot, PostToolUse and Stop hooks',
          set(events) == {'PreToolUse', 'PostToolUse', 'Stop'}, sorted(events))

    stop_timeout = None
    for event, groups in sorted(events.items()):
        for group in groups:
            for hook in group.get('hooks') or []:
                label = '%s %s' % (event, hook.get('command', '?'))
                check('%s: is a command hook' % event, hook.get('type') == 'command', hook)
                check('%s: no unknown keys' % event, set(hook) <= HOOK_KEYS,
                      sorted(set(hook) - HOOK_KEYS))
                timeout = hook.get('timeout')
                check('%s: timeout is a positive int' % event,
                      isinstance(timeout, int) and timeout > 0, timeout)
                scripts = SCRIPT_RE.findall(str(hook.get('command')))
                check('%s: names a script via ${CLAUDE_PLUGIN_ROOT}' % event, scripts, label)
                for rel in scripts:
                    check('%s: %s exists' % (event, rel),
                          os.path.isfile(os.path.join(ROOT, rel)))
                if event == 'Stop':
                    stop_timeout = timeout

    # the matcher is what decides whether collect.py is ever called; hooks.py
    # ignores anything outside WATCHED_TOOLS, so a tool in one and not the
    # other is either a hook that fires for nothing or an edit never recorded
    matcher = events['PostToolUse'][0].get('matcher') or ''
    check('PostToolUse matcher equals hooks.WATCHED_TOOLS',
          set(matcher.split('|')) == hooklib.WATCHED_TOOLS,
          (matcher, sorted(hooklib.WATCHED_TOOLS)))
    pre_matcher = events['PreToolUse'][0].get('matcher') or ''
    check('PreToolUse snapshots Bash before it can change files',
          pre_matcher == 'Bash', pre_matcher)

    # LINT_BUDGET only protects the turn while it stays under what the hook is
    # given; raising the budget past the timeout brings back the silent kill
    check('Stop hook outlives hooks.LINT_BUDGET',
          stop_timeout is not None and hooklib.LINT_BUDGET < stop_timeout,
          (hooklib.LINT_BUDGET, stop_timeout))


def case_manifests():
    print('.claude-plugin:')
    plugin = load('.claude-plugin', 'plugin.json')
    market = load('.claude-plugin', 'marketplace.json')
    entries = [p for p in market.get('plugins') or [] if p.get('name') == plugin.get('name')]
    check('marketplace lists this plugin', len(entries) == 1, market.get('plugins'))
    if not entries:
        return
    # bumping a release means editing two files by hand, which is exactly the
    # kind of step that gets half-done
    check('the two versions agree', plugin.get('version') == entries[0].get('version'),
          (plugin.get('version'), entries[0].get('version')))
    check('version is MAJOR.MINOR.PATCH',
          bool(re.match(r'^\d+\.\d+\.\d+$', str(plugin.get('version')))), plugin.get('version'))

    for key in ('name', 'description', 'version'):
        check('plugin.json has %s' % key, plugin.get(key))

    options = plugin.get('userConfig') or {}
    check('new installs start in report-only mode',
          (options.get('report_only') or {}).get('default') is True,
          options.get('report_only'))
    for name, spec in sorted(options.items()):
        check('userConfig %s has a type' % name,
              spec.get('type') in ('boolean', 'string', 'number', 'directory', 'file'),
              spec.get('type'))
        # delivered to hooks as CLAUDE_PLUGIN_OPTION_<KEY>; an option nothing
        # reads is a switch the user flips with no effect
        used = any('CLAUDE_PLUGIN_OPTION_' + name.upper() in text or
                   "user_option('%s'" % name in text
                   for text in SOURCES)
        check('userConfig %s is read somewhere' % name, used, name)


def _sources():
    out = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, 'scripts')):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            if name.endswith('.py'):
                with open(os.path.join(dirpath, name), encoding='utf-8') as fh:
                    out.append(fh.read())
    return out


SOURCES = _sources()


if __name__ == '__main__':
    case_hooks()
    case_manifests()
    sys.exit(finish('플러그인 매니페스트·훅 설정'))
