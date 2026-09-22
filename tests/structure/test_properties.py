#!/usr/bin/env python3
"""Properties of the structure layer, over generated sources.

The invariants are the ones written down in `domain-entities.md` §8 and the
property list in `testable-properties.md` §1. The generator makes source-like
text -- comments, strings, heredocs, blocks, and a quarter of it broken on
purpose -- because random characters would never reach the interesting paths.

Requires Hypothesis (requirements-dev.txt).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, strategies as st  # noqa: E402

from helpers import check, corpus, finish  # noqa: E402
from helpers.property_runner import run  # noqa: E402
from lib import structure  # noqa: E402
from lib.structure.model import Span  # noqa: E402

# 200 lines is the ceiling for a property example (testable-properties.md §2);
# the 10,000-line cases belong to the performance harness.
sources = st.builds(
    corpus.make_file,
    language=st.sampled_from(corpus.LANGUAGES),
    seed=st.integers(min_value=0, max_value=2 ** 16),
    lines=st.integers(min_value=1, max_value=200),
    density=st.sampled_from(sorted(corpus.DENSITIES)),
    broken=st.floats(min_value=0.0, max_value=0.9),
)
languages = st.sampled_from(corpus.LANGUAGES)


def _analyze(language, text):
    return structure.analyze(text, language)


@given(languages, sources)
def prop_never_raises(language, text):
    """P-14: no input makes the layer throw."""
    fs = _analyze(language, text)
    assert fs.ok in (True, False)
    if not fs.ok:
        assert fs.reason and ':' in fs.reason or fs.reason in (
            'unsupported_language', 'no_backend')


@given(languages, sources)
def prop_line_count_is_preserved(language, text):
    """P-03 / INV-01: analysis does not touch the text."""
    fs = _analyze(language, text)
    assert fs.text == text
    assert fs.line_of(len(text)) == text.count('\n') + 1


@given(languages, sources, st.integers(min_value=1, max_value=400))
def prop_coordinates_round_trip(language, text, lineno):
    """P-01 / INV-02."""
    fs = _analyze(language, text)
    lineno = min(lineno, text.count('\n') + 1)
    assert fs.line_of(fs.offset_of(lineno)) == lineno


@given(languages, sources)
def prop_spans_are_sorted_disjoint_and_in_range(language, text):
    """P-04, P-05, P-06 / INV-03~INV-05."""
    fs = _analyze(language, text)
    spans = sorted(fs.comments + fs.strings)
    previous_end = 0
    for span in spans:
        assert 0 <= span.start < span.end <= len(text), (span, len(text))
        assert span.start >= previous_end, (span, previous_end)
        previous_end = span.end


@given(languages, sources)
def prop_scopes_nest(language, text):
    """P-07, P-08 / INV-06, INV-07."""
    fs = _analyze(language, text)

    def walk(node):
        for child in node.children:
            assert node.start_line <= child.start_line, (node, child)
            assert child.end_line <= node.end_line, (node, child)
            if child.body is not None:
                assert 0 <= child.body.start <= child.body.end <= len(text)
            walk(child)
        for left, right in zip(node.children, node.children[1:]):
            assert left.end_line < right.start_line or left.end_line <= right.start_line

    walk(fs.root)


@given(languages, sources, st.integers(min_value=1, max_value=400))
def prop_scope_path_is_a_chain(language, text, lineno):
    """P-09 / INV-08."""
    fs = _analyze(language, text)
    path = fs.scopes_at(min(lineno, text.count('\n') + 1))
    assert path[0].kind == 'file'
    for parent, child in zip(path, path[1:]):
        assert child in parent.children


@given(languages, sources)
def prop_analysis_is_deterministic(language, text):
    """P-10 / INV-09 -- same input, same answer, cache or no cache."""
    first = _analyze(language, text)
    structure.reset_cache()
    second = _analyze(language, text)
    assert (first.ok, first.reason) == (second.ok, second.reason)
    assert first.comments == second.comments and first.strings == second.strings
    assert _shape(first.root) == _shape(second.root)


@given(languages, sources)
def prop_cache_returns_the_same_object(language, text):
    """P-12 -- a hit is the value that was stored, not a recomputation."""
    first = _analyze(language, text)
    assert _analyze(language, text) is first


@given(languages, sources)
def prop_masking_is_idempotent(language, text):
    """P-15 -- blanking what was found leaves nothing to find."""
    fs = _analyze(language, text)
    if not fs.ok:
        return
    blanked = list(text)
    for span in fs.comments + fs.strings:
        for i in range(span.start, span.end):
            if blanked[i] != '\n':
                blanked[i] = ' '
    again = structure.analyze(''.join(blanked), language)
    assert again.comments == () and again.strings == (), (again.comments, again.strings)


@given(languages, sources, st.integers(min_value=0, max_value=5000))
def prop_evaluate_is_pure(language, text, offset):
    """P-13 -- judging twice gives the same verdict and changes nothing."""
    from lib.structure import conditions
    fs = _analyze(language, text)
    offset = min(offset, max(len(text) - 1, 0))
    span = Span(offset, min(offset + 3, len(text)))
    rule = {'detect': {'not_in': ['comment', 'string']}}
    first = conditions.evaluate(rule, fs, span)
    assert conditions.evaluate(rule, fs, span) == first
    assert fs.text == text


def _shape(node):
    return (node.kind, node.start_line, node.end_line,
            tuple(_shape(child) for child in node.children))


def main():
    print('case_properties:')
    run([prop_never_raises,
         prop_line_count_is_preserved,
         prop_coordinates_round_trip,
         prop_spans_are_sorted_disjoint_and_in_range,
         prop_scopes_nest,
         prop_scope_path_is_a_chain,
         prop_analysis_is_deterministic,
         prop_cache_returns_the_same_object,
         prop_masking_is_idempotent,
         prop_evaluate_is_pure], check)
    return finish('structure properties')


if __name__ == '__main__':
    sys.exit(main())
