"""The structure engine, if it is here: tree-sitter and its grammars.

    engine = loader.get()
    if engine.ok:  engine.parse(text, 'php') -> (tree, data bytes)
    else:          engine.reason -> 'disabled' | 'unsupported' | 'installing'
                                    | 'failed' | 'not_installed' | 'import_failed'

Only the pinned install directory is looked at (install.py) -- never a
tree-sitter that happens to be importable from site-packages, so two machines
cannot judge the same code with two parser versions. Imported once per
process, and only when a structure condition actually has a match to judge:
a Stop whose regex gates found nothing never pays for the import.
"""

import os
import sys

from . import install

GRAMMARS = {
    # language -> (module, function)
    'js': ('tree_sitter_javascript', 'language'),
    'ts': ('tree_sitter_typescript', 'language_typescript'),
    'tsx': ('tree_sitter_typescript', 'language_tsx'),
    'php': ('tree_sitter_php', 'language_php'),
    'php_only': ('tree_sitter_php', 'language_php_only'),
    'py': ('tree_sitter_python', 'language'),
}


class Missing:
    ok = False

    def __init__(self, reason, detail=''):
        self.reason, self.detail = reason, detail

    def describe(self):
        words = {'disabled': '꺼짐 (CONVENTION_GUARD_NO_ENGINE)', 'unsupported': '미지원 플랫폼',
                 'installing': '설치 중', 'failed': '설치 실패',
                 'not_installed': '설치 전', 'import_failed': '불러오기 실패'}
        text = words.get(self.reason, self.reason)
        return '%s: %s' % (text, self.detail) if self.detail else text


class Engine:
    ok = True
    reason = None

    def __init__(self, module, path):
        self.ts = module
        self.path = path
        self._languages = {}
        self._parsers = {}

    def language(self, name):
        if name not in self._languages:
            module, function = GRAMMARS[name]
            grammar = __import__(module)
            self._languages[name] = self.ts.Language(getattr(grammar, function)())
        return self._languages[name]

    def parse(self, data, name):
        """Tree for `data` (bytes) in grammar `name`."""
        if name not in self._parsers:
            self._parsers[name] = self.ts.Parser(self.language(name))
        return self._parsers[name].parse(data)


_cached = None


def reset():
    """Tests only."""
    global _cached
    _cached = None


def get():
    global _cached
    if _cached is None:
        _cached = _load()
    return _cached


def _load():
    if os.environ.get('CONVENTION_GUARD_NO_ENGINE'):
        return Missing('disabled')
    try:
        lock = install.read_lock()
        path = install.installed(lock)
        if path is None:
            try:
                install.choose(lock)
            except install.InstallError as exc:
                return Missing('unsupported', str(exc).split(': ', 1)[-1])
            status = install.read_status()
            state = status.get('state')
            if state in ('installing', 'failed'):
                return Missing(state, status.get('reason') or '')
            return Missing('not_installed')
        if path not in sys.path:
            sys.path.insert(0, path)
        import tree_sitter
        engine = Engine(tree_sitter, path)
        engine.language('php')          # a broken install shows up here, not mid-judgment
        return engine
    except Exception as exc:            # noqa: BLE001 -- the engine is optional, the hook is not
        return Missing('import_failed', type(exc).__name__)
