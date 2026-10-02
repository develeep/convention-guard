"""Structure-aware analysis of one file: comments, literal text and blocks.

    fs = structure.analyze(text, structure.language_of(relpath))
    if fs.ok and fs.in_comment(span):
        ...                       # the match is inside a comment, not code

The structure comes from tree-sitter (engine/), read through a table per
language (nodes.py); Blade templates are read by blade.py around their PHP.
There is no built-in fallback: without the engine every file comes back
`ok=False` with reason `engine_missing:<why>`, every structure condition is
UNKNOWN, the candidate is kept and the file is named (design §4.6). A file
the engine could only partly read is judged up to the first place it could
not read; a match from there on is UNKNOWN.

The layer answers with values and never raises. Results are memoised per
process, keyed by the text, so thirty rules reading one file analyse it once.
"""

import hashlib
from collections import OrderedDict

from . import nodes
from .model import ACCEPT, REJECT, UNKNOWN, FileStructure, ScopeNode, Span, fail_code
from .nodes import language_of

# `cache.py` keeps the same ceiling. A hook only ever analyses the files in the
# change, but `scan.py --all` walks the whole repository.
CACHE_MAX_ENTRIES = 1000

_CACHE = OrderedDict()

__all__ = ['ACCEPT', 'REJECT', 'UNKNOWN', 'FileStructure', 'ScopeNode', 'Span',
           'analyze', 'language_of', 'engine', 'reset_cache', 'cache_size', 'CACHE_MAX_ENTRIES']


def engine():
    """The loaded engine, or loader.Missing saying why there is none."""
    from ..engine import loader
    return loader.get()


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
    except Exception as exc:                            # noqa: BLE001 -- never raise
        return FileStructure.failed(fail_code(exc), text=text or '', language=language)


def _analyze(text, language):
    if nodes.row(language) is None:
        return FileStructure.failed('unsupported_language', text=text, language=language)
    found = engine()
    if not found.ok:
        return FileStructure.failed('engine_missing:%s' % found.reason, text=text,
                                    language=language)
    if language == 'blade':
        from . import blade
        return blade.analyze(found, text)
    from . import treesitter
    return treesitter.analyze(found, text, language)


def reset_cache():
    """Empty the memo. Tests only -- the hook is short-lived by nature."""
    _CACHE.clear()


def cache_size():
    return len(_CACHE)
