#!/usr/bin/env python3
"""What `migrate.judge()` decides for one 1.x rule, branch by branch.

The tool rewrites rules people wrote by hand, so every "yes" it gives has to
be justified by something it can actually see. It reads the regex as text and
never interprets it: a rule that hunts for comments keeps its comments (TR-03),
a rule that quotes a string keeps its strings (TR-04), and anything it cannot
reason about is reported instead of edited (MR-01).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import check, finish  # noqa: E402
from lib import migrate, rules as rulelib  # noqa: E402
from lib import miniyaml  # noqa: E402

BODY = """
id: %(id)s
title: t
severity: warn
applies_to:
  stacks: [%(stack)s]
  files: ["%(glob)s"]
detect:
%(detect)s
message: m
tests:
%(tests)s
"""

MATCH_ONE = "  match:\n    - 'sleep(1);'\n"


def rule(detect, glob='app/**/*.php', stack='php', tests=MATCH_ONE, rid='r'):
    text = BODY % {'id': rid, 'stack': stack, 'glob': glob,
                   'detect': detect, 'tests': tests}
    return rulelib.normalize(miniyaml.load(text), 'local/%s.yaml' % rid, 'local')


def verdict(*args, **kwargs):
    return migrate.judge(rule(*args, **kwargs))


def main():
    # -------------------------------------------------- anchors that cannot hold a condition
    v = verdict("  when_changed: ['app/**/*.php']\n  require_changed: ['tests/**']\n",
                tests="  match:\n    - ['app/A.php']\n")
    check('paired 앵커는 anchor_rejects', v.blocked == 'anchor_rejects', v.blocked)

    v = verdict("  when_file_added: true\n  must_contain_in_file: 'declare'\n")
    check('absent 앵커는 anchor_rejects', v.blocked == 'anchor_rejects', v.blocked)

    # -------------------------------------------------- already decided by a human
    v = verdict("  when_line_added: 'sleep\\s*\\('\n  not_in: [comment]\n")
    check('이미 조건이 있으면 건드리지 않는다', v.blocked is None and v.conditions == {},
          (v.blocked, v.conditions))

    # -------------------------------------------------- nothing to verify against
    v = verdict("  when_line_added: 'sleep\\s*\\('\n",
                tests="  no_match:\n    - 'x'\n")
    check('tests.match 가 없으면 no_fixture', v.blocked == 'no_fixture', v.blocked)

    # -------------------------------------------------- a language the layer cannot read
    v = verdict("  when_line_added: 'sleep\\s*\\('\n", glob='**/*.rb', stack='php')
    check('구조 분석이 없는 언어는 no_structure', v.blocked == 'no_structure', v.blocked)

    # -------------------------------------------------- blade: no block tree, but masking works
    v = verdict("  when_line_added: 'dd\\s*\\('\n", glob='resources/**/*.blade.php',
                tests=MATCH_ONE + "  lang: blade\n")
    check('blade 는 변환 대상이다 (scope 가 없어도 not_in 은 동작)',
          v.blocked is None and v.conditions.get('not_in') == ['comment', 'string'],
          (v.blocked, v.conditions))

    # -------------------------------------------------- the rule looks for comments itself
    v = verdict("  when_line_added: '//\\s*TODO'\n")
    check('정규식에 주석 토큰이 있으면 comment 를 넣지 않는다',
          v.conditions.get('not_in') == ['string'], v.conditions)

    # -------------------------------------------------- the rule looks inside strings
    v = verdict('  when_line_added: \'password\\s*=\\s*"\'\n')
    check('정규식에 따옴표가 있으면 string 을 넣지 않는다',
          v.conditions.get('not_in') == ['comment'], v.conditions)

    # -------------------------------------------------- both: nothing safe is left
    v = verdict('  when_line_added: \'//.*"\'\n')
    check('둘 다 있으면 would_break', v.blocked == 'would_break', v.blocked)

    # -------------------------------------------------- the ordinary case
    v = verdict("  when_line_added: 'sleep\\s*\\('\n")
    check('평범한 규칙에는 not_in: [comment, string]',
          v.blocked is None and v.conditions == {'not_in': ['comment', 'string']},
          (v.blocked, v.conditions))
    check('판정에 근거가 붙는다', bool(v.reasons), v.reasons)

    _text_cases()
    _validate_cases()
    return finish('migrate 판정 · 텍스트 생성 · 검증')


RAW = """# 팀이 직접 쓴 규칙
id: no-sleep
title: sleep 금지
severity: error
applies_to:
  stacks: [php]
  files: ["app/**/*.php"]
detect:
  # 왜 이 정규식인지에 대한 메모
  when_line_added: 'sleep\\s*\\('
message: |
  sleep 대신 큐를 쓰세요.
tests:
  match:
    - 'sleep(1);'
"""


def _text_cases():
    rule = rulelib.normalize(miniyaml.load(RAW), 'local/no-sleep.yaml', 'local')
    out = migrate.build_text(RAW, migrate.judge(rule))

    check('사용자 주석이 살아남는다',
          '# 팀이 직접 쓴 규칙' in out and '# 왜 이 정규식인지에 대한 메모' in out, out)
    check('정규식은 한 글자도 바뀌지 않는다', "when_line_added: 'sleep\\s*\\('" in out, out)
    check('조건이 detect 안에 들어간다',
          'not_in: [comment, string]' in out, out)

    lines = out.split('\n')
    added = [i for i, ln in enumerate(lines) if 'not_in:' in ln][0]
    anchor = [i for i, ln in enumerate(lines) if 'when_line_added:' in ln][0]
    check('조건은 detect 의 마지막 자식 뒤에 온다', added > anchor, out)
    check('형제 키와 들여쓰기가 같다',
          len(lines[added]) - len(lines[added].lstrip()) ==
          len(lines[anchor]) - len(lines[anchor].lstrip()), out)
    check('어디서 왔는지 한 줄 남긴다', 'migrate' in lines[added - 1], lines[added - 1])
    check('바뀐 규칙이 다시 읽힌다',
          rulelib.normalize(miniyaml.load(out), 'local/no-sleep.yaml',
                            'local')['detect']['not_in'] == ['comment', 'string'], out)
    check('tests 블록은 그대로',
          out.count("- 'sleep(1);'") == 1, out)




# `no_match` that the condition must keep quiet, and one it must still catch.
GUARDED = RAW + "  no_match:\n    - 'queue()->later(1);'\n"


def _validate_cases():
    rule = rulelib.normalize(miniyaml.load(GUARDED), 'local/no-sleep.yaml', 'local')
    verdict = migrate.judge(rule)
    good = migrate.build_text(GUARDED, verdict)
    check('정상 변환에는 problems 가 없다', migrate.validate(rule, good) == [],
          migrate.validate(rule, good))

    # a condition that swallows the rule's own match fixture
    broken = GUARDED.replace("  when_line_added: 'sleep\\s*\\('",
                             "  when_line_added: 'sleep\\s*\\('\n  in_scope: [class]")
    problems = migrate.validate(rule, broken)
    check('match 픽스처가 빠지면 problems',
          any('match' in p for p in problems), problems)

    # a rewrite that starts catching what it used to leave alone
    widened = GUARDED.replace("'sleep\\s*\\('", "'sleep\\s*\\(|queue'")
    problems = migrate.validate(rule, widened)
    check('no_match 픽스처가 걸리면 problems',
          any('no_match' in p for p in problems), problems)

    # the generated false-positive fixture: the same sample, commented out
    grown, problems = migrate.grow_fixture(good, rule, verdict)
    check('생성한 픽스처가 no_match 에 들어간다',
          grown is not None and '// sleep(1);' in grown, grown)
    check('생성 뒤에도 검증이 통과한다', problems == [], problems)

    blocked = migrate.Verdict('r', blocked='no_fixture')
    check('넣을 조건이 없으면 텍스트를 건드리지 않는다',
          migrate.build_text(GUARDED, blocked) == GUARDED)

    # MR-11: if the condition does not actually filter, the whole thing is off
    inert = rulelib.normalize(miniyaml.load(GUARDED.replace('app/**/*.php', '**/*.rb')),
                              'local/no-sleep.yaml', 'local')
    check('조건이 무력한 규칙은 애초에 판정에서 걸린다',
          migrate.judge(inert).blocked == 'no_structure', migrate.judge(inert).blocked)


if __name__ == '__main__':
    sys.exit(main())
