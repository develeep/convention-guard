"""What each language looks like, as data.

Adding a language means adding a row here -- nothing in `mask.py` or
`scopes.py` knows a language name (NFR-03.3, checked by
tests/structure/test_determinism.py).

The function-header patterns and the extension table are lifted from
`context.py` unchanged: the four "ported" languages (java family, rust, c
family, python) are meant to keep behaving as they did, so their heuristics
move rather than improve (unit-of-work.md §3.1).
"""

import os
import re
from typing import NamedTuple, Optional, Tuple

# `for (...) {` and `} else if (...) {` look exactly like a method header to a
# regex; these words are never a function name. (context.py:53, verbatim)
NOT_A_NAME = r'(?!(?:if|for|foreach|while|switch|catch|with|return|else|do|try|synchronized)\b)'

FUNCTION_PATTERNS = {
    'php': re.compile(r'\bfunction\s+&?\s*\w+\s*\('),
    'js': re.compile(r'\bfunction\s*\*?\s*\w*\s*\(|^\s*(?:export\s+)?(?:default\s+)?'
                     r'(?:(?:public|private|protected|static|async|get|set|readonly)\s+)*'
                     + NOT_A_NAME +
                     r'[\w$]+\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^={;]+)?\s*\{\s*$'
                     r'|^\s*(?:export\s+)?(?:const|let|var)\s+[\w$]+\s*=\s*(?:async\s*)?'
                     r'(?:\([^)]*\)|[\w$]+)\s*(?::\s*[^=]+)?=>'),
    'go': re.compile(r'^\s*func\b'),
    'java': re.compile(r'^\s*(?:@\w+\s+)*(?:(?:public|private|protected|static|final|'
                       r'override|suspend|fun|async|internal)\s+)*' + NOT_A_NAME +
                       r'[\w<>\[\],.?]+(?:\s+[\w<>\[\],.?]+)*\s+' + NOT_A_NAME + r'\w+\s*'
                       r'\([^;]*\)\s*(?:throws [\w., ]+)?\s*\{?\s*$|\bfun\s+\w+\s*\('),
    'rust': re.compile(r'\bfn\s+\w+'),
    'c': re.compile(r'^[\w\*\s&:<>,]+\s+\**\w+\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$'),
    'py': re.compile(r'^(\s*)(?:async\s+)?def\s+\w+'),
}
PY_CLASS = re.compile(r'^(\s*)class\s+\w+')
PY_EXCEPT = re.compile(r'^(\s*)except\b')


class Token(NamedTuple):
    """A literal token, optionally guarded by a lookaround.

    PHP's `#` opens a comment but `#[` opens an attribute -- the guard keeps
    the distinction `context.py:_strip_strings` already made.
    """

    text: str
    guard: Optional[str] = None


class Delim(NamedTuple):
    """A single-line string delimiter."""

    open: str
    escape: Optional[str] = None
    interpolation: Optional[Tuple[str, str]] = None


class Multiline(NamedTuple):
    """A string literal that may cross lines."""

    open: str
    close: str
    escape: Optional[str] = None
    interpolation: Optional[Tuple[str, str]] = None
    # 'token'        -- ends at `close`
    # 'heredoc_line' -- `open` reads an identifier, which ends it on its own line
    terminator: str = 'token'


class LangDef(NamedTuple):
    name: str
    suffixes: Tuple[str, ...]
    line_comment: Tuple[Token, ...] = ()
    block_comment: Tuple[Tuple[str, str, bool], ...] = ()     # (open, close, nestable)
    string_delims: Tuple[Delim, ...] = ()
    multiline_strings: Tuple[Multiline, ...] = ()
    tag_boundaries: Tuple[Tuple[str, str], ...] = ()
    text_comment: Tuple[Tuple[str, str, bool], ...] = ()       # comments outside tags
    starts_in_code: bool = True
    function_pattern: Optional[re.Pattern] = None
    class_keywords: Tuple[str, ...] = ()
    loop_keywords: Tuple[str, ...] = ()
    branch_keywords: Tuple[str, ...] = ()
    catch_keywords: Tuple[str, ...] = ()
    block_style: Optional[str] = None                          # 'brace' | 'indent' | None


C_BLOCK = (('/*', '*/', False),)
SLASH = (Token('//'),)
# PHP interpolates `{$expr}` inside double quotes and heredocs, and that
# expression is code -- `"{$user->dd()}"` must not hide a match (Q4=C).
PHP_QUOTES = (Delim("'", '\\'), Delim('"', '\\', ('{$', '}')))
QUOTES = (Delim("'", '\\'), Delim('"', '\\'))

_PHP_HEREDOC = Multiline('<<<', '', escape='\\', interpolation=('{$', '}'),
                         terminator='heredoc_line')
_PHP_STRINGS = (_PHP_HEREDOC,)

LANGUAGES = {
    'php': LangDef(
        name='php',
        suffixes=('.php',),
        line_comment=(Token('//'), Token('#', guard=r'(?!\[)')),
        block_comment=C_BLOCK,
        string_delims=PHP_QUOTES,
        multiline_strings=_PHP_STRINGS,
        tag_boundaries=(('<?php', '?>'), ('<?=', '?>')),
        starts_in_code=False,
        function_pattern=FUNCTION_PATTERNS['php'],
        class_keywords=('class', 'interface', 'trait', 'enum'),
        loop_keywords=('for', 'foreach', 'while', 'do'),
        branch_keywords=('if', 'elseif', 'else', 'switch', 'match'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'js': LangDef(
        name='js',
        suffixes=('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('`', '`', escape='\\', interpolation=('${', '}')),),
        function_pattern=FUNCTION_PATTERNS['js'],
        class_keywords=('class', 'interface', 'enum'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'go': LangDef(
        name='go',
        suffixes=('.go',),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('`', '`'),),
        function_pattern=FUNCTION_PATTERNS['go'],
        class_keywords=('struct', 'interface'),
        loop_keywords=('for', 'range'),
        branch_keywords=('if', 'else', 'switch', 'select'),
        block_style='brace',
    ),
    'java': LangDef(
        name='java',
        suffixes=('.java', '.kt', '.cs', '.swift', '.scala', '.dart'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('"""', '"""', escape='\\'),),
        function_pattern=FUNCTION_PATTERNS['java'],
        class_keywords=('class', 'interface', 'enum', 'record', 'struct', 'object'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch', 'when'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'rust': LangDef(
        name='rust',
        suffixes=('.rs',),
        line_comment=SLASH,
        block_comment=(('/*', '*/', True),),
        string_delims=QUOTES,
        multiline_strings=(Multiline('r#"', '"#'), Multiline('r"', '"')),
        function_pattern=FUNCTION_PATTERNS['rust'],
        class_keywords=('struct', 'enum', 'trait', 'impl', 'mod'),
        loop_keywords=('for', 'while', 'loop'),
        branch_keywords=('if', 'else', 'match'),
        block_style='brace',
    ),
    'c': LangDef(
        name='c',
        suffixes=('.c', '.cc', '.cpp', '.h'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        function_pattern=FUNCTION_PATTERNS['c'],
        class_keywords=('struct', 'class', 'union', 'enum', 'namespace'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch'),
        catch_keywords=('catch',),
        block_style='brace',
    ),
    'py': LangDef(
        name='py',
        suffixes=('.py',),
        line_comment=(Token('#'),),
        string_delims=QUOTES,
        multiline_strings=(Multiline("'''", "'''", escape='\\'),
                           Multiline('"""', '"""', escape='\\')),
        function_pattern=FUNCTION_PATTERNS['py'],
        class_keywords=('class',),
        catch_keywords=('except',),
        block_style='indent',
    ),
    # Masking only: a Blade file is template text with islands of PHP, and its
    # apostrophes are prose. Without this split every `<p>It's fine</p>` would
    # leave an unterminated string and the file would come back ok=False,
    # disarming the very rules that target Blade (CQ2=B).
    'blade': LangDef(
        name='blade',
        suffixes=('.blade.php',),
        line_comment=(Token('//'), Token('#', guard=r'(?!\[)')),
        block_comment=C_BLOCK,
        string_delims=PHP_QUOTES,
        multiline_strings=_PHP_STRINGS,
        tag_boundaries=(('<?php', '?>'), ('<?=', '?>'), ('@php', '@endphp')),
        text_comment=(('{{--', '--}}', False),),
        starts_in_code=False,
        block_style=None,
    ),
}

# longest suffix first, so `.blade.php` is matched before `.php`
_BY_SUFFIX = sorted(
    ((suffix, name) for name, definition in LANGUAGES.items()
     for suffix in definition.suffixes),
    key=lambda pair: -len(pair[0]))


def definition(language):
    return LANGUAGES.get(language)


def language_of(relpath):
    """Extension -> language identifier, or None when unsupported.

    `os.path.splitext` cannot see `.blade.php`, so this matches whole
    filename suffixes, longest first.
    """
    name = os.path.basename(str(relpath or '')).lower()
    for suffix, language in _BY_SUFFIX:
        if name.endswith(suffix) and len(name) > len(suffix):
            return language
    return None
