# 규칙

## 목차
- 규칙 레이어
- 파일 형식
- 앵커: 무엇이 이번 변경의 책임인가
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

필드 설명과 검증 규칙 전체는 `skills/rule-add/references/schema.md`, 앵커별 완성 예시는 `skills/rule-add/references/examples.md` 에 있습니다. 두 문서의 예시는 테스트가 실제로 로드해 검증합니다.

```yaml
id: laravel-controller-needs-validation
title: store/update 컨트롤러 액션에 검증 없음
severity: error                     # error | warn | info
applies_to:
  stacks: [laravel]                 # 필수
  files: ["app/Http/Controllers/**/*.php"]
  exclude: ["**/vendor/**"]
detect:
  when_line_added: 'public\s+function\s+(store|update|create)\s*\('
  must_contain_in_file: '(FormRequest|Http\\Requests|->validate\(|->validated\(\)|Validator::make\()'
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

| detect | kind | 이번 변경의 책임 |
|---|---|---|
| `when_line_added` | line | 추가된 줄이 패턴에 맞음 |
| `when_line_added` + `must_contain_in_file` | requires | 조건이 **추가된 줄**에 있고, 필수 요소가 파일 **어디에도** 없음 |
| `when_file_added: true` + `must_contain_in_file` | absent | 파일이 **새것**이고 필수 요소가 없음 |
| `when_changed` + `require_changed` | paired | 변경 집합에 A 는 있고 B 는 없음 |
| `file_regex` | file | 여러 줄 매치 구간이 **변경된 줄과 겹침** (새 파일은 전체) |

`semantic_review` 가 붙은 규칙은 같은 앵커로 후보를 찾고, 판정만 리뷰어에게 넘깁니다: [semantic-review.md](semantic-review.md)

`superseded_by: [pint.json, ...]` 는 그 파일이 레포에 있으면 규칙을 끕니다. 포맷터가 결정적으로 고치는 항목을 정규식으로 중복 지적하지 않기 위해서입니다.

`fix.auto` 가 있는 규칙은 `mode: auto-fix` 와 `scan.py --fix` 에서 후보 줄만 자동 수정됩니다. 탐지 이후 줄이 바뀌었거나 수정해도 규칙에 걸리면 적용하지 않습니다.

## 구조 조건: 매치가 무엇 안에 있는가 (3.0)

앵커가 "이번 변경의 책임"을 정하고, 구조 조건은 그 매치를 **거릅니다**. 정규식만으로는 주석 안의 `dd(` 와 진짜 `dd(` 를 구분할 수 없습니다.

```yaml
detect:
  when_line_added: '\bdd\('
  not_in: [comment, string]     # 주석·문자열 리터럴 안의 매치를 제외
```

| 조건 | 값 | 의미 | 쓸 수 있는 앵커 |
|---|---|---|---|
| `not_in` | `comment`, `string` | 그 구간 안의 매치를 제외 | line / requires / file |
| `in_scope` | `loop`, `function`, `class`, `catch` | 나열한 스코프에 **모두** 속한 매치만 인정 | line / requires / file |
| `block_empty` | `true` | 매치를 감싸는 블록 본문이 공백뿐일 때만 인정 | **file 만** |

- 값 하나는 목록 없이 써도 됩니다: `not_in: comment`
- `block_empty` 가 `file_regex` 전용인 이유는 블록이 중첩되면 "어느 블록"인지 모호해지기 때문입니다
- `block_empty` 에서 **주석은 내용입니다** — 이유를 주석으로 남긴 `catch` 블록은 비어 있지 않습니다
- `when_file_added`(absent)·`when_changed`(paired) 에는 붙일 수 없습니다. 판정할 위치가 없기 때문입니다

지원 언어는 PHP, JavaScript/TypeScript, Go(정밀), Java 계열·Rust·C 계열·Python(이관 수준), Blade(마스킹만)입니다. Blade 는 스코프 트리가 없어 `in_scope`·`block_empty` 를 쓰면 "구조 미확인"이 됩니다.

**파일을 읽지 못하면 후보를 그대로 올립니다.** 문법이 깨졌거나 지원하지 않는 언어여서 구조를 확인할 수 없으면 조건을 적용하지 않고 후보를 남긴 뒤, `systemMessage` 로 어느 파일이었는지 알립니다. 검사하지 못한 것이 "깨끗함"으로 보이지 않게 하기 위해서입니다.

조건을 **추가하거나 바꾸면** 그 규칙의 의미 판정 캐시가 만료됩니다. 후보를 고르는 기준이 달라졌으므로 저장된 판정은 다른 질문에 대한 답입니다.

### 픽스처와 구조 조건

`tests.match`/`no_match` 는 파일이 아니라 조각이라, PHP 조각에는 `<?php` 가 없습니다. 픽스처 실행기가 언어별 접두를 자동으로 붙입니다. 태그 밖 동작 자체를 검증하려면 끕니다.

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
| `tests/integration/test_parity.py` | 픽스처 레포 4개에서 (규칙, 파일, 줄) 결과 고정 |

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
| security | 항상 | 하드코딩 시크릿, NEXT_PUBLIC 시크릿, 검증 없는 `$request->all()` |
| php | php | 디버그 출력, 빈 catch |
| psr12 | php | PSR-12 스타일 12개 (포맷터가 있으면 9개가 물러남) |
| laravel | laravel | 검증·마이그레이션·Blade 쿼리·env·라우트 테스트·N+1 |
| js | js, ts | console, 빈 catch, any |
| react | react | 인덱스 key |
| next | next, next-app | 'use client', img, 공개 시크릿 |
| nest | nest | Req/Res 직접 사용, 컨트롤러의 레포지토리 주입 |
| go | go | 무시한 에러, panic, context 위치, %w |
| architecture | 명시 | 계층 경계(의미 판정), 컨트롤러 레포지토리 주입 |
| performance | 명시 | N+1(의미 판정) |

규칙은 여러 프리셋에 속할 수 있습니다. 모든 core 규칙은 최소 하나의 프리셋에 속해야 합니다(테스트가 강제).

## 번들 규칙 목록

```bash
python3 scripts/detect_stack.py --cwd <레포>
```

적용 중인 규칙(●)과 적용되지 않는 규칙(○)을 사유(프리셋 비활성, 스택 불일치, superseded, config disable)와 함께 보여줍니다.
