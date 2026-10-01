# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 레포

convention-guard — Claude Code 플러그인. PostToolUse 훅이 터치한 파일을 모으고, Stop 훅이 **이번 변경분만** 팀 컨벤션 규칙으로 검사해 차단 → 수정 → 재검증 사이클을 돌린다. 문서·커밋 메시지·주석은 한국어로 쓴다.

## 명령

```bash
# 개발 의존성 (hypothesis, coverage, PyYAML) — 테스트 전용
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt

.venv/bin/python tests/run_all.py                                  # 전체 (tests/**/test_*.py 자동 탐색)
CONVENTION_GUARD_NO_PYYAML=1 .venv/bin/python tests/run_all.py     # 내장 miniyaml 파서로 — 릴리스 전 둘 다 통과해야 함
.venv/bin/python tests/run_all.py --quiet                          # 실패한 스위트만 출력
.venv/bin/python tests/structure/test_mask.py                      # 스위트 하나 (pytest 아님, 종료 코드가 판정)
.venv/bin/python tests/rules/test_rule_fixtures.py                 # 규칙 픽스처
.venv/bin/python tests/integration/test_parity.py [--update]       # 골든(tests/integration/golden/parity.json) 비교/갱신
python3 tests/perf/run.py --corpus both                            # 성능 하네스 (run_all 에 포함 안 됨)

# 플러그인 실사용
python3 scripts/scan.py --range HEAD~5..HEAD      # --staged --files --all --fix --review --fail-on-pending
python3 scripts/detect_stack.py
claude --plugin-dir /root/convention-guard        # 임시 레포에서 실제 세션 점검
```

커버리지는 서브프로세스 측정이라 두 환경 변수가 모두 있어야 한다. 하나라도 없으면 숫자가 조용히 낮게 나온다: `COVERAGE_PROCESS_START=$PWD/.coveragerc COVERAGE_FILE=$PWD/.coverage` — 자세한 절차는 [docs/development.md](docs/development.md).

## 불변 제약

- **배포 경로(`scripts/**`, 훅, 스킬)는 표준 라이브러리만 쓴다.** PyYAML 이 있으면 쓰고, 없으면 `scripts/lib/miniyaml.py` 를 쓴다. 두 파서의 동등성은 `tests/unit/test_yaml_parity.py` 가 검사한다.
- **Python 3.9 호환** (구문과 표준 라이브러리 모두).
- **훅은 에이전트를 절대 깨뜨리지 않는다.** 훅 스크립트는 자기 버그가 나도 종료 코드 0. 구조 계층은 예외 대신 값(ok=False + 사유)으로 답한다. 모르면 후보를 남기고 "구조 미확인"으로 보고한다. 못 읽은 것을 통과로 처리하지 않는다.
- **진입점(`scripts/*.py`)은 인자와 입출력만 다룬다.** 결정 로직은 `scripts/lib/` 에 둔다.
- `.gitattributes` 때문에 CRLF 로 체크아웃되므로 스크립트는 항상 `python3 <경로>` 로 실행한다 (shebang 은 쓰지 않는다). 생성하거나 수정하는 파일은 원본의 줄바꿈을 따른다.
- 성능 예산: 파일 60개 변경, 후보 0건일 때 Stop 훅은 ~60ms. 파일마다 git 프로세스를 띄우지 않는다 (`gitdiff.diff_lines` 는 200개 단위 배치).

## 아키텍처 (큰 그림)

`hooks/hooks.json` 이 **언제**, `scripts/` 가 **어떻게**(얇은 어댑터), `rules/` 가 **무엇을**, `presets/` 가 **어느 규칙을**, `stacks/` 가 스택 감지 마커와 린터 위임을 맡는다.

- `collect.py` (Pre/PostToolUse): 터치한 파일과 세션 최초 HEAD 를 기록한다. Pre 는 파일을 처음 건드리기 직전에 이미 있던 추가 줄을 기준선(`foreign-<session>.jsonl`)으로 남기고, Bash 가 HEAD 를 옮기면 다른 사람 커밋이 가져온 줄도 남긴다. Stop 은 이 줄들을 개수만큼 빼서 **에이전트가 쓴 줄만** 검사한다 (판정 맥락은 파일 전체). Bash 는 실행 전후 dirty 파일 지문을 비교해, 사람이 먼저 수정해 둔 파일은 제외한다.
- `check.py` → `lib/hooks.py` (Stop): `ChangeScope` → `pipeline.run` → 결정론 후보 / 의미 판정 후보 / 없음(AI 호출 0) 중 하나로 나뉜다.
- **`pipeline.run` 하나를 `scan.py`, `dismiss.py`, `review.py` 가 모두 쓴다.** 각 진입점은 `scope.py` 에서 ChangeScope 를 만드는 방식(touched/staged/range/files/all)만 다르다.
- 파이프라인 순서: stacks → rules(프리셋 → disable → 적용 필터: 스택·버전·supersede·files 글롭) → linters(변경 줄에 걸린 것만) → `detect.py`(앵커별) → 구조 조건 필터 → 기각 적용.
- **앵커** (`when_line_added` 등): 추가된 줄, 새 파일, 변경 집합처럼 "이번 변경의 책임"을 정의한다. 레거시 위반에는 반응하지 않는다. 앵커 종류는 [docs/rules.md](docs/rules.md)에 있다.
- **구조 인식 계층 `scripts/lib/structure/`** (3.0): 어휘 마스킹(주석·문자열·정규식 리터럴)과 블록 트리다. 블록 트리는 언어별 헤더 규칙으로 만들고, Python 만 표준 `ast` 를 먼저 쓴다(`structure/native/pyast.py`, 읽지 못하면 들여쓰기 규칙). 규칙의 `not_in`·`in_scope`·`block_empty` 를 ACCEPT/REJECT/UNKNOWN 으로 평가한다. **필터일 뿐**이어서 후보의 스니펫·줄 번호·지문을 바꾸지 않는다. 그래서 기각 기록이 유지된다. 언어 정의는 `structure/native/langs.py` 에 있고, `backend.py` 는 나중에 tree-sitter 백엔드를 끼울 자리다.
- **후보 키 = `규칙:파일:코드 지문`.** 줄이 밀려도 같은 후보로 본다. 기각(`dismissed.yaml`)과 검증 사이클(`cycle.py`: fixed/dismissed/still/new)이 이 키에 의존하므로 지문 계산을 바꾸면 사용자 기록이 무효가 된다.
- 의미 판정(`semantic.py`, `context.py`, `agents/convention-reviewer.md`): 후보가 있고 캐시된 판정이 없을 때만 함수 하나 분량의 컨텍스트 팩을 서브에이전트에 넘긴다.
- 상태는 플러그인 데이터 디렉터리에 둔다(세션 상태, 판정 캐시, `firings.jsonl`). 레포 쪽 상태는 `.claude/convention-guard/{config.yaml,dismissed.yaml,rules/}` 뿐이다.
- 설정 우선순위: `config.yaml`(플러그인 기본값) < 설치 시 userConfig < 레포 config.

## 변경 절차

- **규칙**: `tests.no_match`(또는 `match`)에 사례를 먼저 추가해 실패를 확인하고 → 규칙을 수정하고 → 픽스처 테스트를 돌린다. 앵커가 `when_line_added` 단독이 아니면 `tests/rules/scenarios/` 도 고친다. 새 core 규칙은 `presets/*.yaml` 에 추가해야 한다 (안 하면 픽스처 테스트가 실패한다).
- **엔진**: 패리티 골든이 바뀌면 모든 사용자의 지적 결과가 바뀐다. 의도한 변화인지 확인한 뒤 `--update` 로 갱신하고, 같은 커밋에 넣고, 커밋 메시지에 diff 를 설명한다. Stop 훅 동작을 바꾸면 `tests/integration/test_hook_cycle.py` 에 턴 시나리오를 추가한다.
- **스킬·에이전트**: `tests/skills/test_skill_structure.py` 가 frontmatter, 500줄 미만 본문, 참조 깊이 1단계, 참조한 스크립트의 실재, 스킬당 evals 3개 이상(`tests/skills/evals/<스킬>.json`)을 강제한다. 스킬 안의 경로는 `${CLAUDE_PLUGIN_ROOT}` 로 쓴다. evals 는 자동 실행되지 않는다.
- **릴리스**: 두 테스트 실행(PyYAML 있음/없음)이 통과해야 한다 → `.claude-plugin/plugin.json` 과 `marketplace.json` 의 `version` 을 **둘 다** 올린다 → 형식이 바뀌었으면 `scripts/migrate.py` 와 `docs/migration-*.md` 도 고친다. 커밋 제목 형식: `release: X.Y.Z — <한 줄>`.

## Git

`.cursor/rules/git-master-direct.mdc`: 사용자가 커밋이나 푸시를 명시적으로 요청하면 `master` 에서 직접 진행한다 (브랜치를 따로 만들 필요 없음). 커밋 전 diff 를 읽고, 이번 작업과 관련된 경로만 명시적으로 스테이징한다. 다른 작업의 변경은 포함하지도 되돌리지도 않는다. force push, hard reset, amend 는 별도 승인이 있어야 한다.
