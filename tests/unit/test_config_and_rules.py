#!/usr/bin/env python3
"""Configuration layering, presets, overrides and rule-file validation."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish, tempdir, write  # noqa: E402
from lib import config, rules as rulelib  # noqa: E402


def rule_yaml(**extra):
    body = {
        'id': 'x', 'title': 't', 'severity': 'warn',
        'applies_to': {'stacks': ['php']},
        'detect': {'when_line_added': 'foo'},
        'message': 'm',
    }
    body.update(extra)
    return body


def expect_error(name, raw, needle):
    try:
        rulelib.normalize(raw, 'x.yaml', 'local')
    except rulelib.RuleError as exc:
        check(name, needle in str(exc), str(exc))
        return
    check(name, False, 'no error raised')


def case_schema():
    print('case_schema:')
    rule = rulelib.normalize(rule_yaml(), 'x.yaml', 'local')
    check('a minimal rule loads as a line rule', rule['kind'] == 'line' and rule['id'] == 'local/x')
    expect_error('0.x keys are rejected with a migration hint',
                 {'triggers': {'code_regex': 'x'}, 'applies_to': {'stacks': ['*']}}, 'migrate.py')
    expect_error('stacks is required', rule_yaml(applies_to={'files': ['*.php']}), 'stacks')
    expect_error('two anchors are rejected',
                 rule_yaml(detect={'when_line_added': 'a', 'file_regex': 'b'}), '정확히 하나')
    expect_error('when_file_added needs a requirement',
                 rule_yaml(detect={'when_file_added': True}), 'must_contain_in_file')
    expect_error('when_changed needs require_changed',
                 rule_yaml(detect={'when_changed': ['routes/**']}), 'require_changed')
    expect_error('a bad regex names the field', rule_yaml(detect={'when_line_added': '('}),
                 'when_line_added')
    expect_error('semantic_review needs an instruction',
                 rule_yaml(semantic_review={'context': ['imports']}), 'instruction')
    expect_error('unknown context providers are rejected',
                 rule_yaml(semantic_review={'instruction': 'i', 'context': ['whole_repo']}),
                 'whole_repo')
    expect_error('fix.auto only on plain line rules',
                 rule_yaml(detect={'file_regex': 'a'}, fix={'auto': {'replace': 'a', 'with': 'b'}}),
                 'fix.auto')
    semantic = rulelib.normalize(rule_yaml(semantic_review={'instruction': 'judge'}), 'x.yaml',
                                 'local')
    check('semantic rules default to the current function as context',
          semantic['review']['context'] == ['current_function'], semantic['review'])


def case_config_layers():
    print('case_config_layers:')
    with tempdir() as repo:
        cfg = config.load(repo, ROOT)
        check('defaults load with no repo config', cfg['mode'] == 'fix' and not cfg.notes,
              cfg.notes)

        write(repo, '.claude/convention-guard/config.yaml',
              'mode: report\nlimits:\n  max_error_rules: 2\nlinters:\n  bogus: 1\n')
        cfg = config.load(repo, ROOT)
        check('repo values win', cfg['mode'] == 'report' and cfg.limit('max_error_rules') == 2)
        check('untouched nested defaults survive a partial group',
              cfg.limit('max_warn_rules') == config.DEFAULTS['limits']['max_warn_rules'])
        check('unknown nested keys are reported',
              any('linters.bogus' in text for _, text in cfg.notes), cfg.notes)

        os.environ['CLAUDE_PLUGIN_OPTION_REPORT_ONLY'] = 'false'
        try:
            cfg = config.load(repo, ROOT)
            check('the team config beats the install preference', cfg['mode'] == 'report')
        finally:
            del os.environ['CLAUDE_PLUGIN_OPTION_REPORT_ONLY']

        write(repo, '.claude/convention-guard/config.yaml', 'max_rules: 3\nblock_level: report\n')
        cfg = config.load(repo, ROOT)
        errors = [text for level, text in cfg.notes if level == 'error']
        check('0.x keys are errors that point at migrate.py',
              len(errors) == 2 and all('migrate.py' in e for e in errors), cfg.notes)


def case_presets_and_overrides():
    print('case_presets_and_overrides:')
    with tempdir() as repo:
        auto = rulelib.load(repo, ROOT, config.DEFAULTS, {'php', 'laravel'})
        ids = {r['id'] for r in auto.rules}
        check('auto enables the stack presets', 'core/php-no-debug-output' in ids)
        check('auto leaves opt-in presets off', 'core/layer-boundary' not in ids)
        check('an opt-in rule is listed as inactive with its reason',
              ('core/layer-boundary', 'preset 비활성') in
              {(r['id'], why) for r, why in auto.inactive})

        cfg = dict(config.DEFAULTS, presets=['auto', 'architecture'], disable=['core/no-orphan-todo'],
                   severity={'core/php-line-too-long': 'error'})
        loaded = rulelib.load(repo, ROOT, cfg, {'php'})
        ids = {r['id']: r for r in loaded.rules}
        check('an explicit preset adds to auto', 'core/layer-boundary' in ids)
        check('disable removes a rule', 'core/no-orphan-todo' not in ids)
        check('severity override applies and remembers the base',
              ids['core/php-line-too-long']['severity'] == 'error'
              and ids['core/php-line-too-long']['base_severity'] == 'info')

        bad = rulelib.load(repo, ROOT, dict(config.DEFAULTS, presets=['nope']), {'php'})
        check('an unknown preset is an error', any('nope' in t for _, t in bad.notes), bad.notes)

        write(repo, '.claude/convention-guard/rules/blade.yaml',
              'override: core/laravel-no-query-in-blade\nseverity: warn\n'
              'applies_to:\n  exclude: ["resources/views/admin/**"]\n')
        patched = {r['id']: r for r in
                   rulelib.load(repo, ROOT, config.DEFAULTS, {'php', 'laravel'}).rules}
        rule = patched['core/laravel-no-query-in-blade']
        check('an override deep-merges: new exclude, original files kept',
              rule['exclude'] == ['resources/views/admin/**'] and rule['files'] == ['**/*.blade.php'],
              (rule['exclude'], rule['files']))
        check('an override keeps the detector', rule['kind'] == 'line')
        check('an override records where it came from',
              rule['source'] == 'core<-local' and rule.get('base_severity') == 'error', rule['source'])

        write(repo, '.claude/convention-rules/config.yaml', 'max_rules: 3\n')
        os.remove(os.path.join(repo, '.claude', 'convention-guard', 'rules', 'blade.yaml'))
        os.rmdir(os.path.join(repo, '.claude', 'convention-guard', 'rules'))
        os.rmdir(os.path.join(repo, '.claude', 'convention-guard'))
        legacy = rulelib.load(repo, ROOT, config.DEFAULTS, {'php'})
        check('an unmigrated 0.x layout is an error',
              any('migrate.py' in t for lv, t in legacy.notes if lv == 'error'), legacy.notes)


if __name__ == '__main__':
    case_schema()
    case_config_layers()
    case_presets_and_overrides()
    sys.exit(finish('설정·프리셋·오버라이드·스키마'))
