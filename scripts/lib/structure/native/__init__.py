"""The default backend: masking and scopes with nothing but the standard library."""

from ..model import FileStructure, fail_code, line_starts
from . import langs, mask, scopes


class NativeBackend:
    name = 'native'

    def supports(self, language):
        return langs.definition(language) is not None

    def analyze(self, text, language):
        try:
            return self._analyze(text, language)
        except Exception as exc:                        # noqa: BLE001 -- NR-14
            return FileStructure.failed(fail_code(exc), text=text, language=language,
                                        backend=self.name)

    def _analyze(self, text, language):
        definition = langs.definition(language)
        if definition is None:
            return FileStructure.failed('unsupported_language', text=text,
                                        language=language, backend=self.name)
        masked = mask.scan(text, definition)
        starts = line_starts(text)
        supported = definition.block_style is not None
        if masked.reason is not None:
            # the spans found before the failure are kept for diagnosis only;
            # condition evaluation stops at `ok` (SR-27)
            return FileStructure.failed(masked.reason, text=text, language=language,
                                        backend=self.name, comments=masked.comments,
                                        strings=masked.strings,
                                        scope_supported=supported)
        root = scopes.build(text, definition, masked)
        return FileStructure(text, language=language, backend=self.name,
                             scope_supported=supported,
                             comments=masked.comments, strings=masked.strings,
                             root=root, starts=starts)
