"""Does this match satisfy the rule's structure conditions?

Three conditions, all filters: they never invent a candidate, never change a
snippet and never touch the fingerprint (D4). They only answer accept, reject
or "could not tell".

"Could not tell" is a real answer. When the file did not parse, the candidate
is kept and the file is reported as unchecked -- a structure the layer failed
to read must never look like a clean pass (FR-01.5).
"""

from .model import ACCEPT, REJECT, UNKNOWN

CONDITION_KEYS = ('not_in', 'in_scope', 'block_empty')
MASK_TARGETS = ('comment', 'string')
SCOPE_TARGETS = ('loop', 'function', 'class', 'catch')


def has_conditions(rule):
    """Is it worth reading and analysing the file for this rule?

    The detector asks this before touching the file: a rule without structure
    conditions has to run exactly the 1.x path (FR-02.3).
    """
    detect = (rule or {}).get('detect') or {}
    return any(detect.get(key) for key in CONDITION_KEYS)


def evaluate(rule, structure, span):
    """ACCEPT / REJECT / UNKNOWN for one match position."""
    try:
        return _evaluate(rule, structure, span)
    except Exception:                       # noqa: BLE001 -- NR-14, never raise
        return UNKNOWN


def _evaluate(rule, structure, span):
    if not structure.ok:
        return UNKNOWN                      # the spans below it are untrusted (SR-27)
    detect = (rule or {}).get('detect') or {}
    verdicts = []
    if detect.get('not_in'):
        verdicts.append(_not_in(detect['not_in'], structure, span))
    if detect.get('in_scope'):
        verdicts.append(_in_scope(detect['in_scope'], structure, span))
    if detect.get('block_empty'):
        verdicts.append(_block_empty(structure, span))
    # a reject is evidence; an unknown is the absence of it (SR-26)
    if REJECT in verdicts:
        return REJECT
    if UNKNOWN in verdicts:
        return UNKNOWN
    return ACCEPT


def _as_list(value):
    return [value] if isinstance(value, str) else list(value or ())


def _not_in(targets, structure, span):
    for target in _as_list(targets):
        if target == 'comment' and structure.in_comment(span):
            return REJECT
        if target == 'string' and structure.in_string(span):
            return REJECT
    return ACCEPT


def _in_scope(targets, structure, span):
    if not structure.scope_supported:
        return UNKNOWN                      # the language offers no tree (SR-25)
    kinds = {node.kind for node in structure.scopes_at(structure.line_of(span.start))}
    for target in _as_list(targets):
        if target not in kinds:
            return REJECT
    return ACCEPT


def _block_empty(structure, span):
    """Is the block around the match empty of everything but whitespace?

    A comment counts as content: `php-no-empty-catch` promises that a reason
    written down keeps the rule quiet, and its no_match fixture holds us to it
    (corrected FR-02.1, US-10).
    """
    if not structure.scope_supported:
        return UNKNOWN
    first = structure.line_of(span.start)
    last = structure.line_of(max(span.end - 1, span.start))
    node = _innermost_block(structure.root, first, last)
    if node is None or node.body is None:
        return REJECT                       # no block around it is an answer (SR-24)
    return ACCEPT if not structure.text[node.body.start:node.body.end].strip() else REJECT


def _innermost_block(node, first, last):
    """The deepest block that spans the match (SR-22).

    A `file_regex` match usually covers the header and both braces -- the
    block it belongs to is the one whose own lines contain it, not one whose
    body does.
    """
    for child in node.children:
        if child.contains_line(first) and child.contains_line(last):
            return _innermost_block(child, first, last) or child
    return None
