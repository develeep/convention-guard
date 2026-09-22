"""Structure-aware analysis of one file: comments, strings and blocks.

    fs = structure.analyze(text, structure.language_of(relpath))
    if fs.ok and fs.in_comment(span):
        ...                       # the match is inside a comment, not code

The layer answers with values and never raises: a file it cannot parse comes
back `ok=False` with a reason, and the caller keeps the candidate and says the
file was not checked rather than passing it silently (FR-01.5, NR-14).

Results are memoised per process, keyed by the text itself, so the same file
read by thirty rules is analysed once. The hook is a fresh process every turn,
so nothing is written to disk (D7).
"""

import hashlib
from collections import OrderedDict

from . import backend as backendlib
from .model import ACCEPT, REJECT, UNKNOWN, FileStructure, ScopeNode, Span, fail_code
from .native import NativeBackend
from .native.langs import definition as _definition, language_of

# `cache.py` keeps the same ceiling. A hook only ever analyses the files in the
# change, but `scan.py --all` walks the whole repository (NR-13).
CACHE_MAX_ENTRIES = 1000

_CACHE = OrderedDict()

backendlib.register(NativeBackend())

__all__ = ['ACCEPT', 'REJECT', 'UNKNOWN', 'FileStructure', 'ScopeNode', 'Span',
           'analyze', 'language_of', 'reset_cache', 'cache_size', 'CACHE_MAX_ENTRIES']


def analyze(text, language):
    """FileStructure for this text, from cache when it has been seen."""
    try:
        text = text or ''
        key = (hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest(), language)
        hit = _CACHE.get(key)
        if hit is not None:
            return hit
        result = _analyze(text, language)
        _CACHE[key] = result
        if len(_CACHE) > CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
        return result
    except Exception as exc:                            # noqa: BLE001 -- NR-14
        return FileStructure.failed(fail_code(exc), text=text or '', language=language)


def _analyze(text, language):
    chosen = backendlib.resolve(language)
    if chosen is not None:
        return chosen.analyze(text, language)
    # a language nobody defined, versus a defined one nobody claimed: the
    # second only happens when a backend was unregistered
    reason = 'unsupported_language' if _definition(language) is None else 'no_backend'
    return FileStructure.failed(reason, text=text, language=language)


def reset_cache():
    """Empty the memo. Tests only -- the hook is short-lived by nature."""
    _CACHE.clear()


def cache_size():
    return len(_CACHE)
