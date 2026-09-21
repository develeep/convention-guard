---
name: rule-add
description: 반복되는 리뷰 지적이나 팀 컨벤션 항목을 convention-guard 규칙으로 만듭니다. 규칙으로 만들 가치를 먼저 판단하고, 변경 앵커를 고르고, 실제 코드에서 정상·위반 사례를 찾아 정규식과 픽스처를 짠 뒤, 픽스처·시나리오·레포 전수조사로 오탐을 검증합니다. 정규식으로 판정할 수 없는 규칙은 의미 판정(semantic_review) 규칙으로 만듭니다. "이거 규칙으로 만들어줘", "이 패턴 잡고 싶어", "컨벤션 규칙 추가", convention-discover 가 넘긴 후보를 등록할 때 사용합니다.
---

# 규칙 만들기

사람이 정규식부터 쓰는 것보다 **실제 코드를 보고 만든 뒤 픽스처로 검증하는** 편이 오탐이 훨씬 적습니다.

## 체크리스트

```
- [ ] 1. 규칙으로 만들 가치 판단
- [ ] 2. 위치와 강도 정하기
- [ ] 3. 앵커 고르기
- [ ] 4. 실제 코드에서 위반·정상 사례 찾기
- [ ] 5. 규칙 파일 작성
- [ ] 6. 검증 루프 (픽스처 → 전수조사 → 좁히기)
- [ ] 7. 예방 컨텍스트 여부 결정
- [ ] 8. 보고
```

### 1. 규칙으로 만들 가치 판단

다음이면 규칙을 만들지 말고 이유를 알립니다.

| 대상 | 맡길 곳 |
|---|---|
| 포맷, import 순서, 미사용 변수 | 린터·포맷터 설정 (`examples/formatters/`) |
| 타입 추론, 호출 그래프 | phpstan / tsc / golangci-lint |
| 코드에 흔적이 남지 않는 것 (커밋 메시지, 설계 합의) | 문서 |

### 2. 위치와 강도

- 이 레포에만 해당 → `<repo>/.claude/convention-guard/rules/<id>.yaml` (`local/` 네임스페이스 자동)
- 여러 레포 공통 → 플러그인 `rules/<언어>/<묶음>/<id>.yaml` + `presets/*.yaml` 에 id 추가
- 기존 core 규칙을 바꾸는 것 → 새로 만들지 말고 `override: core/<id>` 파일 (바꿀 키만)
- 강도: **새 규칙은 `warn` 으로 시작**합니다. 승격은 rule-tune 에서 데이터를 보고 합니다.

### 3. 앵커 고르기 — 가장 중요한 선택

앵커는 무엇이 **이번 변경의 책임**인지 정합니다. 잘못 고르면 레거시 코드가 전부 걸립니다.

| 판정에 필요한 것 | detect |
|---|---|
| 추가된 줄 하나 | `when_line_added` |
| "A 를 추가했으면 파일에 B 가 있어야" | `when_line_added` + `must_contain_in_file` |
| 새 파일의 필수 선언 | `when_file_added: true` + `must_contain_in_file` |
| "A 파일을 바꿨으면 B 도" | `when_changed` + `require_changed` |
| 여러 줄에 걸친 패턴 | `file_regex` (매치가 변경된 줄과 겹칠 때만) |
| 의미를 봐야 판정 | 위 중 하나를 게이트로 + `semantic_review` |

필드 전체·픽스처 의미·의미 판정 컨텍스트: [references/schema.md](references/schema.md)

### 4. 실제 코드에서 사례 찾기

`Grep` 으로 레포에서 위반 사례와 **정상 사례를 둘 다** 찾습니다. 정상 코드가 걸리지 않게 만드는 것이 핵심입니다. 주석, 문자열 리터럴, 이름이 비슷한 다른 API 가 단골 오탐 원인입니다.

### 5. 규칙 파일 작성

앵커별 완성 예시를 보고 가장 가까운 것에서 시작합니다: [references/examples.md](references/examples.md)

반드시 채울 것: `applies_to.stacks` (전 스택이면 `["*"]`), `tests.match`, `tests.no_match` (4단계의 헷갈리는 정상 코드), `message` (무엇이 문제인지 한 줄 + 대신 무엇을 할지 한 줄).

### 6. 검증 루프

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tests/rules/test_rule_fixtures.py" --repo .
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --rule <id> --no-lint --fail-on never --no-color
```

1. 픽스처가 실패하면 메시지대로 고치고 다시 실행합니다.
2. 전수조사 결과에서 **서너 곳을 `Read` 로 열어** 실제 위반인지 확인합니다.
3. 정상 코드가 걸렸으면 그 코드를 `no_match` 에 추가하고 정규식을 좁힌 뒤 1로 돌아갑니다.
4. 수백 건이 나오면 규칙이 아니라 레거시 신호입니다. 파일 경로(`applies_to.exclude`)로 좁히거나 강도를 낮춥니다.

플러그인 규칙이라면 앵커가 `when_line_added` 단독이 아닐 때 `tests/rules/scenarios/` 에 git 시나리오(새 코드는 걸림 / 손대지 않은 레거시는 조용함)도 추가하고 `python3 "${CLAUDE_PLUGIN_ROOT}/tests/run_all.py"` 를 돌립니다.

### 7. 예방 컨텍스트 여부

대부분의 규칙은 훅이 잡으므로 컨텍스트에 넣지 않습니다. **잡힌 뒤 되돌리는 비용이 클 때만** `prevent:` 한 줄(명령형)을 붙이고 재생성합니다.

| prevent 를 붙임 | 붙이지 않음 |
|---|---|
| 파일 구조를 바꿔야 고쳐지는 것 (검증 계층, 'use client' 분리) | 한 줄 치환으로 끝나는 것 |
| 되돌리기 어려운 것 (마이그레이션) | 포맷터가 고치는 것 |

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" emit --stdout
```

### 8. 보고

```
규칙: local/no-direct-slack-call (warn) — .claude/convention-guard/rules/no-direct-slack-call.yaml
앵커: when_line_added — 새로 추가한 호출만 걸림, 기존 호출은 조용함
검증: 픽스처 4개 통과 · 전수조사 7건 중 확인한 4건 모두 실제 위반
다음: 2~3주 뒤 rule-tune 으로 error 승격 검토
```
