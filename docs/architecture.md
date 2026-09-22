# 구조

## 목차
- 무엇을 하는가
- 전체 흐름
- 디렉터리 책임
- 파이프라인
- 검증 사이클
- 구조 인식 계층
- 의미 판정
- 상태와 로그
- 설계 원칙

## 무엇을 하는가

AI 코딩 에이전트에게 팀 컨벤션을 알려주는 것(`CLAUDE.md`, `AGENTS.md`)만으로는 긴 세션에서 규칙이 희석됩니다.
convention-guard 는 에이전트가 작업을 끝낼 때마다 **이번 작업이 바꾼 것**을 다시 검사하고, 위반이면 고치게 한 뒤 **고쳐졌는지 다시 검증**합니다.

```
Instruction → Execution → Verification → Feedback → Fix → Verification
```

## 전체 흐름

```
PostToolUse(Write|Edit|MultiEdit|NotebookEdit)   collect.py   터치한 파일 경로와 세션 최초 HEAD 기록 (출력·컨텍스트 0)
                                │
Stop                      check.py ─── lib/hooks.py
                                │
                   ┌────────────┴────────────┐
             열린 사이클 없음              열린 사이클 있음 (같은 요청의 계속)
                   │                          │
            ChangeScope (이번 작업)          같은 범위 재검사
                   │                          │
              pipeline.run                고쳐짐 / 기각 / 그대로 / 새로 생김
     (스택 → 프리셋·규칙 → 린터 →              │
      결정론 탐지 → 기각 적용)          남았으면 한 번 더 차단, 아니면 종료
                   │
   ┌───────────────┼────────────────┐
결정론 후보    semantic 후보         없음 → 통과 (AI 호출 0)
   │               │
   │        판정 캐시 조회 ── VALID/FALSE_POSITIVE → 제외
   │               │         VIOLATION → 결정론 후보처럼 처리
   │               └ 판정 없음 → 배치 파일 → convention-reviewer 에이전트
   │
 예산(강도별 상한·연속 차단 상한) → 차단 + 검증 사이클 시작
```

수동 실행(`scan.py`), 기각(`dismiss.py`), 판정 배치(`review.py`)도 같은 `pipeline.run` 을 씁니다. 차이는 ChangeScope 를 어떻게 만드는가뿐입니다.

## 디렉터리 책임

| 디렉터리 | 책임 | 하지 않는 것 |
|---|---|---|
| `hooks/` | **언제** — PostToolUse·Stop 에 스크립트 연결 | 검사 로직 |
| `scripts/` | **어떻게** — 진입점(얇은 어댑터) | 정책 판단 |
| `scripts/lib/` | 범위·규칙·탐지·파이프라인·사이클·판정·출력 | 훅 입출력 |
| `rules/` | **무엇을** — 컨벤션 정의 (1.0 스키마) | 구현 |
| `presets/` | **어느 규칙을** — 목적·스택별 묶음 | 규칙 내용 |
| `stacks/` | 스택 감지 마커와 린터 위임 | 규칙 |
| `agents/` | 의미 판정 서브에이전트 | 코드 수정 |
| `skills/` | **AI 워크플로** — 도입·발굴·검사·규칙 추가·튜닝 | 결정적 실행 (스크립트를 부름) |
| `docs/` | 왜·어떻게 | |
| `tests/` | 동작 검증 | |

`scripts/lib/` 모듈:

| 모듈 | 역할 |
|---|---|
| `scope.py` | ChangeScope — 무엇이 이번 변경인가 (touched / 워킹 트리 / staged / range / files / all) |
| `gitdiff.py` | 추가된 줄만 뽑는 배치 git diff |
| `stack.py` | 마커 파일로 스택·버전 감지 |
| `rules/` | `schema.py` 파싱·검증, `loader.py` 레이어·오버라이드·프리셋·설정, `select.py` 적용 필터 |
| `detect.py` | 앵커별 결정론 탐지 → Candidate. 규칙에 구조 조건이 있으면 `structure/` 에 물어 후보를 거름 |
| `structure/` | **구조 인식 계층 (3.0)** — 주석·문자열 마스킹과 블록 트리 |
| `candidate.py` | Candidate, 지문(키), 판정 상수 |
| `lint.py` | 린터 실행과 출력 파싱, 변경 줄 앵커링 |
| `pipeline.py` | 위 모두를 한 번에 |
| `cycle.py` | 검증 사이클 상태 머신 |
| `semantic.py`, `context.py` | 판정 캐시·배치, 최소 컨텍스트 팩 |
| `autofix.py` | `fix.auto` 적용 |
| `dismiss.py` | 기각 기록 |
| `config.py` | 설정 병합과 검증 |
| `hooks.py` | Stop·PostToolUse 정책 |
| `report.py` | 차단 메시지·CLI 출력 |
| `state.py`, `log.py`, `cache.py` | 세션 상태, 발동 로그, 파싱 캐시 |

## 구조 인식 계층 (3.0)

정규식은 `dd(` 를 찾을 뿐, 그것이 주석 안인지 문자열 안인지 모릅니다. 3.0 은 그 질문에 답하는 계층을 탐지 **뒤**에 둡니다.

```
정규식 매치 (Span)  →  structure.analyze(text, language)  →  conditions.evaluate
                              │                                    │
                     FileStructure(ok, 주석·문자열 구간,      ACCEPT  후보로 남김
                                   블록 트리)                 REJECT  후보에서 뺌
                              │                              UNKNOWN 후보로 남기고
                     읽지 못하면 ok=False + 사유                     "구조 미확인" 고지
```

| 항목 | 내용 |
|---|---|
| **필터일 뿐** | 후보를 만들지 않고, 스니펫·줄 번호·지문을 바꾸지 않습니다. 그래서 기각 기록이 살아남습니다 |
| **모르면 지킵니다** | 파일을 읽지 못하면 후보를 남기고 **"구조 미확인"으로 보고**합니다. 읽지 못한 것이 깨끗한 통과처럼 보이면 안 됩니다 |
| **값으로 답하고 예외를 던지지 않습니다** | 훅이 우리 버그로 죽지 않아야 합니다 |
| **프로세스 안에서만 기억합니다** | 같은 파일을 서른 개 규칙이 읽어도 한 번만 분석합니다. 훅은 매 턴 새 프로세스라 디스크에 쓰지 않습니다 |

| 모듈 | 역할 |
|---|---|
| `structure/model.py` | `FileStructure`, `ScopeNode`, `Span`, ACCEPT/REJECT/UNKNOWN |
| `structure/backend.py` | 백엔드 인터페이스와 등록 |
| `structure/native/` | 표준 라이브러리만 쓰는 기본 백엔드 — 언어 정의(`langs.py`)와 어휘 스캔 |
| `structure/conditions.py` | `not_in`·`in_scope`·`block_empty` 평가 |
| `rules/fixtures.py` | 픽스처 조각을 파일로 합성해 매칭 — 픽스처 실행기와 `migrate.py` 가 **같은 것**을 씁니다 |

**이것은 AST 파서가 아닙니다.** 어휘 마스킹 + 블록 트리이며, 타입이나 심볼 해석은 하지 않습니다. `backend.py` 의 인터페이스는 tree-sitter 백엔드(3.1)를 갈아 끼울 자리로 둔 것이고, 규칙 스키마와 탐지 로직은 그때도 바뀌지 않습니다.

## 파이프라인

```
scope → stacks → rules (프리셋 → 비활성 규칙 제외 → 적용 가능성 필터)
      → linters (변경 줄에 걸린 실패만 차단)
      → detect (앵커별) → 기각 적용
      → hits (결정론) + semantic_hits (의미 판정 대상)
```

**변경 앵커**: 트리거마다 "이번 변경의 책임"이 다릅니다. 추가된 줄, 새 파일, 변경 집합, 변경된 줄과 겹치는 여러 줄 매치. 그래서 레거시 코드가 있는 파일을 건드려도 기존 위반은 걸리지 않습니다. 자세히: [rules.md](rules.md)

**규칙 필터링**: 스택·버전 게이트, supersede 마커, 변경된 경로가 규칙의 `files` 에 하나라도 닿는지를 먼저 봅니다. 닿지 않는 규칙은 탐지기를 돌리지 않습니다.

## 검증 사이클

차단하면 사이클이 열리고, 같은 요청의 다음 Stop(`stop_hook_active`)에서 같은 범위를 다시 검사합니다.

| 결과 | 뜻 |
|---|---|
| fixed | 지적한 후보가 사라짐 |
| dismissed | 오탐으로 기각됨 |
| still | 그대로 남음 |
| new | 사이클을 열 때 없던 후보 — 대개 수정이 만든 것 |

still 이나 new 중 error 가 있으면 `limits.max_verify_attempts` 까지 다시 차단하고, 그다음에는 남은 것을 기록만 하고 닫습니다. 사이클 전체가 `limits.max_consecutive_blocks` 안에 묶여 있어 무한 루프가 되지 않습니다.

후보 식별은 `규칙:파일:코드 지문` 키입니다. 위쪽에 줄이 추가돼도 같은 후보이고, 줄 자체가 바뀌면 다른 후보입니다. 처음에 표시 예산 때문에 보여주지 않은 후보도 "본 것"으로 기억해 new 로 오인하지 않습니다.

사용자가 요청을 중단하고 새 요청을 보내면(`stop_hook_active` 가 아닌 Stop) 열린 사이클은 abandoned 로 닫히고, 결과는 그대로 측정됩니다.

## 검사 범위의 한계

검사 대상은 수집 훅이 기록한 터치 파일입니다. Write/Edit 계열은 도구 입력의 파일 경로를 사용합니다.
Bash 는 PreToolUse 에서 기존 dirty 파일의 지문을 저장하고 PostToolUse 에서 달라진 경로만 추가하므로,
사람이 먼저 수정해 둔 파일을 에이전트 책임으로 묶지 않습니다. 다음은 여전히 **검사되지 않습니다**.

- 수집 훅이 10초 예산 안에 끝나지 못한 편집
- PreToolUse 없이 PostToolUse 만 전달된 Bash 호출

세션의 첫 수집 시점 HEAD도 저장하므로 Stop 전에 커밋한 변경까지 검사합니다. 범위 계산 실패는
깨끗한 통과로 읽지 않고 검사 불가 메시지를 냅니다.

린터도 같은 성격의 예산이 있습니다. `linters.timeout` 은 린터 **하나당**이고 순차 실행이라, Stop 훅 예산(`hooks/hooks.json` 의 150초)을 넘기면 훅이 죽고 훅이 죽으면 아무것도 출력하지 않아 "통과"와 구분되지 않습니다. `hooks.LINT_BUDGET` 이 린터 단계 전체를 잘라 이를 막고, 돌리지 못한 린터는 경고로 남깁니다.

## 의미 판정

[semantic-review.md](semantic-review.md)

## 상태와 로그

| 파일 (플러그인 데이터 디렉터리) | 내용 |
|---|---|
| `touched-<session>.txt` | 수집 훅이 한 줄씩 덧붙이는 터치 파일 (병렬 실행 안전) |
| `base-<session>.json` | 세션 첫 수정 시점의 레포 루트와 HEAD |
| `bash-<session>-<tool>.json` | Bash 실행 전 dirty 파일 지문 (PostToolUse 후 삭제) |
| `session-<session>.json` | 연속 차단 수, 열린 사이클, 세션 동안 고쳐진 규칙 |
| `reviews/*.json` | 판정 배치와 기록된 판정 (7일 후 정리) |
| `verdicts.json` | 판정 캐시 (레포별, TTL) |
| `cache-yaml.json` | 규칙·프리셋·스택 파일 파싱 캐시 |
| `firings.jsonl` | 발동 로그 (schema 2). `userConfig.log_dir` 로 옮길 수 있음 |

레포 쪽 파일은 `.claude/convention-guard/` 의 `config.yaml`, `dismissed.yaml`, `rules/` 뿐이고 모두 커밋 대상입니다.

## 설계 원칙

1. **후보는 위반이 아니다.** 정규식은 후보를 좁히고, 판정은 코드를 본 에이전트·리뷰어·팀이 한다.
2. **의미 판정은 필요할 때만.** 후보가 없으면 AI 호출도 없다.
3. **최소 충분 컨텍스트.** 리뷰어에게 레포가 아니라 함수 하나와 필요한 주변만 준다.
4. **변경된 코드 중심.** 레거시는 이번 변경의 책임이 아니다.
5. **결정적 도구 우선.** 린터·포맷터가 할 수 있는 것은 규칙으로 만들지 않는다.
6. **AI 는 맥락 판단에만.**
7. **고친 뒤에는 반드시 검증.**
8. **같은 판단을 반복하지 않는다.** 기각은 코드 지문, 판정은 함수 본문 해시로 기억한다.
