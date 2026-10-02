# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 레포

convention-guard — Claude Code 플러그인. Pre/PostToolUse 훅이 편집 사건 원장에 줄마다 출처를 기록하고, Stop 훅이 **에이전트가 쓴 줄만** 팀 컨벤션 규칙으로 검사해 차단 → 수정 → 재검증 사이클을 돌린다. 문서·커밋 메시지·주석은 한국어로 쓴다.

## 명령

```bash
# 개발 의존성 (hypothesis, coverage, PyYAML) — 테스트 전용
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt
python3 scripts/engine.py ensure --dir .engine                     # 개발용 구조 엔진 (run_all 이 자동으로 씀)

.venv/bin/python tests/run_all.py                                  # 전체, 엔진 있음
CONVENTION_GUARD_NO_ENGINE=1 .venv/bin/python tests/run_all.py     # 전체, 엔진 없음 — 릴리스 전 둘 다 통과해야 함
.venv/bin/python tests/run_all.py --quiet                          # 실패한 스위트만 출력
.venv/bin/python tests/structure/test_accuracy.py                  # 스위트 하나 (pytest 아님, 종료 코드가 판정)
.venv/bin/python tests/rules/test_rule_fixtures.py                 # 규칙 픽스처
.venv/bin/python tests/integration/test_parity.py [--update]       # 골든(tests/integration/golden/parity.json) 비교/갱신
python3 tests/perf/run.py                                          # 성능 목표 측정 (run_all 에 포함 안 됨)

# 플러그인 실사용
python3 scripts/scan.py --range HEAD~5..HEAD      # --staged --files --all --fix --review --fail-on-pending --require-engine
python3 scripts/detect_stack.py
python3 scripts/engine.py status                  # ensure / lock / verify-lock
claude --plugin-dir /root/convention-guard        # 임시 레포에서 실제 세션 점검
```

커버리지는 서브프로세스 측정이라 두 환경 변수가 모두 있어야 한다. 하나라도 없으면 숫자가 조용히 낮게 나온다: `COVERAGE_PROCESS_START=$PWD/.coveragerc COVERAGE_FILE=$PWD/.coverage` — 자세한 절차는 [docs/development.md](docs/development.md).

## 불변 제약

- **핵심 네 가지**: 훅이 위반을 차단하고 수정 → 재검증을 돌린다 · 에이전트가 쓴 줄에만 반응하고 레거시에는 반응하지 않는다 · 훅은 자기 버그로 에이전트를 깨뜨리지 않되 읽지 못한 것을 통과로 처리하지 않는다 · 위반 후보가 없으면 AI 호출은 0이다.
- **훅은 에이전트를 절대 깨뜨리지 않는다.** 훅 스크립트는 자기 버그가 나도 종료 코드 0. 수집 훅은 자기 오류를 원장에 적어 Stop 이 알리게 한다. 구조 계층은 예외 대신 값(ok=False + 사유)으로 답하고, 모르면 후보를 남기고 "구조 미확인"·"구조 엔진 없음"으로 보고한다. 관찰 누락도 이름 붙여 알린다.
- **Python 3.10 이상.** 실행 경로는 표준 라이브러리 + 플러그인이 스스로 설치하는 구조 엔진(tree-sitter, `scripts/lib/engine/`)뿐이다. YAML 은 내장 `miniyaml` 하나만 쓴다(PyYAML 은 동등성 테스트의 정답지). 네트워크는 엔진 설치기만 쓰고, `lock.json` 의 sha256 으로 고정한다.
- **진입점(`scripts/*.py`)은 인자와 입출력만 다룬다.** 결정 로직은 `scripts/lib/` 에 둔다. Stop 의 결정은 순수 함수 `lib/decide.py` (I/O 모듈을 임포트하지 않음 — 테스트가 강제).
- `.gitattributes` 때문에 CRLF 로 체크아웃되므로 스크립트는 항상 `python3 <경로>` 로 실행한다 (shebang 은 쓰지 않는다). 생성하거나 수정하는 파일은 원본의 줄바꿈을 따른다.
- 성능은 목표다(실패 조건 아님, [docs/design-4.0.md](docs/design-4.0.md) §7): 게이트에 걸리는 것 없는 60개 파일 Stop ~60ms, 수집 훅 1회 ~25ms(Edit)·~35ms(Bash). 수집 훅(`collect.py`)은 원장 모듈 밖을 임포트하지 않는다. 엔진은 정규식 게이트에 걸린 매치가 있을 때만 임포트한다.

## 아키텍처 (큰 그림)

`hooks/hooks.json` 이 **언제**, `scripts/` 가 **어떻게**(얇은 어댑터), `rules/` 가 **무엇을**, `presets/` 가 **어느 규칙을**, `stacks/` 가 스택 감지 마커와 린터 위임을 맡는다.

- `collect.py` (Pre/PostToolUse/PostToolUseFailure) → `lib/ledger.py`: 편집 사건 원장. 파일마다 마지막 내용과 줄별 출처(`p` 원래 / `a` 에이전트 / `o` 남의 커밋 / `u` 출처 미확인, 대문자 = 에이전트가 지운 자리)를 sqlite 에 둔다. Edit 계열은 경로로, Bash 와 모든 `mcp__*` 는 `git status` 전후 비교로 관찰한다. Pre 만 있고 Post 가 없거나, Post 만 왔거나, 도구 밖에서 바뀐 것은 Stop 이 이름 붙여 알린다.
- `check.py` → `lib/stop.py`(셸): 원장 정리 → `ChangeScope.from_ledger` → `pipeline.run` → `decide.decide(state, observation, cfg)` → 배치·상태·로그 저장 → 출력. 결정론 후보 / 의미 판정 후보 / 없음(AI 호출 0).
- `session_start.py` (SessionStart, async): 구조 엔진이 없으면 설치한다. Stop 도 엔진이 필요한데 없으면 백그라운드 설치를 시작한다.
- **`pipeline.run` 하나를 `scan.py`, `dismiss.py`, `review.py` 가 모두 쓴다.** 각 진입점은 ChangeScope 를 만드는 방식(훅: 원장 / CLI: working tree·staged·range·files·all)만 다르다.
- 파이프라인 순서: stacks → rules(프리셋 → disable → 적용 필터: 스택·버전·supersede·files 글롭) → linters(변경 줄에 걸린 것만) → `detect.py`(앵커별 정규식 게이트) → 구조 조건 → 기각 적용.
- **앵커** (`when_line_added` 등): 추가된 줄, 새 파일, 변경 집합처럼 "이번 변경의 책임"을 정의한다. 앵커 종류는 [docs/guide/ko/rules.md](docs/guide/ko/rules.md)에 있다.
- **구조 엔진 `scripts/lib/structure/`**: tree-sitter 트리를 언어별 노드 대응표(`nodes.py`)로 읽어 주석·문자열(그 안의 코드는 코드)·함수·루프(콜백 반복 포함)·catch 범위를 만든다(`treesitter.py`, Blade 는 `blade.py`). `not_in`·`in_scope`·`block_empty` 를 ACCEPT/REJECT/UNKNOWN 으로 평가한다. **필터일 뿐**이어서 후보의 스니펫·줄 번호·지문을 바꾸지 않는다. 첫 읽기 오류 뒤의 매치와 엔진이 없을 때는 UNKNOWN. 노드 이름은 `nodes.py` 에만 둔다.
- **후보 키 = `규칙:파일:코드 지문`.** 줄이 밀려도 같은 후보로 본다. 기각(`dismissed.yaml`, `version: 4`)과 검증 사이클(`decide.classify`: fixed/dismissed/still/new)이 이 키에 의존한다.
- 의미 판정(`semantic.py`, `batch.py`, `context.py`, `agents/convention-reviewer.md`): 후보가 있고 캐시된 판정이 없을 때만 함수 하나 분량의 컨텍스트 팩을 서브에이전트에 넘긴다. 배치 참조는 `<db 경로>#<id>`.
- 상태는 플러그인 데이터 디렉터리의 `convention-guard.db`(원장, 관찰 누락, 사이클 상태, 판정 캐시, 배치, 파싱 캐시)와 `engine/`, 로그는 `firings.jsonl`. 저장소 스키마가 바뀌면 이관하지 않고 다시 만든다. 레포 쪽 상태는 `.claude/convention-guard/{config.yaml,dismissed.yaml,rules/}` 뿐이다.
- 설정 우선순위: `config.yaml`(플러그인 기본값) < 설치 시 userConfig < 레포 config.

## 변경 절차

- **규칙**: `tests.no_match`(또는 `match`)에 사례를 먼저 추가해 실패를 확인하고 → 규칙을 수정하고 → 픽스처 테스트를 돌린다. 구조 조건이 있는 규칙의 사례는 파서가 읽을 수 있는 완결된 코드여야 한다. 앵커가 `when_line_added` 단독이 아니면 `tests/rules/scenarios/` 도 고친다. 새 core 규칙은 `presets/*.yaml` 에 추가해야 한다. 규칙 YAML 에 여러 줄 흐름 목록(`[a,\n b]`)은 쓰지 않는다 (miniyaml 이 읽지 못함).
- **엔진**: 패리티 골든이 바뀌면 모든 사용자의 지적 결과가 바뀐다. 의도한 변화인지 확인한 뒤 `--update` 로 갱신하고, 같은 커밋에 넣고, 커밋 메시지에 diff 를 설명한다. 사이클 전이를 바꾸면 `tests/unit/test_decide.py` 에 행을, 턴 동작은 `tests/integration/test_hook_cycle.py` 에 시나리오를 추가한다. 원장을 바꾸면 `tests/unit/test_ledger.py` 와 `tests/integration/test_ledger_scenarios.py`.
- **구조 엔진**: 판정이 틀린 사례는 `tests/structure/cases/<언어>.yaml` 에 먼저 추가한다. 문법 버전을 올리면 `scripts/lib/engine/install.py` 의 `PINS` → `python3 scripts/engine.py lock` → `test_nodes.py`·`test_accuracy.py`. 엔진이 필요한 테스트 사례는 `helpers.needs_engine()` 으로 묶는다.
- **스킬·에이전트**: `tests/skills/test_skill_structure.py` 가 frontmatter, 500줄 미만 본문, 참조 깊이 1단계, 참조한 스크립트의 실재, 스킬당 evals 3개 이상(`tests/skills/evals/<스킬>.json`)을 강제한다. 스킬 안의 경로는 `${CLAUDE_PLUGIN_ROOT}` 로 쓴다. evals 는 자동 실행되지 않는다.
- **문서**: 사용자 문서는 `README.md`·`README.en.md` 와 `docs/guide/ko/`·`docs/guide/en/` (같은 파일 이름, 같은 내용). 한쪽을 고치면 다른 언어판도 같은 커밋에서 고친다. 플러그인을 고치는 사람이 읽는 문서(구조·개발·설계·기록)는 `docs/` 에 둔다.
- **릴리스** ([docs/development.md](docs/development.md#릴리스)): 엔진 있음/없음 두 실행 + 하한 Python 3.10 실행이 통과해야 한다 → `python3 scripts/engine.py verify-lock` → `python3 tests/perf/run.py` 로 목표 값 기록 → 실제 `claude -p --plugin-dir` 세션 한 사이클 → `.claude-plugin/plugin.json` 과 `marketplace.json` 의 `version` 을 **둘 다** 올린다. 하위 호환이 끊기면 릴리스 커밋 본문에 밝힌다 (이관 도구는 만들지 않는다). 커밋 제목 형식: `release: X.Y.Z — <한 줄>`.

## Git

`.cursor/rules/git-master-direct.mdc`: 사용자가 커밋이나 푸시를 명시적으로 요청하면 `master` 에서 직접 진행한다 (브랜치를 따로 만들 필요 없음). 커밋 전 diff 를 읽고, 이번 작업과 관련된 경로만 명시적으로 스테이징한다. 다른 작업의 변경은 포함하지도 되돌리지도 않는다. force push, hard reset, amend 는 별도 승인이 있어야 한다.
