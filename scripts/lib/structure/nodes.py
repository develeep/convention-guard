"""What each language's tree means to the structure conditions, as data.

A language is a row: which file names it covers, which grammar parses it,
and which node types are a comment, literal text, a function, a loop, a
class, a catch or a branch. Nothing else in the layer knows a node name.
tests/structure/test_nodes.py checks every name below against the pinned
grammar, so a grammar upgrade that renames one fails there first.

Literal text (`string`) is the node minus the code inside it: a template's
`${...}`, an f-string's `{...}`, PHP's `"{$a->b()}"` -- PHP has no wrapper
node there, so "code" is any named child that is not a literal part.

Iteration written as a call -- `xs.forEach(x => ...)`, `$users->each(fn ...)`,
`array_map(fn ...)`, `map(lambda ...)` -- still needs the names: the grammar
says "a call with a function argument", not "a loop". A function handed to
one of these calls is both a loop and a function.
"""

import os
import re

_JS_FUNCTIONS = ('function_declaration', 'function_expression', 'generator_function_declaration',
                 'generator_function', 'arrow_function', 'method_definition')
_JS_LOOPS = ('for_statement', 'for_in_statement', 'while_statement', 'do_statement')
_JS_BRANCHES = ('if_statement', 'else_clause', 'switch_statement', 'try_statement',
                'finally_clause')
_JS_ITERATION = ('map', 'forEach', 'each', 'flatMap', 'filter', 'reduce', 'reduceRight', 'some',
                 'every', 'find', 'findIndex', 'sort')

JS = {
    'comment': ('comment', 'html_comment'),
    'string': ('string', 'template_string', 'regex', 'jsx_text'),
    'literal_parts': ('string_fragment', 'escape_sequence', 'regex_pattern', 'regex_flags',
                      'html_character_reference'),
    'string_containers': (),
    'function': _JS_FUNCTIONS,
    'loop': _JS_LOOPS,
    'class': ('class_declaration', 'class', 'abstract_class_declaration',
              'interface_declaration'),
    'catch': ('catch_clause',),
    'branch': _JS_BRANCHES,
    'calls': {'call_expression': ('function', 'arguments')},
    'member_name': {'member_expression': 'property'},
    'argument_wrappers': (),
    'iteration_methods': _JS_ITERATION,
    'iteration_functions': (),
    'decorated': (),
    'pack': ('function',),
    'imports': r'(?:import\b|export\s+(?:\*|\{)|(?:const|let|var)\s+.*=\s*require\()',
}

PHP = {
    'comment': ('comment',),
    'string': ('string', 'encapsed_string', 'heredoc', 'nowdoc', 'shell_command_expression',
               'text'),
    'literal_parts': ('string_content', 'escape_sequence', 'heredoc_start', 'heredoc_end',
                      'nowdoc_body', 'nowdoc_string'),
    'string_containers': ('heredoc_body',),
    'function': ('function_definition', 'method_declaration', 'anonymous_function',
                 'arrow_function'),
    'loop': ('for_statement', 'foreach_statement', 'while_statement', 'do_statement'),
    'class': ('class_declaration', 'interface_declaration', 'trait_declaration',
              'enum_declaration'),
    'catch': ('catch_clause',),
    'branch': ('if_statement', 'else_clause', 'else_if_clause', 'switch_statement',
               'try_statement', 'finally_clause'),
    'calls': {'member_call_expression': ('name', 'arguments'),
              'nullsafe_member_call_expression': ('name', 'arguments'),
              'scoped_call_expression': ('name', 'arguments'),
              'function_call_expression': ('function', 'arguments')},
    'member_name': {},
    'argument_wrappers': ('argument',),
    'iteration_methods': ('each', 'map', 'filter', 'reject', 'transform', 'flatMap', 'every',
                          'partition', 'groupBy', 'sortBy'),
    'iteration_functions': ('array_map', 'array_filter', 'array_walk', 'array_reduce'),
    'decorated': (),
    'pack': ('function',),
    'imports': r'(?:use\s+[\w\\]|require(?:_once)?\b|include(?:_once)?\b)',
}

PY = {
    'comment': ('comment',),
    'string': ('string',),
    'literal_parts': ('string_start', 'string_content', 'string_end', 'escape_sequence',
                      'escape_interpolation'),
    'string_containers': (),
    'function': ('function_definition', 'lambda'),
    'loop': ('for_statement', 'while_statement', 'list_comprehension', 'set_comprehension',
             'dictionary_comprehension', 'generator_expression'),
    'class': ('class_definition',),
    'catch': ('except_clause',),
    'branch': ('if_statement', 'elif_clause', 'else_clause', 'try_statement', 'finally_clause',
               'with_statement', 'match_statement'),
    'calls': {'call': ('function', 'arguments')},
    'member_name': {'attribute': 'attribute'},
    'argument_wrappers': ('keyword_argument',),
    'iteration_methods': (),
    'iteration_functions': ('map', 'filter', 'reduce', 'sorted'),
    'decorated': ('decorated_definition',),
    # a line directly in a class body has always shown the class (context.py)
    'pack': ('function', 'class'),
    'imports': r'(?:import\b|from\s+\S+\s+import\b)',
}

# language -> (row, grammar). Blade is PHP islands in a template (blade.py).
LANGUAGES = {
    'js': (JS, 'js'),
    'ts': (JS, 'ts'),
    'tsx': (JS, 'tsx'),
    'php': (PHP, 'php'),
    'blade': (PHP, 'php_only'),
    'py': (PY, 'py'),
}

SUFFIXES = (
    ('.blade.php', 'blade'), ('.php', 'php'),
    ('.tsx', 'tsx'), ('.ts', 'ts'), ('.mts', 'ts'), ('.cts', 'ts'),
    ('.jsx', 'js'), ('.js', 'js'), ('.mjs', 'js'), ('.cjs', 'js'),
    ('.py', 'py'), ('.pyi', 'py'),
)

KINDS = ('function', 'loop', 'class', 'catch', 'branch')

IMPORT_PATTERNS = {name: re.compile(r'^\s*' + row['imports'])
                   for name, (row, _grammar) in LANGUAGES.items()}


def language_of(relpath):
    """File name -> language, or None. Whole suffixes, so `.blade.php` wins."""
    name = os.path.basename(str(relpath or '')).lower()
    for suffix, language in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return language
    return None


def row(language):
    found = LANGUAGES.get(language)
    return found[0] if found else None


def grammar(language):
    found = LANGUAGES.get(language)
    return found[1] if found else None


def kind_of(row_, node_type):
    for kind in KINDS:
        if node_type in row_[kind]:
            return kind
    return None
