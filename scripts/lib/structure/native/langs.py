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

# Iteration written as a call that takes a callback. Only these get it: the
# ported languages keep 1.x behaviour (unit-of-work.md §3.1), and Go has no
# callback-iteration idiom. A name counts only where it is called -- after a
# member operator for methods, bare for functions -- and only when the block
# is the callback's body (scopes.py:_iterates).
ITERATION_METHODS = {
    'php': ('each', 'map', 'filter', 'reject', 'transform', 'flatMap', 'every',
            'partition', 'groupBy', 'sortBy'),
    'js': ('map', 'forEach', 'each', 'flatMap', 'filter', 'reduce', 'reduceRight',
           'some', 'every', 'find', 'findIndex', 'sort'),
    'kotlin': ('forEach', 'forEachIndexed', 'map', 'mapIndexed', 'mapNotNull', 'flatMap',
               'filter', 'filterNot', 'fold', 'reduce', 'onEach', 'any', 'all', 'none',
               'find', 'first', 'sumOf', 'groupBy', 'associateBy', 'associateWith',
               'sortedBy'),
}
ITERATION_FUNCTIONS = {
    'php': ('array_map', 'array_filter', 'array_walk', 'array_reduce'),
    'kotlin': ('repeat',),
}

FUNCTION_PATTERNS = {
    'php': re.compile(r'\bfunction\s+&?\s*\w+\s*\('),
    'js': re.compile(r'\bfunction\s*\*?\s*\w*\s*\(|^\s*(?:export\s+)?(?:default\s+)?'
                     r'(?:(?:public|private|protected|static|async|get|set|readonly)\s+)*'
                     + NOT_A_NAME +
                     r'[\w$]+\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^={;]+)?\s*\{?\s*$'
                     r'|^\s*(?:export\s+)?(?:const|let|var)\s+[\w$]+\s*=\s*(?:async\s*)?'
                     r'(?:\([^)]*\)|[\w$]+)\s*(?::\s*[^=]+)?=>'),
    'go': re.compile(r'^\s*func\b'),
    'java': re.compile(r'^\s*(?:@\w+\s+)*(?:(?:public|private|protected|static|final|'
                       r'override|suspend|fun|async|internal)\s+)*' + NOT_A_NAME +
                       r'[\w<>\[\],.?]+(?:\s+[\w<>\[\],.?]+)*\s+' + NOT_A_NAME + r'\w+\s*'
                       r'\([^;]*\)\s*(?:throws [\w., ]+)?\s*\{?\s*$|\bfun\s+\w+\s*\('),
    'rust': re.compile(r'\bfn\s+\w+'),
    'c': re.compile(r'^[\w\*\s&:<>,]+\s+\**' + NOT_A_NAME + r'\w+\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$'),
}


class Token(NamedTuple):
    """A literal token, optionally guarded by a lookaround.

    PHP's `#` opens a comment but `#[` opens an attribute -- the guard keeps
    the distinction `context.py:_strip_strings` already made.
    """

    text: str
    guard: Optional[str] = None


class Delim(NamedTuple):
    """A single-line string delimiter.

    `escape` of one character takes the next character with it (`\\"`); a
    longer one is complete on its own (C#'s doubled `""`). `guard` is a
    lookahead the opener must satisfy -- see CHAR_LITERAL.
    """

    open: str
    escape: Optional[str] = None
    interpolation: Optional[Tuple[str, str]] = None
    guard: Optional[str] = None


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
    # `/.../flags` can be a literal (JS). Its quotes and backticks open nothing,
    # and a `/` right after a value is division (SR-12b).
    regex_literals: bool = False
    # `<Tag>` after `(`, `return`, `=>`, ... opens JSX: its text is literal
    # text and `{...}` inside it is code. Off for .ts, where `<T>(x) =>` is a
    # generic.
    jsx: bool = False
    # after these words an operand is expected, so `/` opens a regex
    regex_after_words: Tuple[str, ...] = ()
    # words whose `(...)` is a header, not a value: `if (x) /re/`
    control_heads: Tuple[str, ...] = ()
    # after these words `<Tag` opens JSX
    jsx_after_words: Tuple[str, ...] = ()
    function_pattern: Optional[re.Pattern] = None
    # Iteration that is written as a call taking a callback -- `xs.map(x => {`,
    # `$users->each(function ($u) {`. FR-01.2 counts `each` and `map` as loops,
    # and a keyword list cannot see them because they are method names.
    iteration_methods: Tuple[str, ...] = ()                    # `.name(` / `->name(`
    iteration_functions: Tuple[str, ...] = ()                  # bare `name(`
    # What marks a block as a lambda's body: an arrow right before `{`, or a
    # keyword such as `function` at the block's level. A lambda is a function,
    # and one handed to an iteration call is a loop too.
    lambda_heads: Tuple[str, ...] = ()
    # Semicolons may be left out (JS), so a header can run over a finished
    # statement -- `save(x)` on the line before `if (y) {`. Function patterns
    # then look at the last statement only.
    optional_semicolons: bool = False
    # `.class`, `::class`, `->for(` are names, not keywords.
    member_ops: Tuple[str, ...] = ()
    # Kotlin's `items.forEach {` -- the block follows the call instead of
    # sitting inside its parentheses.
    trailing_lambdas: bool = False
    # A line break ends a statement (Go, Kotlin), so `;` belongs to a header
    # such as Go's `for i := 0; i < n; i++ {` instead of cutting it.
    newline_ends_statement: bool = False
    # Keywords that open a block, judged only where the block's own brace
    # sits: not inside the header's parentheses, not after a member operator.
    class_keywords: Tuple[str, ...] = ()
    loop_keywords: Tuple[str, ...] = ()
    branch_keywords: Tuple[str, ...] = ()
    catch_keywords: Tuple[str, ...] = ()
    block_style: Optional[str] = None                          # 'brace' | 'indent' | None
    # indent languages: (kind, header regex after the indentation)
    indent_headers: Tuple[Tuple[str, str], ...] = ()
    # a standard-library parser tried before the indent rules ('python_ast')
    parser: Optional[str] = None
    # the start of an import statement, for a reviewer's `imports` section;
    # a bracket it leaves open is read to its close (R21)
    import_pattern: Optional[re.Pattern] = None
    # the blocks a context pack is cut to (R21; was PACK_SCOPES in context.py)
    pack_scopes: Tuple[str, ...] = ('function',)
    # indent languages: a line starting with this decorates the header below
    decorator_prefix: str = ''


C_BLOCK = (('/*', '*/', False),)
SLASH = (Token('//'),)
# PHP interpolates `{$expr}` inside double quotes and heredocs, and that
# expression is code -- `"{$user->dd()}"` must not hide a match (Q4=C).
PHP_QUOTES = (Delim("'", '\\'), Delim('"', '\\', ('{$', '}')))
QUOTES = (Delim("'", '\\'), Delim('"', '\\'))
JS_REGEX_AFTER = ('return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'new', 'delete',
                  'void', 'throw', 'instanceof', 'yield', 'await')
JS_CONTROL_HEADS = ('if', 'while', 'for', 'with')
JS_JSX_AFTER = ('return', 'yield', 'default', 'case', 'else', 'do', 'await')
# A quote that opens a character literal: one character or one escape, then
# the closing quote. Rust's `'a` lifetime and C++14's `1'000` open nothing.
CHAR_LITERAL = r"(?=(?:[^\\\n]|\\(?:u\{[0-9A-Fa-f]{1,6}\}|x[0-9A-Fa-f]{2}|[^\n]))')"
CHAR_QUOTES = (Delim("'", '\\', guard=CHAR_LITERAL), Delim('"', '\\'))

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
        iteration_methods=ITERATION_METHODS['php'],
        iteration_functions=ITERATION_FUNCTIONS['php'],
        lambda_heads=('function', 'fn'),
        member_ops=('?->', '->', '::'),
        class_keywords=('class', 'interface', 'trait', 'enum'),
        loop_keywords=('for', 'foreach', 'while', 'do'),
        branch_keywords=('if', 'elseif', 'else', 'switch', 'match'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'js': LangDef(
        name='js',
        suffixes=('.js', '.jsx', '.mjs', '.cjs', '.tsx'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('`', '`', escape='\\', interpolation=('${', '}')),),
        regex_literals=True,
        regex_after_words=JS_REGEX_AFTER,
        control_heads=JS_CONTROL_HEADS,
        jsx=True,
        jsx_after_words=JS_JSX_AFTER,
        function_pattern=FUNCTION_PATTERNS['js'],
        iteration_methods=ITERATION_METHODS['js'],
        lambda_heads=('=>', 'function'),
        optional_semicolons=True,
        member_ops=('?.', '.'),
        class_keywords=('class', 'interface', 'enum'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    # JavaScript without JSX: in a .ts file `<T>(x) => x` is a generic.
    'ts': LangDef(
        name='ts',
        suffixes=('.ts', '.mts', '.cts'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('`', '`', escape='\\', interpolation=('${', '}')),),
        regex_literals=True,
        regex_after_words=JS_REGEX_AFTER,
        control_heads=JS_CONTROL_HEADS,
        function_pattern=FUNCTION_PATTERNS['js'],
        iteration_methods=ITERATION_METHODS['js'],
        lambda_heads=('=>', 'function'),
        optional_semicolons=True,
        member_ops=('?.', '.'),
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
        lambda_heads=('func',),
        member_ops=('.',),
        newline_ends_statement=True,
        class_keywords=('struct', 'interface'),
        loop_keywords=('for', 'range'),
        branch_keywords=('if', 'else', 'switch', 'select'),
        block_style='brace',
    ),
    'java': LangDef(
        name='java',
        suffixes=('.java', '.scala'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('"""', '"""', escape='\\'),),
        function_pattern=FUNCTION_PATTERNS['java'],
        # Java `->`, C#/Scala `=>`, Swift `func`
        lambda_heads=('->', '=>', 'func'),
        member_ops=('.', '::'),
        class_keywords=('class', 'interface', 'enum', 'record', 'struct', 'object'),
        loop_keywords=('for', 'while', 'do'),
        # `case 1 -> {` is a switch arm, not a lambda
        branch_keywords=('if', 'else', 'switch', 'when', 'case', 'default'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    # Masked exactly as the java row it was split from; what it adds is the
    # grammar of statements -- line breaks end them, lambdas trail the call.
    'kotlin': LangDef(
        name='kotlin',
        suffixes=('.kt', '.kts'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        multiline_strings=(Multiline('"""', '"""', escape='\\'),),
        function_pattern=FUNCTION_PATTERNS['java'],
        iteration_methods=ITERATION_METHODS['kotlin'],
        iteration_functions=ITERATION_FUNCTIONS['kotlin'],
        member_ops=('?.', '.', '::'),
        trailing_lambdas=True,
        newline_ends_statement=True,
        class_keywords=('class', 'interface', 'enum', 'record', 'struct', 'object'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch', 'when'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'swift': LangDef(
        name='swift',
        suffixes=('.swift',),
        line_comment=SLASH,
        block_comment=(('/*', '*/', True),),
        # `'` is not a Swift delimiter; `#"..."#` is raw, `\(x)` rides the escape
        string_delims=(Delim('"', '\\'),),
        multiline_strings=(Multiline('#"""', '"""#'), Multiline('#"', '"#'),
                           Multiline('"""', '"""', escape='\\')),
        function_pattern=FUNCTION_PATTERNS['java'],
        lambda_heads=('func',),
        member_ops=('.', '?.'),
        newline_ends_statement=True,
        class_keywords=('class', 'struct', 'enum', 'protocol', 'extension'),
        loop_keywords=('for', 'while', 'repeat'),
        branch_keywords=('if', 'else', 'switch', 'guard'),
        catch_keywords=('catch',),
        block_style='brace',
    ),
    'csharp': LangDef(
        name='csharp',
        suffixes=('.cs',),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=QUOTES,
        # `@"C:\dir\"` has no backslash escapes; `""` is a quote
        multiline_strings=(Multiline('"""', '"""'), Multiline('@"', '"', escape='""')),
        function_pattern=FUNCTION_PATTERNS['java'],
        lambda_heads=('=>',),
        member_ops=('.', '?.'),
        class_keywords=('class', 'interface', 'enum', 'record', 'struct', 'namespace'),
        loop_keywords=('for', 'foreach', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch', 'case', 'default'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'dart': LangDef(
        name='dart',
        suffixes=('.dart',),
        line_comment=SLASH,
        block_comment=(('/*', '*/', True),),
        string_delims=(Delim("'", '\\', ('${', '}')), Delim('"', '\\', ('${', '}'))),
        multiline_strings=(Multiline("'''", "'''", escape='\\', interpolation=('${', '}')),
                           Multiline('"""', '"""', escape='\\', interpolation=('${', '}'))),
        function_pattern=FUNCTION_PATTERNS['java'],
        member_ops=('.', '?.'),
        class_keywords=('class', 'mixin', 'enum', 'extension'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch'),
        catch_keywords=('catch', 'finally'),
        block_style='brace',
    ),
    'rust': LangDef(
        name='rust',
        suffixes=('.rs',),
        line_comment=SLASH,
        block_comment=(('/*', '*/', True),),
        string_delims=CHAR_QUOTES,
        multiline_strings=(Multiline('r#"', '"#'), Multiline('r"', '"')),
        function_pattern=FUNCTION_PATTERNS['rust'],
        lambda_heads=('|', '||'),
        member_ops=('.', '::'),
        class_keywords=('struct', 'enum', 'trait', 'impl', 'mod'),
        loop_keywords=('for', 'while', 'loop'),
        branch_keywords=('if', 'else', 'match'),
        block_style='brace',
    ),
    'c': LangDef(
        name='c',
        suffixes=('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hh', '.hxx'),
        line_comment=SLASH,
        block_comment=C_BLOCK,
        string_delims=CHAR_QUOTES,
        multiline_strings=(Multiline('R"(', ')"'),),
        function_pattern=FUNCTION_PATTERNS['c'],
        member_ops=('.', '->', '::'),
        class_keywords=('struct', 'class', 'union', 'enum', 'namespace'),
        loop_keywords=('for', 'while', 'do'),
        branch_keywords=('if', 'else', 'switch'),
        catch_keywords=('catch',),
        block_style='brace',
    ),
    'py': LangDef(
        name='py',
        suffixes=('.py', '.pyi'),
        line_comment=(Token('#'),),
        string_delims=QUOTES,
        multiline_strings=(Multiline("'''", "'''", escape='\\'),
                           Multiline('"""', '"""', escape='\\')),
        class_keywords=('class',),
        catch_keywords=('except',),
        block_style='indent',
        indent_headers=(('function', r'(?:async\s+)?def\s+\w+'),
                        ('class', r'class\s+\w+'),
                        ('catch', r'except\b'),
                        ('loop', r'(?:async\s+)?(?:for|while)\b')),
        parser='python_ast',
        pack_scopes=('function', 'class'),
        decorator_prefix='@',
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

# Single-file components: markup with a `<script>` island, read like Blade --
# the template's apostrophes are prose and its `{{ }}` braces are not code;
# inside the island it is JavaScript (R23a).
for _name, _suffix in (('vue', '.vue'), ('svelte', '.svelte')):
    LANGUAGES[_name] = LANGUAGES['js']._replace(
        name=_name, suffixes=(_suffix,), tag_boundaries=(('<script', '</script>'),),
        starts_in_code=False, jsx=False, jsx_after_words=())

# How each language names what it depends on (R21). ts, vue and svelte read
# like js; Blade has no blocks to tell a file-level `use` from a trait.
IMPORT_PATTERNS = {
    'php': r'(?:use\s+[\w\\]|require(?:_once)?\b|include(?:_once)?\b)',
    'js': r'(?:import\b|export\s+(?:\*|\{)|(?:const|let|var)\s+.*=\s*require\()',
    'go': r'(?:package|import)\b',
    'java': r'(?:package|import)\b',
    'kotlin': r'(?:package|import)\b',
    'swift': r'import\b',
    'csharp': r'using\s+(?:static\s+)?[\w.]+\s*(?:=|;)',
    'dart': r'(?:import|export|part|library)\b',
    'rust': r'(?:use\b|extern\s+crate\b|mod\s+\w+\s*;)',
    'c': r'#\s*include\b',
    'py': r'(?:import\b|from\s+\S+\s+import\b)',
}
for _name in list(LANGUAGES):
    _pattern = IMPORT_PATTERNS.get({'ts': 'js', 'vue': 'js', 'svelte': 'js'}.get(_name, _name))
    if _pattern:
        LANGUAGES[_name] = LANGUAGES[_name]._replace(
            import_pattern=re.compile(r'^\s*' + _pattern))

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
