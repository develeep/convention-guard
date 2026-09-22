"""Run a rule against its own `tests.match` / `tests.no_match` fragments.

Both the fixture runner and `migrate.py` have to answer the same question --
"would this rule fire on this snippet?" -- and they have to answer it the same
way. A migration that adds `not_in: [comment]` is only safe if the tool that
approves it matches exactly like the suite that will later hold the rule to
it, so the matching lives here, once, and both sides import it (MR-09).
"""

import re

from .. import structure
from ..structure import conditions
from ..structure.model import REJECT, Span
from .select import match_any

# A fixture is a fragment, not a file: a PHP snippet has no `<?php`, so the
# structure layer would read all of it as template text and find neither
# comments nor strings. The prologue makes the fragment a file. It is part of
# the synthesised text, so detection and analysis share one coordinate system
# (DR-25, DR-26). `tests.lang_prefix: false` opts out.
PROLOGUE = {'php': '<?php\n'}


EXTENSIONS = re.compile(r'\.(\w+)|\{([\w,]+)\}')


def fixture_language(rule):
    """The language a fixture fragment should be read as.

    `applies_to.files` holds globs, and a glob is not a filename: brace lists
    like `**/*.{ts,tsx,js}` have to be opened up before an extension is
    visible at all.
    """
    declared = (rule.get('tests') or {}).get('lang')
    if declared:
        return declared
    for pattern in rule.get('files') or ():
        for dotted, braced in EXTENSIONS.findall(str(pattern)):
            for extension in (braced.split(',') if braced else [dotted]):
                language = structure.language_of('x.%s' % extension.strip())
                if language:
                    return language
    return None


def synthesise(rule, sample):
    """(text, language) -- the fragment as a file."""
    language = fixture_language(rule)
    if not language or rule['tests'].get('lang_prefix', True) is False:
        return str(sample), language
    return PROLOGUE.get(language, '') + str(sample), language


def passes_conditions(rule, text, language, match):
    """Would the detector keep this match? UNKNOWN keeps it (D5)."""
    analysed = structure.analyze(text, language)
    if not analysed.ok:
        return True
    span = Span(match.start(), match.end())
    return conditions.evaluate(rule, analysed, span) != REJECT


def matcher(rule):
    kind = rule['kind']
    if conditions.has_conditions(rule) and kind in ('line', 'requires', 'file'):
        plain = _plain_matcher(rule)

        def check(sample):
            text, language = synthesise(rule, sample)
            pattern = rule['compiled_file'] if kind == 'file' else rule['compiled_when']
            match = pattern.search(text)
            if match is None or not plain(sample):
                return False
            return passes_conditions(rule, text, language, match)
        return check
    return _plain_matcher(rule)


def _plain_matcher(rule):
    kind = rule['kind']
    if kind == 'paired':
        def check(sample):
            paths = [sample] if isinstance(sample, str) else list(sample)
            if not any(match_any(rule['when_changed'], p) for p in paths):
                return False
            return not any(match_any(rule['require_changed'], p) for p in paths)
        return check
    if kind == 'absent':
        return lambda s: not rule['compiled_must'].search(str(s))
    if kind == 'requires':
        return lambda s: (bool(rule['compiled_when'].search(str(s)))
                          and not rule['compiled_must'].search(str(s)))
    if kind == 'file':
        return lambda s: bool(rule['compiled_file'].search(str(s)))
    return lambda s: bool(rule['compiled_when'].search(str(s)))
