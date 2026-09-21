#!/usr/bin/env python3
"""Skills and the reviewer agent follow the Agent Skills authoring rules, and
every command and example they show actually works.

Structure (platform.claude.com agent-skills best practices):
- name: <= 64 chars, lowercase letters/digits/hyphens, no reserved words, = dir name
- description: 1..1024 chars, no XML tags, says what it does and when to use it
- SKILL.md body under 500 lines
- references one level deep from SKILL.md; reference files > 100 lines have a 목차
- forward-slash paths only
- at least three evaluation scenarios per skill (tests/skills/evals/<name>.json)

Truthfulness:
- every script a skill or agent tells Claude to run exists
- every example rule in rule-add's references loads and passes its own fixtures
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from helpers import ROOT, check, finish  # noqa: E402
from lib import rules as rulelib  # noqa: E402
from lib.yamlio import load as yaml_load  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'rules'))
from test_rule_fixtures import matcher  # noqa: E402

SKILLS = os.path.join(ROOT, 'skills')
AGENTS = os.path.join(ROOT, 'agents')
EVALS = os.path.join(HERE, 'evals')
NAME_RE = re.compile(r'^[a-z0-9-]{1,64}$')
LINK_RE = re.compile(r'\]\(([^)#\s]+\.md)\)')
SCRIPT_RE = re.compile(r'(?:\$\{CLAUDE_PLUGIN_ROOT\}|<plugin>)/((?:scripts|tests)/[\w/.-]+\.py)')
XML_RE = re.compile(r'<[A-Za-z/][^>]*>')
BASH_RE = re.compile(r'```bash\n(.*?)```', re.S)
# `$VAR` / `${VAR}`, but not `$(...)` and not `${{ ... }}` (CI templating)
USE_RE = re.compile(r'\$\{(?!\{)(\w+)\}|\$(\w+)')
SET_RE = re.compile(r'^\s*(?:export\s+)?(\w+)=', re.M)
# set by the shell itself, so a block may read them without setting them
SHELL_VARS = {'HOME', 'PWD', 'PATH', 'USER', 'SHELL'}
AGENT_TOOLS = {'Bash', 'Read', 'Grep', 'Glob', 'Write', 'Edit', 'NotebookEdit', 'WebFetch',
               'WebSearch'}


def split_frontmatter(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read().replace('\r\n', '\n')
    if not text.startswith('---\n'):
        return None, text
    end = text.index('\n---\n', 4)
    return yaml_load(text[4:end]), text[end + 5:]


def scripts_in(text):
    found = set()
    for match in SCRIPT_RE.finditer(text):
        rel = match.group(1) or 'scripts/%s' % match.group(2)
        found.add(rel)
    return found


def check_scripts(label, text):
    for rel in sorted(scripts_in(text)):
        check('%s: %s exists' % (label, rel), os.path.isfile(os.path.join(ROOT, rel)))


def check_shell_vars(label, text, substituted=()):
    """Each bash block is one Bash tool call, and shell state does not survive
    to the next one. `S="<...>/scripts"` written in prose -- or in an earlier
    block -- is gone by the time the next block runs, and `python3 "$S/scan.py"`
    then runs as `python3 "/scan.py"`. It shipped that way in every skill once.
    """
    for block in BASH_RE.findall(text):
        known = set(SET_RE.findall(block)) | SHELL_VARS | set(substituted)
        for braced, bare in USE_RE.findall(block):
            name = braced or bare
            check('%s: bash block does not read undefined $%s' % (label, name),
                  name in known, block.strip()[:120])


def check_no_plugin_root(label, text):
    """Claude Code substitutes ${CLAUDE_PLUGIN_ROOT} only in content it loads as
    instructions (SKILL.md, agents/*.md, hooks.json). A reference file is opened
    later with Read, so it arrives raw and the variable expands to nothing.
    """
    check('%s: no ${CLAUDE_PLUGIN_ROOT} (not substituted here -- use <plugin>)' % label,
          'CLAUDE_PLUGIN_ROOT' not in text)


def check_skill(name):
    skill_dir = os.path.join(SKILLS, name)
    path = os.path.join(skill_dir, 'SKILL.md')
    front, body = split_frontmatter(path)
    label = 'skills/%s' % name
    check('%s has frontmatter' % label, isinstance(front, dict))
    front = front or {}
    skill_name = str(front.get('name') or '')
    check('%s name is valid' % label, bool(NAME_RE.match(skill_name))
          and 'anthropic' not in skill_name and 'claude' not in skill_name, skill_name)
    check('%s name matches its directory' % label, skill_name == name, skill_name)
    desc = str(front.get('description') or '')
    check('%s description is 1..1024 chars' % label, 0 < len(desc) <= 1024, len(desc))
    check('%s description has no XML tags' % label, not XML_RE.search(desc))
    check('%s description says when to use it' % label, '사용합니다' in desc, desc[-80:])
    check('%s description is not second person' % label,
          '사용하세요' not in desc and '해주세요' not in desc, desc)
    lines = body.count('\n') + 1
    check('%s body is under 500 lines' % label, lines < 500, lines)
    check('%s uses forward slashes only' % label, '\\scripts' not in body and 'scripts\\' not in body)
    check_scripts(label, body)
    check_shell_vars(label, body, substituted=('CLAUDE_PLUGIN_ROOT',))

    for link in sorted(set(LINK_RE.findall(body))):
        ref = os.path.normpath(os.path.join(skill_dir, link))
        check('%s link %s exists' % (label, link), os.path.isfile(ref))
        if not os.path.isfile(ref) or not ref.startswith(skill_dir):
            continue
        with open(ref, encoding='utf-8') as fh:
            ref_text = fh.read()
        nested = [l for l in LINK_RE.findall(ref_text)
                  if os.path.isfile(os.path.normpath(os.path.join(os.path.dirname(ref), l)))]
        check('%s is one level deep (no further .md links)' % link, not nested, nested)
        if ref_text.count('\n') > 100:
            check('%s (>100 lines) has a table of contents' % link, '## 목차' in ref_text)
        check_scripts('%s/%s' % (label, link), ref_text)
        check_no_plugin_root('%s/%s' % (label, link), ref_text)
        check_shell_vars('%s/%s' % (label, link), ref_text)

    evals_path = os.path.join(EVALS, '%s.json' % name)
    check('%s has an evals file' % label, os.path.isfile(evals_path))
    if os.path.isfile(evals_path):
        with open(evals_path, encoding='utf-8') as fh:
            evals = json.load(fh)
        check('%s has at least three evaluations' % label, len(evals) >= 3, len(evals))
        for i, scenario in enumerate(evals):
            check('%s eval %d is well formed' % (label, i + 1),
                  scenario.get('skills') == [name] and scenario.get('query')
                  and len(scenario.get('expected_behavior') or []) >= 2, scenario)


def check_agent(path):
    front, body = split_frontmatter(path)
    label = 'agents/%s' % os.path.basename(path)
    front = front or {}
    check('%s name matches its file' % label,
          front.get('name') == os.path.splitext(os.path.basename(path))[0], front.get('name'))
    desc = str(front.get('description') or '')
    check('%s description is 1..1024 chars without XML' % label,
          0 < len(desc) <= 1024 and not XML_RE.search(desc), desc)
    tools = [t.strip() for t in str(front.get('tools') or '').split(',') if t.strip()]
    check('%s tools are known' % label, tools and set(tools) <= AGENT_TOOLS, tools)
    check_scripts(label, body)
    check_shell_vars(label, body, substituted=('CLAUDE_PLUGIN_ROOT',))


def check_example_rules():
    path = os.path.join(SKILLS, 'rule-add', 'references', 'examples.md')
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    blocks = re.findall(r'```yaml\n(.*?)```', text, re.S)
    check('rule-add examples exist', len(blocks) >= 5, len(blocks))
    for block in blocks:
        raw = yaml_load(block)
        rid = raw.get('id', '?')
        try:
            rule = rulelib.normalize(raw, 'example.yaml', 'local')
        except rulelib.RuleError as exc:
            check('example %s loads' % rid, False, exc)
            continue
        hit = matcher(rule)
        ok = all(hit(s) for s in rule['tests'].get('match') or []) and \
            not any(hit(s) for s in rule['tests'].get('no_match') or [])
        check('example %s passes its own fixtures' % rid, ok)


def main():
    names = sorted(d for d in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, d, 'SKILL.md')))
    check('the five skills of the design are present',
          set(names) >= {'convention-setup', 'convention-discover', 'convention-check',
                         'rule-add', 'rule-tune'}, names)
    for name in names:
        print('%s:' % name)
        check_skill(name)
    for agent in sorted(os.listdir(AGENTS)):
        if agent.endswith('.md'):
            print('agent %s:' % agent)
            check_agent(os.path.join(AGENTS, agent))
    print('rule-add examples:')
    check_example_rules()
    return finish('스킬·에이전트 구조')


if __name__ == '__main__':
    sys.exit(main())
