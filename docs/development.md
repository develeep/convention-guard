# 개발

## 목차
- 원칙
- 준비
- 테스트
- 규칙을 바꿀 때
- 엔진을 바꿀 때
- 구조 엔진을 바꿀 때
- 스킬과 에이전트를 바꿀 때
- 줄바꿈과 실행
- 릴리스

## 원칙

- 핵심 네 가지: 훅이 위반을 차단하고 수정 → 재검증을 돌린다 · 에이전트가 쓴 줄만 검사한다 · 훅은 자기 버그로 에이전트를 깨뜨리지 않되 읽지 못한 것을 통과로 처리하지 않는다 · 판정할 것이 없으면 AI 호출은 0이다 (판정할 것은 정규식 게이트를 통과한 후보와, `when_code_added` 규칙의 글롭에 든 파일에서 에이전트가 의미 있는 줄을 추가한 판정 단위뿐이다. 캐시에 판정이 있는 것은 다시 묻지 않는다)
- Python 3.10 이상. 실행 경로는 표준 라이브러리 + 플러그인이 스스로 설치하는 구조 엔진(tree-sitter)뿐입니다. YAML 은 내장 `miniyaml` 하나만 씁니다
- 결정은 `scripts/lib` 에, 진입점(`scripts/*.py`)은 인자·입출력만. Stop 의 결정은 순수 함수 `lib/decide.py` 에 있습니다

## 준비

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt     # coverage, PyYAML (테스트 전용)
python3 scripts/engine.py ensure --dir .engine              # 개발용 구조 엔진 (.gitignore)
```

`tests/run_all.py` 는 `.engine/` 이 있으면 `CONVENTION_GUARD_ENGINE_DIR` 로 씁니다. 엔진은 인터프리터마다(cp310, cp312 …) 따로 설치됩니다 — 다른 버전으로 테스트하려면 그 버전으로 `engine.py ensure --dir .engine` 을 한 번 더 돌립니다.

## 테스트

```bash
.venv/bin/python tests/run_all.py                                  # 엔진 있음
CONVENTION_GUARD_NO_ENGINE=1 .venv/bin/python tests/run_all.py     # 엔진 없음
.venv/bin/python tests/run_all.py --quiet                          # 실패한 스위트만
.venv/bin/python tests/structure/test_accuracy.py                  # 스위트 하나 (pytest 아님, 종료 코드가 판정)
.venv/bin/python tests/run_all.py --repo /path/to/repo             # 그 레포의 로컬 규칙 픽스처까지
```

**두 번 돕니다.** 엔진 있음 실행은 모든 판정을, 엔진 없음 실행은 엔진이 없을 때의 약속(구조 조건은 UNKNOWN, 후보는 남고, "구조 엔진 없음" 으로 알림)을 확인합니다. 구조 판정에 기대는 사례는 `helpers.needs_engine()` 로 묶여 있어서, 엔진 없음 실행에서는 건너뛰고 그 개수를 출력합니다. 엔진 없이 **실수로** 돌리면(`CONVENTION_GUARD_NO_ENGINE` 없이 엔진이 없음) 실패합니다.

`run_all.py` 는 실행마다 임시 `CLAUDE_PLUGIN_DATA` 를 줍니다. `helpers.isolated_env` 가 HOME·데이터 디렉터리를 격리하므로 이 머신의 사용자 규칙이나 상태가 결과에 섞이지 않습니다.

커버리지는 스위트를 서브프로세스로 띄우므로 병렬 모드가 필요합니다.

```bash
export COVERAGE_PROCESS_START=$PWD/.coveragerc COVERAGE_FILE=$PWD/.coverage
.venv/bin/python -m coverage run --parallel-mode tests/run_all.py
.venv/bin/python -m coverage combine
.venv/bin/python -m coverage report --include='*/lib/*'
```

두 변수가 다 필요합니다. 하나라도 없으면 숫자가 **조용히** 낮게 나옵니다.

성능은 매 실행에 끼지 않습니다 (목표이지 실패 조건이 아님 — [design-4.0.md](design-4.0.md) §7).

```bash
python3 tests/perf/run.py                       # stop / stop_gated / edit·bash pre·post / gate / engine_import / analyze_*
python3 tests/perf/run.py --json out.json
python3 tests/perf/fp_reduction.py              # 구조 조건이 걸러 내는 오탐 수
```

| 디렉터리 | 내용 |
|---|---|
| `tests/unit/` | 설정·스키마, `decide()` 전이 표, 원장 `apply()` 표, 저장소, 엔진 설치기, 버전 가드, miniyaml↔PyYAML |
| `tests/integration/` | 실제 훅 스크립트를 턴 단위로 구동 (검증 사이클, 원장 시나리오, 의미 판정, 자동 수정, 기각, CLI 계약, 린터 앵커링, 출력 형식, 패리티) |
| `tests/rules/` | 규칙 픽스처, 규칙 시나리오(`scenarios/`) |
| `tests/semantic/` | 컨텍스트 팩, 판정 캐시 키 |
| `tests/structure/` | 구조 정확도 사례(`cases/*.yaml`), 노드 대응표, 조건 평가, 결정성 |
| `tests/perf/` | 성능 하네스 (자동 실행 대상 아님) |
| `tests/skills/` | 스킬·에이전트 구조와 예시 검증, 스킬 평가 시나리오(`evals/`) |
| `tests/helpers/` | 임시 git 레포, 격리된 훅 세션 실행기, 픽스처 레포, 합성 코퍼스 |

## 규칙을 바꿀 때

1. `tests.no_match` 에 오탐 사례를 먼저 추가하고 실패를 확인
2. 규칙 수정
3. `.venv/bin/python tests/rules/test_rule_fixtures.py`
4. 앵커가 `when_line_added` 단독이 아니면 `tests/rules/scenarios/` 시나리오 추가·수정
5. `tests/integration/test_parity.py` — 결과가 바뀌었으면 의도한 변화인지 확인 후 `--update` 로 골든 갱신하고 **같은 커밋에** 포함
6. 새 core 규칙은 `presets/*.yaml` 에 추가 (안 하면 픽스처 테스트가 실패)

구조 조건이 있는 규칙의 픽스처는 **파서가 읽을 수 있는 완결된 코드**여야 합니다 (`} catch (...) {` 조각이 아니라 `try { … } catch …`, 메서드는 클래스 안에). PHP 조각에는 `<?php` 가 자동으로 붙습니다 (조각이 `<?` 로 시작하면 붙이지 않음).

## 엔진을 바꿀 때

- 패리티 골든(`tests/integration/golden/parity.json`)이 바뀌면 모든 사용자의 지적 결과가 바뀝니다. 골든 diff 를 커밋 메시지에서 설명하세요
- Stop 의 전이를 바꾸면 `tests/unit/test_decide.py` 에 행을 추가하고, 턴 단위 동작은 `test_hook_cycle.py` 에 시나리오로
- 원장(줄 출처)을 바꾸면 `tests/unit/test_ledger.py` 표와 `tests/integration/test_ledger_scenarios.py`
- `decide.py`·`batch.py`·`candidate.py` 는 외부와 닿는 모듈을 임포트하지 않습니다 (`test_decide.case_pure` 가 강제)
- 수집 훅(`collect.py`)은 매 도구 호출마다 돕니다. 원장 모듈 밖을 임포트하지 마세요

## 구조 엔진을 바꿀 때

- 노드 이름은 `scripts/lib/structure/nodes.py` 에만 둡니다 (`test_determinism` 이 강제)
- 문법 버전을 올리려면 `scripts/lib/engine/install.py` 의 `PINS` 를 고치고 `python3 scripts/engine.py lock` 으로 `lock.json` 을 다시 만든 뒤, `tests/structure/test_nodes.py`(대응표 이름이 문법에 있는지)와 `test_accuracy.py` 를 돌립니다
- 판정이 틀린 사례는 `tests/structure/cases/<언어>.yaml` 에 먼저 추가합니다

## 스킬과 에이전트를 바꿀 때

`tests/skills/test_skill_structure.py` 가 강제하는 것:

- `name`: 64자 이하 소문자·숫자·하이픈, 디렉터리명과 같음
- `description`: 1~1024자, XML 태그 없음, 무엇을 하는지 + "~할 때 사용합니다"
- SKILL.md 본문 500줄 미만, 참조 파일은 SKILL.md 에서 한 단계, 100줄 넘는 참조는 `## 목차`
- 스킬이 실행하라는 스크립트가 실제로 존재
- `rule-add/references/examples.md` 의 예시 규칙이 로드되고 자기 픽스처를 통과
- 스킬마다 평가 시나리오 3개 이상 (`tests/skills/evals/<스킬>.json`)

평가 시나리오는 자동 실행되지 않습니다. 스킬 안의 경로는 `${CLAUDE_PLUGIN_ROOT}` 로 씁니다.

## 줄바꿈과 실행

`.gitattributes` 가 텍스트 파일을 CRLF 로 체크아웃합니다. 그래서 스크립트는 항상 `python3 <경로>` 로 실행합니다 (shebang 직접 실행은 동작하지 않음). 생성·수정하는 파일(`dismissed.yaml`, AGENTS.md, 자동 수정 대상)은 원래 파일의 줄바꿈을 따릅니다.

## 릴리스

[design-4.0.md](design-4.0.md) §8.3 의 절차입니다.

1. `python3 scripts/engine.py ensure --dir .engine`
2. `.venv/bin/python tests/run_all.py` — 엔진 있음
3. `CONVENTION_GUARD_NO_ENGINE=1 .venv/bin/python tests/run_all.py` — 엔진 없음
4. 하한 인터프리터: `uv run --no-project --python 3.10 python scripts/engine.py ensure --dir .engine` 후 `uv run --no-project --python 3.10 --with pyyaml python tests/run_all.py`
5. `python3 scripts/engine.py verify-lock` — lock 의 모든 휠이 PyPI 와 같은지 (네트워크)
6. `python3 tests/perf/run.py` — 목표 값 기록
7. 실제 세션 점검: 임시 레포에서 `claude -p --plugin-dir <이 레포>` 로 위반 → 차단 → 수정 → 재검증 통과
8. `.claude-plugin/plugin.json` 과 `marketplace.json` 의 `version` 을 **둘 다** 올림. 커밋 제목은 `release: X.Y.Z — <한 줄>`
