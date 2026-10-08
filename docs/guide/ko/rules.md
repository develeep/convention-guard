# 규칙

[README](../../../README.md) · **한국어** · [English](../en/rules.md)

## 목차
- 규칙 레이어
- 파일 형식
- 앵커: 무엇이 이번 변경의 책임인가
- 구조 조건: 매치가 무엇 안에 있는가
- 픽스처와 시나리오 테스트
- 오버라이드
- 프리셋
- 번들 규칙 목록

## 규칙 레이어

| 레이어 | 위치 | id |
|---|---|---|
| core | 플러그인 `rules/**` | `core/<id>` |
| user | `~/.claude/convention-guard/rules/` | `user/<id>` |
| local | `<repo>/.claude/convention-guard/rules/` | `local/<id>` |

뒤 레이어가 앞 레이어를 덮습니다. 로컬·개인 규칙은 프리셋과 무관하게 항상 로드되고, core 규칙은 활성 프리셋에 속할 때만 로드됩니다.

## 파일 형식

규칙 파일은 내장 YAML 파서(`miniyaml`)로 읽습니다. PyYAML 이 있어도 쓰지 않으므로 기기마다 다르게 읽히는 일이 없습니다. 대신 여러 줄에 걸친 흐름 목록(`[a,\n b]`)은 읽지 못하니 블록 목록(`- a`)으로 쓰세요.

필드 설명과 검증 규칙 전체는 `skills/rule-add/references/schema.md`, 앵커별 완성 예시는 `skills/rule-add/references/examples.md` 에 있습니다. 두 문서의 예시는 테스트가 실제로 로드해 검증합니다.

```yaml
id: laravel-controller-needs-validation
title: store/update 컨트롤러 액션에 검증 없음
severity: error                     # error | warn | info
applies_to:
  stacks: [laravel]                 # 필수
  files: ["app/Http/Controllers/**/*.php"]
  exclude: ["**/vendor/**"]
  # include_generated: true         # 선택. 설정 generated 기본 목록(테스트·빌드 산출물 등)에 든 경로도 읽음
detect:
  when_line_added: 'public\s+function\s+(store|update|create)\s*\('
  must_contain_in_file: '(FormRequest|Http\\Requests|->validate\(|->validated\(\)|Validator::make\()'
  must_not_in: [comment, string]    # 주석·문자열 안의 필수 요소는 없는 것으로 봄
message: |
  쓰기 액션을 추가했는데 이 파일 어디에도 검증이 없습니다.
  FormRequest 를 만들어 타입힌트로 받고 $request->validated() 를 쓰세요.
prevent: 쓰기 액션(store/update/create)은 FormRequest 로 받고 $request->validated() 를 쓰세요.
tests:
  match: ["..."]
  no_match: ["..."]
```

| 강도 | 동작 |
|---|---|
| error | 차단 (mode: fix / auto-fix) |
| warn | 혼자서는 차단하지 않고, error 로 차단할 때 함께 전달 |
| info | 기록만 |

## 앵커: 무엇이 이번 변경의 책임인가

규칙이 레거시 코드에 반응하면 도입 2주 만에 꺼집니다. 그래서 앵커마다 "이번 변경"의 정의가 다릅니다.

"추가된 줄"은 진입점마다 다르게 정해집니다.

- **훅**: 편집 사건 원장이 기록한 **에이전트가 쓴 줄**입니다 ([architecture.md](../../architecture.md#편집-사건-원장)). 사람이 쓴 줄, 원래 있던 줄, 남의 커밋이 들여온 줄은 들지 않습니다. 같은 도구 호출에서 지웠다가 다시 쓴 줄(줄 이동, `mv`)은 쓴 줄이 아니고, 옮겨 온 파일은 새 파일이 아닙니다. 커밋해도 출처는 그대로입니다.
- **CLI**(`scan.py`): `git diff --diff-algorithm=histogram` 기준입니다. 사용자의 `diff.algorithm` 설정과 관계없이 같은 변경은 같은 줄로 읽습니다. `git mv`(유사도 70% 이상)는 바뀐 줄만, 내용 그대로의 `mv` 는 아무 줄도 추가하지 않습니다.

| detect | kind | 이번 변경의 책임 |
|---|---|---|
| `when_line_added` | line | 추가된 줄이 패턴에 맞음 |
| `when_line_added` + `must_contain_in_file` | requires | 조건이 **추가된 줄**에 있고, 필수 요소가 파일 **어디에도** 없음 |
| `when_file_added: true` + `must_contain_in_file` | absent | 파일이 **새것**이고 필수 요소가 없음 |
| `when_changed` + `require_changed` | paired | 변경 집합에 A 는 있고 B 는 없음 (줄만 지운 파일도 변경 집합에 듭니다) |
| `file_regex` | file | 여러 줄 매치 구간(앞뒤 공백 제외)이 **변경된 줄과 겹치거나 그 안에서 줄이 지워짐** (새 파일은 전체) |
| `when_code_added: true` (+ `semantic_review`, `applies_to.files` 필수) | unit | 글롭에 든 파일에 **글자가 있는 줄**을 추가함. 그 줄이 속한 함수, 또는 함수 밖 줄을 모은 파일 머리가 판정 단위 |

필수 요소(`must_contain_in_file`)는 **주석 안에 있으면 없는 것**으로 봅니다. `// TODO: FormRequest 로 교체` 는 검증이 아닙니다. 문자열 안의 매치는 기본으로 셉니다(`'use client'` 는 그 자체가 문자열입니다). 바꾸려면 `must_not_in` 을 씁니다. 쓰면 기본값 `[comment]` 를 대체합니다.

- `must_not_in: [comment, string]` — 문자열 안의 매치도 셈에서 뺍니다
- `must_not_in: []` — 원문 그대로 셉니다(주석으로 된 라이선스 헤더를 요구하는 규칙)
- 구조를 읽지 못한 파일은 원문 매치로 판단하고 "구조 미확인"으로 알립니다. 분석은 원문에 필수 요소가 보이는 파일에서만 돕니다
- 파일 맨 앞의 UTF-8 BOM 은 읽을 때 벗깁니다. 그래서 `^\s*'use client'` 같은 첫 줄 패턴이 BOM 파일에서도 맞습니다

`semantic_review` 가 붙은 규칙은 같은 앵커로 후보를 찾고, 판정만 리뷰어에게 넘깁니다. 정규식 신호가 없는 컨벤션(컨트롤러에 비즈니스 로직 금지 등)은 `when_code_added` 로 파일 글롭만 정하고 판정을 리뷰어에게 맡깁니다: [semantic-review.md](semantic-review.md#파일-글롭-상시-판정)

`superseded_by: [pint.json, ...]` 는 그 파일이 레포에 있으면 규칙을 끕니다. 포맷터가 결정적으로 고치는 항목을 정규식으로 중복 지적하지 않기 위해서입니다.

`fix.auto` 가 있는 규칙은 `mode: auto-fix` 와 `scan.py --fix` 에서 후보 줄만 자동 수정됩니다. 탐지 이후 줄이 바뀌었거나 수정해도 규칙에 걸리면 적용하지 않습니다. UTF-8 로 읽히지 않는 파일은 고치지 않고, 고친 줄 말고는 줄바꿈(LF·CRLF 섞임 포함)까지 바이트 그대로 둡니다.

## 구조 조건: 매치가 무엇 안에 있는가

앵커가 "이번 변경의 책임"을 정하고, 구조 조건은 그 매치를 **거릅니다**. 정규식만으로는 주석 안의 `dd(` 와 진짜 `dd(` 를 구분할 수 없습니다. 구조는 tree-sitter 구문 트리로 판정합니다 (플러그인이 스스로 설치하는 구조 엔진 — [architecture.md](../../architecture.md#구조-엔진)).

```yaml
detect:
  when_line_added: '\bdd\('
  not_in: [comment, string]     # 주석·문자열 리터럴 안의 매치를 제외
```

| 조건 | 값 | 의미 | 쓸 수 있는 앵커 |
|---|---|---|---|
| `not_in` | `comment`, `string` | 그 구간 안의 매치를 제외 | line / requires / file |
| `in_scope` | `loop`, `function`, `class`, `catch` | 나열한 범위의 **본문**에 **모두** 속한 매치만 인정 | line / requires / file |
| `block_empty` | `true` | 매치를 감싸는 블록 본문이 공백뿐일 때만 인정 | **file 만** |

- 값 하나는 목록 없이 써도 됩니다: `not_in: comment`
- 정규식이 먼저 돕니다. 구조 조건이 있는 규칙의 매치가 있는 파일만 파싱하고, 매치가 없으면 엔진은 임포트조차 하지 않습니다
- line·requires 앵커는 줄의 **모든** 매치를 봅니다. 하나라도 조건을 통과하면 그 줄이 후보입니다. 그래서 `$label = "dd("; dd($user);` 는 앞의 문자열 매치가 걸러져도 뒤의 호출로 걸립니다
- `string` 은 리터럴 **텍스트**입니다: 문자열, 템플릿 리터럴, 정규식 리터럴, heredoc/nowdoc, JSX 텍스트와 속성 값, PHP 의 `?>` 뒤 HTML, Blade 의 템플릿 텍스트. 그 안의 코드 — 템플릿의 `${...}`, f-string 의 `{...}`, PHP 의 `"{$a->b()}"`·`$x`, heredoc 보간, JSX 의 `{...}` — 는 코드입니다
- `comment` 는 `//`, `/* */`, `#`(PHP·Python), Blade `{{-- --}}` 입니다. PHP 의 `#[` 는 속성이고 주석이 아닙니다. PHP 의 `//` 주석은 `?>` 에서 끝납니다
- `in_scope` 는 블록 **본문**만 안으로 봅니다. `for (const x of await load()) {` 의 `await load()` 는 loop 밖입니다. 그래서 트리거가 헤더 줄 자체인 규칙(`foreach (` 를 찾는 규칙)에 `in_scope: loop` 를 붙이면 아무것도 걸리지 않습니다
- `loop` 에는 반복 메서드에 넘긴 콜백 본문도 들어갑니다(`xs.map(x => ...)`, `$users->each(function ...)`, `array_map(fn ...)`, `map(lambda ...)`). 반복 메서드인지는 이름 목록으로 판정합니다(`structure/nodes.py`). 반복 메서드의 콜백은 loop 이면서 function 입니다. Python 컴프리헨션도 loop 입니다
- `function` 에는 메서드, 클로저, 화살표 함수(중괄호 없는 것 포함), PHP `fn`, Python `lambda` 본문이 들어갑니다
- `block_empty` 가 `file_regex` 전용인 이유는 블록이 중첩되면 "어느 블록"인지 모호해지기 때문입니다. 매치가 아니라 **판정하는 블록 전체**를 변경 창으로 보므로, 레거시 catch 의 본문을 지우거나 빈 줄로 바꾸면 이번 변경의 책임입니다. **주석은 내용입니다** — 이유를 주석으로 남긴 `catch` 블록은 비어 있지 않습니다
- `when_file_added`(absent)·`when_changed`(paired) 에는 붙일 수 없습니다. 판정할 위치가 없기 때문입니다

지원 언어는 JavaScript(JSX), TypeScript, TSX, PHP, Blade, Python 입니다. Blade 는 지시문 블록(`@foreach…@endforeach` 등)이 범위가 되고, 그 안의 PHP 는 PHP 로 읽습니다.

**읽지 못한 것은 통과가 아닙니다.** 다음 경우 조건을 적용하지 않고 후보를 남긴 뒤 `systemMessage` 로 어느 파일이었는지 알립니다.

- 구조 엔진이 없음 — "구조 엔진 없음 (설치 전 / 설치 중 / 설치 실패 / 불러오기 실패 / 미지원 플랫폼 / 꺼짐)". CI 에서는 `scripts/engine.py ensure` 로 먼저 설치하고, `scan.py --require-engine` 으로 확인 없이 지나가는 것을 막을 수 있습니다
- 파일에 파서가 읽지 못한 곳이 있음 — 첫 읽기 오류 지점부터 뒤의 매치는 "구조 미확인"(닫히지 않은 따옴표는 뒤 전체를 바꿉니다). 앞은 정상 판정합니다
- 지원하지 않는 언어(예: `.yaml` 에 걸린 `not_in: [comment]`)

조건을 **추가하거나 바꾸면** 그 규칙의 의미 판정 캐시가 만료됩니다. 후보를 고르는 기준이 달라졌으므로 저장된 판정은 다른 질문에 대한 답입니다.

### 픽스처와 구조 조건

구조 조건이 있는 규칙의 `tests.match`/`no_match` 는 **파서가 읽을 수 있는 완결된 코드**여야 합니다. `} catch (e) {` 처럼 짝이 없는 조각은 읽기 오류가 되어 판정되지 않습니다 — `try { … } catch (e) { … }` 로, 메서드는 클래스 안에 씁니다. PHP 조각에는 `<?php` 가 자동으로 붙습니다(조각이 `<?` 로 시작하면 붙이지 않음). 태그 밖 동작 자체를 검증하려면 끕니다.

```yaml
tests:
  lang_prefix: false
  match: ["<p>It's</p>"]
```

## 픽스처와 시나리오 테스트

| 테스트 | 검증하는 것 |
|---|---|
| `tests/rules/test_rule_fixtures.py` | 모든 규칙의 `tests.match`/`no_match`, 자동 수정이 위반을 해소하는지, 프리셋 소속, id↔파일명 |
| `tests/rules/test_rule_scenarios.py` | 실제 git 변경으로 앵커 동작: 새 코드는 걸리고 **손대지 않은 레거시는 조용함** |
| `tests/integration/test_parity.py` | 픽스처 레포 3개에서 (규칙, 파일, 줄) 결과 고정 |

`when_line_added` 단독이 아닌 규칙은 레거시 무반응 시나리오가 필수입니다(테스트가 강제).

레포 로컬 규칙은 `python3 tests/rules/test_rule_fixtures.py --repo <레포>` 로 검사합니다. 오버라이드는 원본에 병합된 상태로 검사됩니다.

## 오버라이드

```yaml
# <repo>/.claude/convention-guard/rules/override-blade-query.yaml
override: core/laravel-no-query-in-blade
severity: warn
applies_to:
  exclude: ["resources/views/admin/**"]
```

원본 규칙의 원시 YAML 에 깊은 병합한 뒤 검증합니다. 매핑은 병합되고 **목록은 교체**됩니다. 단순히 끄기·강도 조정·경로 제외라면 오버라이드보다 레포 `config.yaml` 의 `disable`/`severity`/`exclude` 가 간단합니다.

## 프리셋

`presets/*.yaml` 은 core 규칙 묶음입니다.

```yaml
name: laravel
description: "Laravel 컨트롤러·마이그레이션·Blade·설정 규칙"
stacks: [laravel]        # 이 태그가 감지되면 presets: auto 에서 켜짐. 비어 있으면 명시해야 켜짐
rules:
  - core/laravel-*       # 규칙 id 글롭
```

| 프리셋 | auto 조건 | 내용 |
|---|---|---|
| common | 항상 | 담당자 없는 TODO |
| security | 항상 | 하드코딩 시크릿, 검증 없는 `$request->all()` |
| php | php | 디버그 출력, 빈 catch |
| psr12 | php | PSR-12 스타일 12개 (포맷터가 있으면 9개가 물러남) |
| laravel | laravel | 검증·마이그레이션·Blade 쿼리·env·라우트 테스트·N+1 |
| js | js, ts | console, 빈 catch, any |
| react | react | 인덱스 key |
| next | next, next-app | 'use client', img |
| nest | nest | Req/Res 직접 사용, 컨트롤러의 레포지토리 주입 |
| python | python | 디버그 출력(print·breakpoint·pdb), 맨 except |
| architecture | 명시 | 계층 경계(의미 판정), 컨트롤러 레포지토리 주입 |
| performance | 명시 | N+1(의미 판정) |
| layering | 명시 | 컨트롤러에 비즈니스 로직, 도메인 계층의 I/O 의존 (파일 글롭 상시 판정) |

규칙은 여러 프리셋에 속할 수 있습니다. 모든 core 규칙은 최소 하나의 프리셋에 속해야 합니다(테스트가 강제).

## 번들 규칙 목록

```bash
python3 scripts/detect_stack.py --cwd <레포>
```

적용 중인 규칙(`✔ on`)과 적용되지 않는 규칙(`○ off`)을 사유(프리셋 비활성, 스택 불일치, superseded, config disable)와 함께 보여줍니다.
