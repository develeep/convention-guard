#!/usr/bin/env python3
"""Comment and string spans, per language.

`business-rules.md` SR-01~SR-12. Spans include their delimiters (Q1=A), an
interpolation hole splits a literal into fragments (CQ1=A), and a token left
open at end of file is a failure, not a guess (Q2=B).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib.structure.native import langs, mask  # noqa: E402

PHP = '<?php\n'


def run(text, language='php'):
    return mask.scan(text, langs.definition(language))


def pieces(text, spans):
    return [text[s.start:s.end] for s in spans]


def case_basics():
    print('case_basics:')
    text = PHP + '$x = "dd(1)"; // note\n'
    res = run(text)
    check('a string span includes both quotes', pieces(text, res.strings) == ['"dd(1)"'],
          str(pieces(text, res.strings)))
    check('a line comment span includes the slashes but not the newline',
          pieces(text, res.comments) == ['// note'], str(pieces(text, res.comments)))
    check('a clean file has no reason', res.reason is None)

    text = PHP + "// it's fine\n$y = 1;\n"
    res = run(text)
    check('a quote inside a comment opens nothing (SR-02)',
          res.strings == () and len(res.comments) == 1)

    text = PHP + '$url = "http://x";\n'
    res = run(text)
    check('slashes inside a string open no comment (SR-03)',
          res.comments == () and pieces(text, res.strings) == ['"http://x"'])

    text = PHP + '$a = "a\\"b"; $c = 1;\n'
    res = run(text)
    check('an escaped quote does not close the string (SR-04)',
          pieces(text, res.strings) == ['"a\\"b"'], str(pieces(text, res.strings)))


def case_php_specifics():
    print('case_php_specifics:')
    text = PHP + '#[Attr]\nclass A {}\n'
    res = run(text)
    check('an attribute is not a comment (SR §9-8)', res.comments == (),
          str(pieces(text, res.comments)))

    text = PHP + '# note\n'
    res = run(text)
    check('a hash comment still works', pieces(text, res.comments) == ['# note'])

    text = "<html>It's fine</html>\n" + PHP + "$x = 1;\n"
    res = run(text)
    check('text outside the php tag is neither code nor string (SR-11)',
          res.ok and res.strings == () and res.comments == ())

    text = PHP + '$sql = <<<SQL\n  select "a" -- x\nSQL;\n'
    res = run(text)
    check('a heredoc is one string span (SR-09)',
          len(res.strings) == 1 and res.strings[0].start == text.index('<<<'),
          str(pieces(text, res.strings)))
    check('the heredoc ends at its identifier line',
          text[res.strings[0].end - 3:res.strings[0].end] == 'SQL')

    text = PHP + "$sql = <<<'SQL'\n  {$nope}\nSQL;\n"
    res = run(text)
    check('a nowdoc does not interpolate', len(res.strings) == 1)


def case_interpolation():
    print('case_interpolation:')
    text = 'const m = `hello ${name} world`;\n'
    res = run(text, 'js')
    got = pieces(text, res.strings)
    check('a template literal splits into fragments (CQ1=A)',
          got == ['`hello ${', '} world`'], str(got))

    text = 'const m = `${ {a: 1} }`;\n'
    res = run(text, 'js')
    got = pieces(text, res.strings)
    check('braces inside the hole do not close it early',
          got == ['`${', '}`'], str(got))

    text = 'const m = `a ${ `b ${c}` } d`;\n'
    res = run(text, 'js')
    check('a nested template literal is handled', res.reason is None and len(res.strings) == 4,
          str(pieces(text, res.strings)))

    text = PHP + '$m = "{$user->dd()} ok";\n'
    res = run(text)
    got = pieces(text, res.strings)
    check('php interpolates inside double quotes (Q4=C)',
          got == ['"{$', '} ok"'], str(got))

    text = PHP + "$m = '{$user}';\n"
    res = run(text)
    check('php single quotes do not interpolate',
          pieces(text, res.strings) == ["'{$user}'"], str(pieces(text, res.strings)))


def case_other_languages():
    print('case_other_languages:')
    text = 'x := `raw // not a comment`\n'
    res = run(text, 'go')
    check('a go raw string swallows slashes',
          res.comments == () and pieces(text, res.strings) == ['`raw // not a comment`'])

    text = '/* a /* b */ c */\nfn x() {}\n'
    res = run(text, 'rust')
    check('rust block comments nest (SR-08)',
          pieces(text, res.comments) == ['/* a /* b */ c */'], str(pieces(text, res.comments)))

    text = '/* a /* b */\nint x;\n'
    res = run(text, 'c')
    check('c block comments do not nest',
          pieces(text, res.comments) == ['/* a /* b */'], str(pieces(text, res.comments)))

    text = 'def f():\n    """doc \'x\'"""\n    return 1\n'
    res = run(text, 'py')
    check('a python triple quote is one string',
          pieces(text, res.strings) == ['"""doc \'x\'"""'], str(pieces(text, res.strings)))


def case_blade():
    print('case_blade:')
    text = "<p>It's fine</p>\n@php\n$x = 1;\n@endphp\n"
    res = run(text, 'blade')
    check('an apostrophe in template text is prose, not a string (CQ2=B)',
          res.ok and res.reason is None, str(res.reason))
    check('blade text produces no spans', res.strings == ())

    text = "{{-- note --}}\n<p>x</p>\n"
    res = run(text, 'blade')
    check('a blade comment is a comment',
          pieces(text, res.comments) == ['{{-- note --}}'], str(pieces(text, res.comments)))

    text = "<p>a</p>\n<?php $s = 'x'; ?>\n<p>b's</p>\n"
    res = run(text, 'blade')
    check('strings inside a php island are found',
          res.ok and pieces(text, res.strings) == ["'x'"], str(pieces(text, res.strings)))


def case_failures():
    print('case_failures:')
    res = run(PHP + '$a = "oops;\n$b = 1;\n')
    check('an unterminated string fails with its line',
          res.reason == 'unterminated_string:2', str(res.reason))

    res = run(PHP + '/* open\nstill open\n')
    check('an unterminated block comment fails',
          res.reason == 'unterminated_block_comment:2', str(res.reason))

    res = run(PHP + '$x = <<<SQL\nselect 1\n')
    check('an unterminated heredoc fails',
          res.reason == 'unterminated_heredoc:2', str(res.reason))

    res = run('const m = `a ${ b\n', 'js')
    check('an unterminated interpolation fails',
          res.reason == 'unterminated_interpolation:1', str(res.reason))

    res = run(PHP + '$a = 1; // fine\n')
    check('a line comment at end of file is not a failure', res.reason is None)

    res = run(PHP + 'if (a) { b();\n')
    check('an unbalanced brace is not a masking failure (Q2=B, not C)', res.reason is None)

    text = PHP + '$a = "x";\n'
    res = run(text)
    check('spans never overlap and stay in range',
          all(0 <= s.start < s.end <= len(text) for s in res.strings + res.comments))


def main():
    for case in (case_basics, case_php_specifics, case_interpolation,
                 case_other_languages, case_blade, case_failures):
        case()
    return finish('structure.native.mask')


if __name__ == '__main__':
    sys.exit(main())
