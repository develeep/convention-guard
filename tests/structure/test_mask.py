#!/usr/bin/env python3
"""Comment and string spans, per language.

`business-rules.md` SR-01~SR-12b. Spans include their delimiters (Q1=A), an
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


def case_js_regex_literals():
    """SR-12b. A regex literal is one literal span; its quotes, backticks and
    slashes open nothing. When `/` could be either, it is division."""
    print('case_js_regex_literals:')
    for label, src, literal in (
            ("a quote in a regex opens no string", 'x.replaceAll(/\'/g, "")', "/\'/g"),
            ('a double quote in a regex opens no string', 'x.split(/"/)', '/"/'),
            ('a backtick in a regex opens no template', 'x.split(/`/)', '/`/'),
            ('a slash inside a character class does not end it', 'x.split(/[*/]/)', '/[*/]/'),
            ('an escaped slash does not end it', "x.match(/a\\/'b/)", "/a\\/'b/"),
            ('a regex after return', "return /'/.test(s);", "/'/"),
            ('a regex after =', "const r = /'/g;", "/'/g")):
        text = src + '\n'
        res = run(text, 'js')
        check(label, res.ok and literal in pieces(text, res.strings),
              '%s %s' % (res.reason, pieces(text, res.strings)))
    for label, src in (('division between identifiers', "a / b; c = 'x';"),
                       ('division after a call', "f(a) / 2; s = 'y';"),
                       ('division after a number', "n = 10 / 2 / 5; s = 'z';"),
                       ('division after an index', "xs[0] / xs[1]; s = 'w';")):
        text = src + '\n'
        res = run(text, 'js')
        check(label + ' is not a regex', res.ok and all(
            not p.startswith('/') for p in pieces(text, res.strings)),
            '%s %s' % (res.reason, pieces(text, res.strings)))
    # after `;` a slash reads as a regex opener, but no `/` closes it on the line
    res = run("w = {};\n/ 2 + 'q';\n", 'js')
    check('a slash with no closing slash on its line is division, not a failure',
          res.ok, str(res.reason))
    text = "if (/{/.test(s)) {\n  go();\n}\n"
    res = run(text, 'js')
    check('a regex is not code: its braces are masked', res.ok and '/{/' in pieces(
        text, res.strings), str(pieces(text, res.strings)))
    res = run(PHP + "$x = f('a') / 2;\n", 'php')
    check('php has no regex literals: a slash is just a slash', res.ok, str(res.reason))


def case_r9_regex_context():
    """R9(b): `/` is division only after a value; everywhere else a regex."""
    print('case_r9_regex_context:')
    for label, src, literal in (
            ('a regex after an arrow', 'const f = s => /"/.test(s);', '/"/'),
            ('a regex after a binary operator', 'a + /"/.test(s);', '/"/'),
            ('a regex after a control header', 'if (x) /"/.test(s);', '/"/'),
            ('a regex after a while header', "while (x) /'/.test(y);", "/'/")):
        text = src + '\n'
        res = run(text, 'js')
        check(label, res.ok and literal in pieces(text, res.strings),
              '%s %s' % (res.reason, pieces(text, res.strings)))
    for label, src in (('division after a postfix increment', "a++ / 2; s = 'x';"),
                       ('division after a closing call', "(a + b) / 2; s = 'y';"),
                       ('division after a string', "'a' / 2; s = 'z';")):
        text = src + '\n'
        res = run(text, 'js')
        check(label + ' is not a regex', res.ok and all(
            not p.startswith('/') for p in pieces(text, res.strings)),
            '%s %s' % (res.reason, pieces(text, res.strings)))


def case_r9_char_literals():
    print('case_r9_char_literals:')
    text = "fn f<'a>(x: &'a str) -> &'a str { x }\n"
    res = run(text, 'rust')
    check('a rust lifetime opens no string', res.ok and res.strings == (),
          '%s %s' % (res.reason, pieces(text, res.strings)))
    text = "let c = 'x'; let d = '\\n'; let q = '\\''; let e = '\\u{1F600}';\n"
    res = run(text, 'rust')
    got = pieces(text, res.strings)
    check('rust char literals are still strings',
          res.ok and got == ["'x'", "'\\n'", "'\\''", "'\\u{1F600}'"], '%s %s' % (res.reason, got))
    text = "int n = 1'000'000; char c = 'a';\n"
    res = run(text, 'c')
    check('a c++ digit separator opens no string',
          res.ok and pieces(text, res.strings) == ["'a'"],
          '%s %s' % (res.reason, pieces(text, res.strings)))


def case_r9_raw_strings():
    print('case_r9_raw_strings:')
    for label, language, text, literal in (
            ('a c# verbatim string ends at its quote', 'csharp',
             'var p = @"C:\\dir\\"; var q = 1;\n', '@"C:\\dir\\"'),
            ('a c# verbatim string escapes a quote by doubling it', 'csharp',
             'var s = @"say ""hi"" now"; var q = 1;\n', '@"say ""hi"" now"'),
            ('a swift raw string', 'swift', 'let r = #"a "quoted" \\n"#\nlet q = 1\n',
             '#"a "quoted" \\n"#'),
            ('a c++ raw string', 'c', 'auto r = R"(a "b" c)"; int q;\n', 'R"(a "b" c)"')):
        res = run(text, language)
        check(label, res.ok and literal in pieces(text, res.strings),
              '%s %s' % (res.reason, pieces(text, res.strings)))
    text = '/* a /* b */ c */\nlet x = 1\n'
    for language in ('swift', 'dart'):
        res = run(text, language)
        check('%s block comments nest' % language,
              pieces(text, res.comments) == ['/* a /* b */ c */'], str(pieces(text, res.comments)))
    text = "var s = 'hi ${user.name}!';\n"
    res = run(text, 'dart')
    check('dart interpolates code inside quotes',
          pieces(text, res.strings) == ["'hi ${", "}!'"], str(pieces(text, res.strings)))


def case_r9_heredoc_interpolation():
    print('case_r9_heredoc_interpolation:')
    text = PHP + '$h = <<<EOT\n  hello {$u->dd()} there\nEOT;\n$x = 1;\n'
    res = run(text)
    at = text.index('dd()')
    check('code in a heredoc interpolation is code',
          res.ok and not any(s.start <= at < s.end for s in res.strings),
          '%s %s' % (res.reason, pieces(text, res.strings)))
    check('the heredoc still ends at its identifier line',
          res.ok and pieces(text, res.strings)[-1].endswith('EOT'), str(pieces(text, res.strings)))


def case_r9_jsx():
    """R9(c): JSX children are literal text (strings); `{...}` inside is code."""
    print('case_r9_jsx:')
    text = "const a = <p>Don't do this</p>;\nconst b = 'ok';\n"
    res = run(text, 'js')
    check('an apostrophe in jsx text opens no string', res.ok, str(res.reason))
    check('the jsx text is recorded as a string',
          any("Don't do this" in p for p in pieces(text, res.strings)), str(pieces(text, res.strings)))

    text = ('function A({ user }) {\n  return (\n    <div className="it\'s">\n'
            "      <span>{user.name}'s page</span>\n"
            '      <img src={user.pic} />\n      <>frag</>\n'
            '      {items.map(i => <li key={i}>{i}</li>)}\n'
            '      <button onClick={() => go()}>Go</button>\n    </div>\n  );\n}\n')
    res = run(text, 'js')
    check('a component with nested jsx masks cleanly', res.ok, str(res.reason))
    for needle in ('user.name', 'user.pic', 'items.map', 'go()'):
        at = text.index(needle)
        check('%s inside braces is code' % needle,
              not any(s.start <= at < s.end for s in res.strings), str(pieces(text, res.strings)))
    at = text.index("'s page")
    check('text next to an expression is text',
          any(s.start <= at < s.end for s in res.strings), str(pieces(text, res.strings)))

    text = 'if (a < b && c > d) { go(); }\nconst s = "x";\n'
    res = run(text, 'js')
    check('a comparison is not jsx', res.ok and pieces(text, res.strings) == ['"x"'],
          '%s %s' % (res.reason, pieces(text, res.strings)))

    text = "const f = <T>(x: T) => x;\nconst s = 'ok';\n"
    res = run(text, 'ts')
    check('a .ts generic arrow is not jsx', res.ok and pieces(text, res.strings) == ["'ok'"],
          '%s %s' % (res.reason, pieces(text, res.strings)))

    res = run('const a = <div>\n  open\n', 'js')
    check('an unclosed jsx element fails instead of hiding the file',
          res.reason == 'unterminated_jsx:1', str(res.reason))


def case_r9_jsx_text_bounds():
    """R9 follow-up: jsx text is the prose only -- not the braces around an
    expression, not the whitespace between tags -- so blanking what was found
    leaves nothing to find (P-15)."""
    print('case_r9_jsx_text_bounds:')
    text = '<p>a{x}b</p>\n'
    res = run(text, 'js')
    check('the braces belong to the expression', pieces(text, res.strings) == ['a', 'b'],
          str(pieces(text, res.strings)))
    text = '<div>\n  <p>x</p>\n</div>\n'
    res = run(text, 'js')
    check('whitespace between tags is no string', pieces(text, res.strings) == ['x'],
          str(pieces(text, res.strings)))
    for text in ("<p>It's</p>\n", '<p>a{x}b</p>\n'):
        res = run(text, 'js')
        blanked = list(text)
        for span in res.strings:
            for i in range(span.start, span.end):
                blanked[i] = ' ' if blanked[i] != '\n' else '\n'
        again = run(''.join(blanked), 'js')
        check('blanking %r leaves nothing to find' % text, again.strings == (),
              str(pieces(''.join(blanked), again.strings)))


def main():
    for case in (case_basics, case_php_specifics, case_interpolation,
                 case_other_languages, case_blade, case_failures, case_js_regex_literals,
                 case_r9_regex_context, case_r9_char_literals, case_r9_raw_strings,
                 case_r9_heredoc_interpolation, case_r9_jsx, case_r9_jsx_text_bounds):
        case()
    return finish('structure.native.mask')


if __name__ == '__main__':
    sys.exit(main())
