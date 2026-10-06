# 구조

## 목차
- 무엇을 하는가
- 전체 흐름
- 디렉터리와 모듈
- 편집 사건 원장
- 관찰 누락 알림
- Stop: 셸과 decide()
- 파이프라인
- 구조 엔진
- 검증 사이클
- 상태와 로그
- 검사 범위의 한계
- 설계 원칙

## 무엇을 하는가

AI 코딩 에이전트에게 팀 컨벤션을 알려주는 것(`CLAUDE.md`, `AGENTS.md`)만으로는 긴 세션에서 규칙이 희석됩니다.
convention-guard 는 에이전트가 작업을 끝낼 때마다 **에이전트가 쓴 줄**을 다시 검사하고, 위반이면 고치게 한 뒤 **고쳐졌는지 다시 검증**합니다.

```
Instruction → Execution → Verification → Feedback → Fix → Verification
```

## 전체 흐름

```
SessionStart (async)   session_start.py   구조 엔진(tree-sitter)이 없으면 설치, 오래된 세션 정리
        │
PreToolUse / PostToolUse / PostToolUseFailure      collect.py → lib/ledger.py
  (Write|Edit|MultiEdit|NotebookEdit|Bash|mcp__*)    도구 호출 전후 내용을 비교해 줄마다 출처를 기록
        │                                          (출력·컨텍스트 0)
Stop                   check.py → lib/stop.py (셸) → lib/decide.py (순수 결정)
        │
   원장 정리 ── 열린 사건(Post 없음) · 도구 밖 변경(출처 미확인) · 관찰 누락 알림
        │
   에이전트 줄(ChangeScope.from_ledger) → pipeline.run
        │      스택 → 규칙 → 린터 → 정규식 게이트 → 구조 확인(tree-sitter) → 기각
        │
   decide(state, observation, cfg)
        ├ 판정할 것 없음 → 통과 (AI 호출 0)
        ├ 결정론 후보 → 차단 + 검증 사이클
        └ 의미 판정 후보 → 판정 캐시 → 없으면 배치 → convention-reviewer 에이전트
```

수동 실행(`scan.py`), 기각(`dismiss.py`), 판정 배치(`review.py`)도 같은 `pipeline.run` 을 씁니다. 차이는 ChangeScope 를 어떻게 만드는가뿐입니다 (훅은 원장, CLI 는 git).

## 디렉터리와 모듈

| 디렉터리 | 책임 | 하지 않는 것 |
|---|---|---|
| `hooks/` | **언제** — 훅 이벤트에 스크립트 연결 | 검사 로직 |
| `scripts/` | **어떻게** — 진입점(인자·입출력만) | 정책 판단 |
| `scripts/lib/` | 원장·범위·규칙·탐지·구조·결정·출력 | 훅 입출력 |
| `rules/` | **무엇을** — 컨벤션 정의 | 구현 |
| `presets/` | **어느 규칙을** — 목적·스택별 묶음 | 규칙 내용 |
| `stacks/` | 스택 감지 마커와 린터 위임 | 규칙 |
| `agents/` | 의미 판정 서브에이전트 | 코드 수정 |
| `skills/` | **AI 워크플로** — 도입·발굴·검사·규칙 추가·튜닝 | 결정적 실행 (스크립트를 부름) |

`scripts/lib/` 모듈:

| 모듈 | 역할 |
|---|---|
| `ledger.py` | 편집 사건 원장: 줄 출처, `apply()`, 사건 처리, 관찰 누락 기록, Stop 정리 |
| `observe.py` | stat 서명, git 방식 줄 읽기, `git status` 한 번으로 HEAD 와 dirty 경로, blob 읽기 |
| `store.py` | sqlite 저장소 (`convention-guard.db`): 스키마, 트랜잭션, GC |
| `state.py` | Stop 의 사이클 상태 읽기·쓰기 |
| `decide.py` | 사이클 전이를 모은 순수 함수 `decide()`, 분류(fixed/dismissed/still/new) |
| `stop.py` | Stop 셸: 관찰 → decide → 저장·로그·렌더, 알림 붙이기 |
| `scope.py` | ChangeScope — 원장(`from_ledger`) 또는 git(working tree / staged / range / files / all) |
| `gitdiff.py` | CLI 범위의 배치 git diff, 남의 커밋이 들여온 줄 |
| `pipeline.py` | 스택 → 규칙 → 린터 → 탐지 → 기각, 모든 진입점이 공유 |
| `detect.py` | 앵커별 탐지 → Candidate, 구조 조건 필터 |
| `structure/` | 구조 엔진: `nodes.py`(언어별 노드 대응표), `treesitter.py`, `blade.py`, `conditions.py`, `model.py` |
| `engine/` | tree-sitter 설치기(`install.py`, `tags.py`, `lock.json`)와 로더(`loader.py`) |
| `batch.py`, `semantic.py`, `context.py` | 판정 배치 계획, 판정 캐시·배치 저장, 최소 컨텍스트 팩 |
| `rules/`, `config.py`, `stack.py`, `lint.py`, `dismiss.py`, `autofix.py` | 규칙 스키마·레이어·프리셋, 설정 병합, 스택 감지, 린터, 기각, 자동 수정 |
| `report.py`, `fmt.py`, `log.py` | 차단 메시지·CLI 출력, 형식 명세, 발동 로그 |

## 편집 사건 원장

`lib/ledger.py`. 줄의 출처를 **도구 호출이 일어날 때마다** 기록하고, Stop 은 기록을 읽기만 합니다.

| 출처 | 뜻 | 검사 |
|---|---|---|
| `p` pre | 원장이 그 파일을 처음 볼 때 이미 있던 줄 | 안 함 |
| `a` agent | 에이전트 도구 호출(Pre → Post) 사이에 생긴 줄 | **함** |
| `o` other | Bash 호출이 HEAD 를 옮기며 남의 커밋이 들여온 줄 | 안 함 |
| `u` unknown | 도구 호출 밖에서 바뀐 줄 (사람, 에디터, 백그라운드 프로세스) | 안 함, 이름 붙여 알림 |

대문자는 이음매입니다: 에이전트가 그 줄 바로 뒤의 줄을 지웠다는 표시입니다. 블록을 비우는 것처럼 지우기만 한 변경도 검사 대상이 됩니다.

관찰 방식은 두 가지입니다.

| 방식 | 도구 | Pre | Post / PostToolUseFailure |
|---|---|---|---|
| 파일 | Write, Edit, MultiEdit, NotebookEdit | 경로마다 현재 내용을 기억 (원장에 없으면 전부 `p`, 그 사이 바뀌었으면 `u`) | 바뀐 줄을 `a` 로 |
| 작업 트리 | Bash, 모든 `mcp__*` | `git status` 한 번 + HEAD. 원장이 모르는 dirty 파일의 내용을 `p` 로 | 다시 `git status`. 바뀐 파일을 `a` 로, HEAD 가 움직였으면 남의 커밋 줄은 `o` |

`apply(이전, 출처, 새 내용, 라벨)` 은 공통 접두·접미를 잘라 낸 뒤 가운데만 `difflib` 로 정렬합니다. 같은 사건 안에서 지운 줄과 텍스트가 똑같은 새 줄은 지운 줄의 출처를 이어받습니다 — 파일 안에서 줄을 옮기거나 `mv` 로 파일을 옮긴 것은 쓴 것이 아닙니다. 공백만 바뀐 줄은 바뀐 줄입니다.

`absent` 앵커의 "새 파일"은 원장이 처음 볼 때 없던 파일을 에이전트가 써서 만든 경우입니다 (옮겨 온 파일, 사람이 만든 파일은 아님).

## 관찰 누락 알림

수집 훅이 놓친 것은 Stop 이 이름을 붙여 말합니다. 침묵하는 경로가 없습니다.

| 알림 | 언제 | 검사 |
|---|---|---|
| 관찰 누락 — 실행 후 기록 없음 | Pre 만 있고 Post 가 오지 않은 사건, 그 사이 파일이 바뀜 | 바뀐 줄을 에이전트 것으로 검사 |
| (알리지 않음) | Pre 만 있고 파일이 그대로 — 권한 거부나 PreToolUse 차단으로 실행되지 않은 도구 | — |
| 관찰 누락 — 실행 전 기록 없음 | Pre 없이 온 Post | 바뀐 줄을 에이전트 것으로 검사 |
| 출처 미확인 변경 | 원장 파일이 도구 밖에서 바뀜, 또는 원장 밖 dirty 경로가 지난 Stop 이후 바뀜 | 안 함 |
| 작업 트리 관찰 실패 | `git status` 가 실패해 Bash/MCP 호출이 바꾼 파일을 모름 | — |
| 검사되지 않음 (레포 밖) | 작업 트리 밖 경로를 쓴 도구 | — |
| git 레포가 아니라 검사하지 않음 | 프로젝트가 git 작업 트리가 아님 | — |
| 수집 훅 오류 | 수집 훅이 자기 예외를 원장에 적음 | — |

## Stop: 셸과 decide()

```
stop.py (셸)
  payload → Request(prompt_id, stop_hook_active, 질문으로 끝났는가), 설정, 상태
  ledger.at_stop()                    원장 정리 + 관찰 누락 수집
  decide.needs_scan()?  → 스캔 (+ auto-fix) + 판정 캐시 트리아지
  decide.decide(state, observation, cfg)        ← 파일·시계·DB 를 읽지 않는 순수 함수
  배치 저장 → 상태 저장 → 발동 로그 → 출력 렌더 + 알림
```

`decide()` 는 (다음 상태, 행동, 로그 이벤트, 저장할 배치)를 돌려줍니다. 행동은 `Silent`, `Notice`, `ConfigError`, `Block(open|verify)` 중 하나이고, 문구는 `report.py` 가 만듭니다. 전이는 `tests/unit/test_decide.py` 의 표 테스트로 고정되어 있습니다. 판정 배치의 참조(`<db 경로>#<id>`)는 셸이 미리 만든 id 를 써서 decide 가 상태에 바로 적습니다.

## 파이프라인

```
scope → stacks → rules (프리셋 → 비활성 규칙 제외 → 적용 가능성 필터)
      → linters (변경 줄에 걸린 실패만 차단)
      → detect (앵커별 정규식 게이트 → 구조 확인) → 기각 적용
      → hits (결정론) + semantic_hits (의미 판정 대상)
```

**변경 앵커**: 규칙마다 "이번 변경의 책임"을 선언합니다 — 추가된 줄, 새 파일, 변경 집합, 변경된 줄과 겹치는 여러 줄 매치. 레거시 코드가 있는 파일을 건드려도 기존 위반은 걸리지 않습니다. 자세히: [rules.md](guide/ko/rules.md)

## 구조 엔진

정규식은 `dd(` 를 찾을 뿐, 그것이 주석 안인지 문자열 안인지, 루프 안인지 모릅니다. 구조 조건(`not_in`, `in_scope`, `block_empty`)이 그 질문에 답합니다.

```
정규식 게이트 (매치가 없으면 끝 — 엔진은 임포트조차 하지 않음)
   → structure.analyze(text, language)        파일당 한 번, 프로세스 안 메모
        tree-sitter 트리 → FileStructure(주석·문자열 구간, 오류 구간, 범위 트리)
   → conditions.evaluate → ACCEPT 후보로 남김 / REJECT 뺌 / UNKNOWN 남기고 "구조 미확인"
```

| 항목 | 내용 |
|---|---|
| **필터일 뿐** | 후보를 만들지 않고, 스니펫·줄 번호·지문을 바꾸지 않습니다. 그래서 기각 기록이 살아남습니다 |
| **노드 대응표** | 언어 행 하나(`structure/nodes.py`)가 주석·문자열·함수·루프·클래스·catch·분기 노드를 정합니다. 문자열 안의 코드(템플릿 `${}`, f-string `{}`, PHP 보간식)는 코드입니다. 콜백 반복(`forEach`, `->each`, `array_map`, `map(lambda)`)은 메서드 이름 목록이 필요합니다 |
| **Blade** | Blade 문법(주석, 출력식, `@php`, 지시문 인자, 짝 지시문 블록)은 `blade.py` 가 읽고, 그 안의 PHP 만 tree-sitter 가 파싱합니다 |
| **읽기 오류** | 파일의 첫 읽기 오류 지점부터 뒤의 매치는 UNKNOWN 입니다 (닫히지 않은 따옴표는 뒤 전체를 바꿉니다). 앞은 정상 판정합니다 |
| **엔진 없음** | 내장 대체 계층은 없습니다. 모든 구조 조건이 UNKNOWN 이고, 후보를 남기고 "구조 엔진 없음 (사유)" 로 알립니다 |
| **값으로 답하고 예외를 던지지 않습니다** | 훅이 엔진 문제로 죽지 않습니다 |

엔진 설치: `lib/engine/install.py` 가 `lock.json` 의 고정 휠(tree-sitter 0.25.2, javascript 0.25.0, typescript 0.23.2, php 0.24.1, python 0.25.0)을 files.pythonhosted.org 에서 받아 sha256 을 확인하고, 경로 탈출을 막아 풀고, 임시 디렉터리에서 모든 문법을 불러 파싱해 본 뒤 `${CLAUDE_PLUGIN_DATA}/engine/<lock id>/<cp3XY-os-arch>/` 로 옮깁니다. venv·pip 를 쓰지 않습니다. 설치 시점은 `SessionStart` 훅(백그라운드), Stop 이 엔진이 필요한데 없을 때(백그라운드), `scripts/engine.py ensure`(CI) 셋입니다. 로더는 이 고정 디렉터리만 보고 사이트 패키지의 다른 tree-sitter 는 쓰지 않습니다.

## 검증 사이클

차단하면 사이클이 열리고, 같은 요청의 다음 Stop(`stop_hook_active`)에서 같은 범위를 다시 검사합니다.

| 결과 | 뜻 |
|---|---|
| fixed | 지적한 후보가 사라짐 |
| dismissed | 오탐으로 기각됨 |
| still | 그대로 남음 (제자리 재포맷·통째 이동도 still) |
| new | 사이클을 열 때 없던 후보 — 대개 수정이 만든 것 |

still 이나 new 중 error 가 있으면 `limits.max_verify_attempts` 까지 다시 차단하고, 그다음에는 남은 것을 기록만 하고 닫습니다. `limits.max_consecutive_blocks` 가 요청마다 루프를 묶습니다. 표시 예산 밖의 error 는 차단하지 않지만 통과로 닫지도 않습니다("미표시 N"). 사용자가 요청을 중단하고 새 요청을 보내면 열린 사이클은 abandoned 로 닫힙니다.

후보 식별은 `규칙:파일:코드 지문` 키입니다 (줄 전체를 공백 정규화한 sha1 앞 10자리). 위쪽에 줄이 추가돼도 같은 후보이고, 줄 자체가 바뀌면 다른 후보입니다.

## 상태와 로그

| 위치 | 내용 |
|---|---|
| `${CLAUDE_PLUGIN_DATA}/convention-guard.db` | sqlite 하나: 원장(`ledger_*`), 관찰 누락(`observe_issue`), 사이클 상태, 판정 캐시, 판정 배치, 파싱 캐시. 스키마 버전이 다르면 이관하지 않고 다시 만듭니다 |
| `${CLAUDE_PLUGIN_DATA}/engine/` | 구조 엔진 설치와 `status.json`(마지막 설치 시도) |
| `firings.jsonl` | 발동 로그 (schema 2). `userConfig.log_dir` 로 옮길 수 있음 |

레포 쪽 파일은 `.claude/convention-guard/` 의 `config.yaml`, `dismissed.yaml`(`version: 4`), `rules/` 뿐이고 모두 커밋 대상입니다.

## 검사 범위의 한계

- 도구 호출 구간(Pre → Post) 안에서 사람이 같은 파일을 고치면 에이전트 줄로 봅니다. 구간이 도구 실행 시간뿐이라 받아들입니다.
- 사람이 에이전트가 쓴 줄을 다시 고치면 그 줄은 `u` 가 되어 검사에서 빠집니다 (이름은 남습니다).
- 남의 커밋을 들여오는 바로 그 Bash 호출 안에서 에이전트가 그 커밋과 똑같은 줄을 쓰면 `o` 로 봅니다.
- `.gitignore` 에 걸린 파일, 400KB 를 넘는 파일(이름 붙여 알림), 바이너리는 검사하지 않습니다.
- Bash/MCP Pre 는 원장이 모르는 dirty 파일의 내용을 세션당 한 번 읽습니다. 무시되지 않는 거대한 미추적 트리는 비용입니다.

린터에는 단계 전체의 예산(`stop.LINT_BUDGET`)이 있어 Stop 훅 시간 제한을 넘기지 않고, 돌리지 못한 린터는 경고로 남깁니다.

## 설계 원칙

1. **후보는 위반이 아니다.** 정규식은 후보를 좁히고, 판정은 코드를 본 에이전트·리뷰어·팀이 한다.
2. **의미 판정은 필요할 때만.** 게이트 후보도, 글롭 규칙의 판정 단위도 없으면 AI 호출도 없다. 판정 단위는 함수·파일 머리이고, 의미 있는 줄(글자가 있는 줄)을 에이전트가 추가했을 때만 생긴다 (`lib/units.py`).
3. **최소 충분 컨텍스트.** 리뷰어에게 레포가 아니라 함수 하나와 필요한 주변만 준다.
4. **에이전트가 쓴 줄만.** 레거시와 사람의 줄은 이번 변경의 책임이 아니다.
5. **읽지 못한 것은 통과가 아니다.** 관찰 누락, 구조 미확인, 엔진 없음은 이름 붙여 말한다.
6. **결정적 도구 우선.** 린터·포맷터가 할 수 있는 것은 규칙으로 만들지 않는다.
7. **고친 뒤에는 반드시 검증.**
8. **같은 판단을 반복하지 않는다.** 기각은 코드 지문, 판정은 함수 본문 해시로 기억한다.
