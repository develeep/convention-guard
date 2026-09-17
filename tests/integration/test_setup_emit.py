#!/usr/bin/env python3
"""setup.py emit: the instruction layer is generated, but the documents are shared.

1. Only the managed block belongs to the generator; a person's text around it
   survives regeneration, and running twice changes nothing.
2. A document keeps its own line endings.
3. AGENTS.md mode puts the content in AGENTS.md and a one-line import in
   CLAUDE.md -- unless CLAUDE.md already imports it by hand.
4. A core rule a repo merely overrode (source "core<-local") stays grouped by
   its stack; it is not a repo-only rule loaded into every session.
5. A generated per-group file whose rules disappeared is removed, unless a
   person has added to it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import (LARAVEL_COMPOSER, check, isolated_env, make_repo,  # noqa: E402
                     run_cases, run_script, write)


def emit(repo, data, *args):
    return run_script('setup.py', ['emit', '--cwd', repo] + list(args),
                      env=isolated_env(data), cwd=repo)


def read(repo, rel):
    with open(os.path.join(repo, rel), encoding='utf-8', newline='') as fh:
        return fh.read()


def case_agents_md(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER,
                     'AGENTS.md': '# 프로젝트\r\n\r\n빌드는 make 로 합니다.\r\n'})
    proc = emit(repo, data, '--agents-md')
    check('emit --agents-md succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    agents = read(repo, 'AGENTS.md')
    check('human text is kept', '빌드는 make 로 합니다.' in agents, agents)
    check('the prevent lines are in', 'declare(strict_types=1)' in agents, agents)
    check('CRLF is followed', '\r\n' in agents and '\n' not in agents.replace('\r\n', ''),
          repr(agents[-120:]))
    check('CLAUDE.md imports AGENTS.md', '@AGENTS.md' in read(repo, 'CLAUDE.md'))

    emit(repo, data, '--agents-md')
    check('regeneration is idempotent', read(repo, 'AGENTS.md') == agents)
    check('the import is not duplicated', read(repo, 'CLAUDE.md').count('@AGENTS.md') == 1)


def case_manual_import_respected(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {'composer.json': LARAVEL_COMPOSER,
                     'CLAUDE.md': '# 메모\n\n@AGENTS.md\n'})
    emit(repo, data, '--agents-md')
    check('a hand-written import is left alone',
          read(repo, 'CLAUDE.md') == '# 메모\n\n@AGENTS.md\n', read(repo, 'CLAUDE.md'))


def case_groups_and_stale_files(tmp):
    repo, data = os.path.join(tmp, 'repo'), os.path.join(tmp, 'data')
    make_repo(repo, {
        'composer.json': LARAVEL_COMPOSER,
        '.claude/convention-guard/rules/migration.yaml':
            'override: core/laravel-migration-needs-down\nseverity: warn\n',
        '.claude/rules/convention-go.md': '<!-- convention-guard:begin x -->\n- old\n'
                                          '<!-- convention-guard:end -->\n',
        '.claude/rules/convention-js.md': '<!-- convention-guard:begin x -->\n- old\n'
                                          '<!-- convention-guard:end -->\n\n내가 쓴 메모\n',
    })
    proc = emit(repo, data)
    check('emit succeeds', proc.returncode == 0, proc.stdout + proc.stderr)
    php = read(repo, '.claude/rules/convention-php.md')
    check('an overridden core rule stays in its stack group', 'down()' in php, php)
    check('no repo-only group was invented',
          not os.path.exists(os.path.join(repo, '.claude', 'rules', 'convention-local.md')))
    check('the per-group file is path-scoped', php.startswith('---\npaths:'), php[:80])
    check('a stale generated file is removed',
          not os.path.exists(os.path.join(repo, '.claude', 'rules', 'convention-go.md')))
    check('a generated file a person added to is kept',
          os.path.exists(os.path.join(repo, '.claude', 'rules', 'convention-js.md')))


if __name__ == '__main__':
    sys.exit(run_cases([case_agents_md, case_manual_import_respected,
                        case_groups_and_stale_files], 'setup.py emit'))
