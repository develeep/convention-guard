"""Who analyses which language.

One implementation exists (`native`), and it handles every language, so this
is deliberately thin: an interface with two methods and a dict. It is here
because FR-01.4 asks that a different parser -- tree-sitter, one day -- can be
dropped in without the rule schema or the detector noticing, and an interface
written after the fact is written around whatever the first implementation
happened to do.

Per-language backends are possible but not the default: giving one language a
better parser than another is exactly the gap US-14 says must not exist.
"""


class StructureBackend:
    """A parser for the structure layer."""

    name = 'abstract'

    def supports(self, language):
        raise NotImplementedError

    def analyze(self, text, language):
        """-> FileStructure. Never raises; failure is `ok=False`."""
        raise NotImplementedError


_EXPLICIT = {}
_FALLBACKS = []


def register(backend, languages=None):
    """Register `backend`, for the named languages or for whatever it supports."""
    if languages:
        for language in languages:
            _EXPLICIT[language] = backend
    else:
        _FALLBACKS.append(backend)


def resolve(language):
    """The backend for `language`, or None."""
    backend = _EXPLICIT.get(language)
    if backend is not None:
        return backend
    for candidate in _FALLBACKS:            # registration order, so it is stable
        if candidate.supports(language):
            return candidate
    return None


def reset_backends():
    """Drop every registration and restore the defaults. Tests only."""
    _EXPLICIT.clear()
    del _FALLBACKS[:]
    from .native import NativeBackend
    register(NativeBackend())
