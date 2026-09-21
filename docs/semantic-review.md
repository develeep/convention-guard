# 의미 판정 (Semantic Review)

## 목차
- 왜 필요한가
- 왜 전부 맡기지 않는가
- 흐름
- 최소 충분 컨텍스트
- 판정 캐시와 중복 방지
- 검증 사이클과의 관계
- 규칙 작성
- 비용과 한계

## 왜 필요한가

N+1 쿼리, 계층 경계, "A 가 있으면 B 가 필요"가 함수 흐름에 달린 경우처럼 **코드 모양이 아니라 의미**를 봐야 판정되는 컨벤션이 있습니다. 정규식은 이런 코드를 후보로 좁힐 수는 있어도 판정은 못 합니다.

```php
$orders = Order::query()->with('items')->get();   // 이 줄이 있으면 VALID
foreach ($orders as $order) {
    $order->items->count();                        // 정규식은 둘을 구분 못 함
}
```

## 왜 전부 맡기지 않는가

| 문제 | 내용 |
|---|---|
| 비용 | Stop 은 매 턴 발생합니다. 무조건 판정하면 턴마다 LLM 호출 |
| 지연 | 도구를 쓰는 판정은 수십 초 |
| 비결정성 | 같은 코드에 다른 판정 |
| 수렴 실패 | 고칠 때마다 새 지적 — 검증 루프가 끝나지 않음 |

그래서 **결정론 게이트를 통과한 후보만**, **판정 기록이 없는 코드만**, **함수 하나 분량의 컨텍스트로** 판정합니다.

## 흐름

```
Stop
 └ semantic_review 규칙의 detect 로 후보 탐지     후보 0건 → 끝 (AI 호출 없음)
    └ 후보마다 컨텍스트 팩 + context_hash / related_hash
       └ 판정 캐시 조회 (rule:file:review_hash)
          ├ VALID / FALSE_POSITIVE → 제외
          ├ VIOLATION              → 결정론 지적처럼 차단 메시지에 포함
          └ 없음                   → 배치 파일 작성
             └ 차단 메시지: "convention-guard:convention-reviewer 에이전트에게
                            python3 .../review.py show <배치> 를 전달하세요"
                └ 메인 에이전트가 서브에이전트 호출
                   └ 리뷰어: show → 판정 → review.py record → 위반만 한 줄씩 응답
                      └ 메인 에이전트: VIOLATION 만 수정 → Stop → 검증
```

메인 에이전트의 컨텍스트에 들어가는 것은 명령 한 줄과 리뷰어의 짧은 응답뿐입니다. 컨텍스트 팩과 리뷰어가 읽은 코드는 서브에이전트 안에서 끝납니다.

설정: `semantic_review.enabled: true` (레포 config 또는 userConfig). 의미 판정 규칙이 있는 프리셋(`architecture`, `performance`, 또는 `laravel` 의 N+1)이 활성이어야 합니다.

## 최소 충분 컨텍스트

규칙이 필요한 조각을 고르고, 조각마다 줄 예산이 있습니다.

| 조각 | 내용 | 상한 |
|---|---|---|
| `current_function` | 후보를 감싸는 이름 있는 함수·메서드. 길면 머리·후보 주변·꼬리만 | 80줄 |
| `snippet` | 후보 ±5줄 (함수를 못 찾으면 ±30줄로 대체) | |
| `imports` | 파일 상단 import/use/require | 30줄 |
| `changed_hunks` | 같은 파일에서 이번 변경이 추가한 다른 줄 | 20줄 |
| `related_files` | 함수 안의 심볼(예: `Order::query`)로 찾은 파일의 앞부분 | 파일당 60줄, 최대 2개 |

- 규칙별 상한 `semantic_review.max_context_lines`, 배치 전체 상한 `semantic_review.context_budget_lines`
- 한 배치의 후보 수 상한 `semantic_review.max_candidates`. 넘치는 후보는 다음 판정으로 미룹니다
- 잘린 곳에는 `… N줄 생략 — 필요하면 Read` 가 붙습니다. 리뷰어는 판정에 꼭 필요할 때만, 후보당 최대 3번 더 읽습니다

함수 경계는 언어별 휴리스틱입니다: 중괄호 언어(php, js/ts, go, java/kotlin, rust, c)는 시그니처를 찾아 괄호 짝을 맞추고, Python 은 들여쓰기로 찾습니다. `for (...) {` 같은 제어문은 함수로 보지 않습니다.

## 판정 캐시와 중복 방지

캐시 키는 `rule:file:review_hash` 이고, `review_hash` 는 **그 판정이 의존한 것 전부**를 하나로 접은 지문입니다.

| 조각 | 내용 | 바뀌면 |
|---|---|---|
| `definition_hash` | 규칙의 `detect` 게이트 + `semantic_review` (instruction, context, max_context_lines) | 질문 자체가 달라졌으므로 재판정 |
| `context_hash` | 주 영역 — 감싸는 함수 본문 (없으면 후보 주변 창) | 판정 대상 코드가 달라졌으므로 재판정 |
| `related_hash` | 팩에 실린 관련 파일과 import 구역 | 판정 근거가 달라졌으므로 재판정 |

규칙의 `title`·`severity`·`message` 는 판정을 바꾸지 않으므로 지문에서 뺍니다 — 제목을 고쳤다고 캐시를 버리지 않습니다. `changed_hunks` 도 뺍니다: 그것은 판정 대상이 아니라 변경 범위를 따라다니는 값입니다.

- 같은 함수가 그대로고 규칙도 그대로면 다시 판정하지 않습니다 — 세션이 달라도 (`verdict_ttl_days` 동안)
- 함수의 **어느 줄이든** 바뀌면 다시 판정합니다. VIOLATION 을 고치려고 반복문 위에 `with()` 를 추가해도 판정이 갱신됩니다
- 팩에 실린 Model 에 relationship 이 추가되는 것처럼 **관련 파일이 바뀌어도** 다시 판정합니다. 리뷰어가 그 내용을 읽고 판정했기 때문입니다
- 규칙의 instruction 이나 detect 를 고치면 그 규칙의 기존 판정은 재사용되지 않습니다
- 같은 파일의 다른 함수, 팩에 실리지 않은 파일이 바뀌는 것은 영향이 없습니다

캐시는 플러그인 데이터 디렉터리에 있고 레포에 커밋되지 않습니다. 모델의 의견은 팀 결정이 아니기 때문입니다. 팀이 합의한 예외는 `dismiss.py` 로 기각합니다.

## 검증 사이클과의 관계

| 상황 | 동작 |
|---|---|
| 리뷰어가 VIOLATION → 에이전트가 고침 → 함수 본문이 바뀜 | fixed 로 기록하고, 바뀐 함수는 한 번 더 판정 요청 |
| 리뷰어가 VALID | 다음 Stop 에서 제외 — 통과 |
| 판정 요청을 실행하지 않음 (기록 없음) | "실행되지 않았습니다" 로 한 번 더 요청, 그다음은 기록만 남기고 종료 |
| `max_verify_attempts` 소진 | 남은 판정 대기 후보를 `review_skipped` 로 기록하고 종료 |
| `mode: report` | 판정을 요청하지 않음 (차단할 수 없으므로). `review_skipped` 기록 |

## 규칙 작성

```yaml
detect:
  when_line_added: '\bforeach\s*\(|->each\s*\('     # 게이트: 좁을수록 싸다
semantic_review:
  context:
    - current_function
    - related_files: {symbol: '\b([A-Z]\w+)::(?:query|with|where)\b', glob: 'app/Models/{1}.php', max: 2}
  max_context_lines: 150
  instruction: |
    VIOLATION: 로드되지 않은 관계에 반복문 안에서 접근한다.
    VALID: 이미 with()/load() 로 로드됐거나 관계 접근이 없다.
    판단할 수 없으면 VALID 입니다.
```

- instruction 에 VIOLATION/VALID 조건을 한 문장씩, 그리고 "판단할 수 없으면 VALID"
- "레포 구조를 훑어보라" 같은 지시는 넣지 않습니다. 팩으로 판정할 수 없는 규칙은 지침(AGENTS.md)으로 남깁니다
- 픽스처는 게이트만 검사합니다

## 비용과 한계

- 판정은 후보가 있는 턴에만, 캐시에 없는 코드에만 발생합니다. 게이트가 넓으면 비용이 커지므로 `log_report.py` 의 정밀도(리뷰어가 VIOLATION 으로 판정한 비율)가 낮은 규칙은 게이트를 좁힙니다. `VALID` 가 많으면 게이트가 넓은 것이고, `FALSE_POSITIVE` 가 많으면 게이트가 엉뚱한 코드를 잡는 것이라 조치가 다릅니다
- 메인 에이전트가 판정 요청을 무시할 수 있습니다. 그 경우 한 번 더 요청하고, 로그에 `review_skipped` 로 남습니다
- `scan.py --review` 는 로컬 캐시에 의존하므로 CI 게이트에 쓰지 않습니다
