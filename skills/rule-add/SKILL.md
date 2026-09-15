---
name: rule-add
description: PR 리뷰에서 반복된 지적이나 팀 컨벤션 문서의 항목을 convention-guard 규칙으로 만듭니다. 정규식과 픽스처를 짜고 테스트까지 돌립니다. "이거 규칙으로 만들어줘", "이런 지적 자동화하고 싶어", "컨벤션 규칙 추가", "이 패턴 잡고 싶어", 코드 리뷰에서 같은 말을 또 하게 될 때 사용하세요.
---

# 컨벤션 규칙 만들기

사람이 정규식을 직접 쓰는 것보다, **실제 코드를 보고 만든 뒤 픽스처로 검증하는** 편이
오탐이 훨씬 적습니다. 순서를 지키세요.

## 1. 규칙으로 만들 가치가 있는지부터 판단

다음에 해당하면 **규칙을 만들지 말고** 그 이유를 사용자에게 알려주세요.

- **린터가 잡는 것** (포맷, import 순서, 미사용 변수) → 린터 설정에 넣는 게 맞습니다.
  `presets/` 에 프리셋이 있으면 그걸 권하세요. 굳이 규칙으로도 둘 거라면
  `superseded_by: [pint.json, ...]` 를 붙여 포맷터가 있는 레포에서는 물러나게 하세요.
- **타입 추론이나 호출 그래프가 필요한 것** → phpstan / tsc / golangci-lint 의 몫입니다.
- **의미를 봐야만 판정되는 것** (N+1, 계층 경계) → 정규식 규칙이 아니라
  `semantic` 규칙(6번)으로 만드세요.

## 2. 어디에 둘지, 얼마나 세게 할지 정하기

한 번에 물어보고, 판단이 서면 추천안을 먼저 제시하세요.

- **공통(`rules/`)** vs **이 레포만(`.claude/convention-rules/`)**.
  한 레포에서만 통하는 이야기면 로컬입니다. `local/` 네임스페이스가 자동으로 붙습니다.
- **강도**: `error`(차단) / `warn`(차단 안 함, error 에 편승) / `info`(로그만).
  **검증되지 않은 새 규칙은 `warn` 으로 시작하세요.** 승격은 `rule-tune` 으로 데이터를 보고.

## 3. 트리거 종류 고르기 — 가장 중요한 선택

줄 하나만 봐서 판정되는 규칙은 생각보다 적습니다. **무엇을 봐야 하는지**와
**무엇이 이번 변경의 책임인지**를 함께 정하세요.

| 판정에 필요한 것 | 트리거 | 앵커 |
|---|---|---|
| 줄 하나 | `code_regex` | 줄 자체 |
| 여러 줄에 걸친 패턴 | `file_regex` | 매치 구간이 변경된 줄과 겹칠 때 |
| "A를 추가했으면 파일에 B가 있어야" | `when_line_added` + `must_contain_in_file` | 조건이 새로 추가됐을 때 |
| 새 파일의 필수 선언 | `absent_in_new_file` | 파일이 새것일 때 |
| "A 파일 바꿨으면 B도" | `when_changed` + `require_changed` | 변경 집합 |
| 의미 판단이 필요 | `review_when` + `review_prompt` | 게이트 통과 시 서브에이전트 |

**세 번째를 먼저 고려하세요.** 대부분의 "맥락이 필요한" 규칙이 여기에 들어맞습니다.
조건은 변경된 줄에서 찾고 요구사항은 파일 전체에서 찾으므로, 레거시 파일을 건드려도
조용합니다.

절대 하지 말 것: 파일 전체를 훑는 규칙을 만들려고 `code_regex` 에 광범위한 패턴을 넣는 것.
레거시가 전부 걸려서 일주일이면 규칙이 꺼집니다.

## 4. 실제 코드에서 패턴 확인

`Grep` 으로 레포를 훑어 **위반 사례와 정상 사례를 둘 다** 찾으세요.
정상 사례가 정규식에 걸리지 않는지 확인하는 것이 핵심입니다.

적용 태그는 감지 결과와 맞춰야 합니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
```

## 5. 규칙 파일 작성

```yaml
id: <짧은-케밥-케이스>            # core/ 또는 local/ 네임스페이스는 자동
title: <한 줄 요약>
severity: warn
superseded_by: [pint.json]      # 포맷터가 고쳐주는 항목이면 (선택)
applies_to:
  stack: [laravel]              # ["*"] 는 전 스택
  files: ["app/**/*.php"]
  exclude: ["**/vendor/**"]
  version: ">=10"               # 선택
triggers:
  code_regex: '...'
context_injection: |
  무엇이 문제인지 한 줄, 대신 무엇을 할지 한 줄.
  에이전트가 읽고 바로 고칠 수 있게 구체적으로.
tests:
  should_match:
    - '실제 위반 코드'
  should_not_match:
    - '비슷하지만 정상인 코드'
    - '주석 안에 같은 단어가 있는 경우'
```

`should_not_match` 에는 **정규식이 헷갈릴 만한 정상 코드**를 반드시 넣으세요.
주석, 문자열 리터럴, 이름이 비슷한 다른 API 가 단골 오탐 원인입니다.

픽스처 의미는 트리거마다 다릅니다.

| 트리거 | `should_match` 에 넣을 것 |
|---|---|
| `code_regex` / `file_regex` | 위반 코드 |
| `absent_in_new_file` | 해당 선언이 **없는** 파일 본문 |
| `when_line_added` + `must_contain` | 조건은 있고 요구사항은 **없는** 파일 본문 |
| `when_changed` + `require_changed` | 변경된 경로 **목록** — `["routes/api.php"]` |

## 6. semantic 규칙 (의미 판정)

정규식은 **게이트로만** 씁니다. 판정은 서브에이전트가 합니다.

```yaml
id: laravel-n-plus-one
severity: warn
applies_to:
  stack: [laravel]
  files: ["app/**/*.php"]
triggers:
  review_when: '\bforeach\s*\('     # 판정을 살 만한 턴인지 거르는 게이트
review_prompt: |
  반복문 안에서 관계에 접근해 쿼리가 N번 나가는지 판단하세요.
  이미 eager load 되어 있으면 위반이 아닙니다.
  확실하지 않으면 보고하지 마세요.
```

`review_prompt` 에는 **"확실하지 않으면 보고하지 말라"** 를 반드시 넣으세요.
그리고 게이트를 좁게 잡으세요 — 넓으면 매 턴 LLM 비용이 나갑니다.
`agent` 훅을 켜지 않았다면 semantic 규칙은 로드만 되고 아무 일도 하지 않습니다.

## 7. 컨텍스트에 넣을 규칙인지 판단

대부분의 규칙은 **넣지 않습니다.** 훅이 잡아주므로 컨텍스트에 또 적으면 자리만 차지하고,
목록이 길어질수록 전부 묻힙니다.

`in_context: true` 를 붙일 기준은 하나입니다 — **잡힌 뒤 고치는 비용이 큰가.**

| 넣을 것 | 넣지 말 것 |
|---|---|
| 파일 구조를 바꿔야 고쳐지는 것 (검증 계층 추가, 'use client' 분리) | 한 줄 치환으로 끝나는 것 |
| 마이그레이션처럼 되돌리기 어려운 것 | 포맷터가 고쳐주는 것 |
| `semantic` 규칙 (자동으로 포함됨) | 정규식으로 확실히 잡히는 것 |

넣기로 했다면 `context_line` 을 **명령형 한 줄**로 쓰세요. `context_injection` 은
"~가 없습니다" 처럼 사후 지적문이라 예방용으로는 어색합니다.

```yaml
in_context: true
context_line: 쓰기 액션(store/update/create)은 FormRequest 로 받고 $request->validated() 를 쓰세요.
```

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --stdout   # 확인 후
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py"            # 재생성
```

## 8. 검증 — 건너뛰지 마세요

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_rules.py" --repo "$CLAUDE_PROJECT_DIR"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --rule <새-규칙-id> --no-color
```

두 번째가 진짜 시험입니다. **레포 전체에서 몇 건이 나오는지 보고, 그중 몇 개를 열어
실제 위반인지 확인하세요.** 오탐이 섞여 있으면 정규식을 좁히고 3번으로 돌아갑니다.
전수조사에서 수백 건이 나오면 그건 규칙이 아니라 레거시 신호입니다 —
`exclude` 를 붙이거나 `severity` 를 낮추세요.

## 9. 기존 규칙을 조정하는 경우

새 규칙을 만들지 말고 덮어쓰세요.

- 끄기 / 강도 조정 / 디렉터리 제외 → `.claude/convention-rules/config.yaml`
- 조건 일부만 변경 → `override: core/<id>` 파일 (명시한 키만 병합됩니다)

## 마무리

무엇을 어디에 만들었고, 왜 그 강도이며, 레포 전체에서 몇 건이 걸리는지 세 줄로 보고하세요.
`warn` 으로 시작했다면 2~3주 뒤 `rule-tune` 으로 승격을 검토하자고 덧붙이세요.
