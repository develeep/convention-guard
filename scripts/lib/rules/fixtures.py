"""Run a rule against its own `tests.match` / `tests.no_match` fragments.

"Would this rule fire on this snippet?" -- answered the way detection
answers it: fragments are composed into a file and matched with the same
structure conditions.
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


def has_requirement(rule, sample):
    """Like the detector: a requirement in a comment does not count (R6)."""
    text, language = synthesise(rule, sample)
    found, _reason = conditions.requirement_present(
        rule, text, lambda: structure.analyze(text, language))
    return found


def matcher(rule):
    kind = rule['kind']
    if conditions.has_conditions(rule) and kind in ('line', 'requires', 'file'):
        plain = _plain_matcher(rule)

        def check(sample):
            text, language = synthesise(rule, sample)
            pattern = rule['compiled_file'] if kind == 'file' else rule['compiled_when']
            if not plain(sample):
                return False
            # like the detector: any match the conditions keep is enough (R5)
            return any(passes_conditions(rule, text, language, match)
                       for match in pattern.finditer(text))
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
        return lambda s: not has_requirement(rule, s)
    if kind == 'requires':
        return lambda s: (bool(rule['compiled_when'].search(str(s)))
                          and not has_requirement(rule, s))
    if kind == 'file':
        return lambda s: bool(rule['compiled_file'].search(str(s)))
    return lambda s: bool(rule['compiled_when'].search(str(s)))
