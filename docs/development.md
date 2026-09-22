# 개발

## 목차
- 원칙
- 테스트
- 규칙을 바꿀 때
- 엔진을 바꿀 때
- 스킬과 에이전트를 바꿀 때
- 줄바꿈과 실행
- 릴리스

## 원칙

- 배포되는 실행 경로는 외부 의존성 0. PyYAML 이 있으면 쓰고, 없으면 `scripts/lib/miniyaml.py`
- Python 3.9 호환 (구문·표준 라이브러리)
- 훅은 절대 에이전트를 깨뜨리지 않습니다. 훅 스크립트는 자기 버그에도 종료 코드 0
- 결정은 `scripts/lib` 에, 진입점(`scripts/*.py`)은 인자·입출력만

## 테스트

테스트 전용 의존성(`hypothesis`, `coverage`)이 있어 가상환경을 씁니다. 최근 배포판은 시스템 파이썬에 바로 설치하는 것을 막습니다 (PEP 668).

```bash
python3 -m venv .venv                            # 최초 1회
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
```

활성화한 뒤에는 평소대로 돌립니다.

```bash
python3 tests/run_all.py                         # 전체 (tests/**/test_*.py 자동 탐색)
CONVENTION_GUARD_NO_PYYAML=1 python3 tests/run_all.py   # 내장 파서로 한 번 더
python3 tests/run_all.py --repo /path/to/repo   # 그 레포의 로컬 규칙 픽스처까지
```

활성화 없이 경로로 불러도 됩니다. 스크립트나 CI 에서는 이쪽이 안전합니다.

```bash
.venv/bin/python tests/run_all.py
```

`requirements-dev.txt` 는 **테스트 전용**입니다. 설치하지 않으면 속성 기반 테스트 스위트가 실패합니다 -- 건너뛰지 않습니다. 돌지 않은 속성이 통과한 속성처럼 보이면 안 되기 때문입니다. 배포되는 실행 경로(`scripts/**`, 훅, 스킬)는 이 패키지들을 임포트하지 않으므로 **사용자는 아무것도 설치하지 않습니다**.

커버리지는 `tests/run_all.py` 가 스위트를 서브프로세스로 띄우므로 병렬 모드가 필요합니다.

```bash
export COVERAGE_PROCESS_START=$PWD/.coveragerc COVERAGE_FILE=$PWD/.coverage
.venv/bin/python -m coverage run --parallel-mode tests/run_all.py
.venv/bin/python -m coverage combine
.venv/bin/python -m coverage report --include='*/lib/structure/*'
```

두 변수가 다 필요합니다. `COVERAGE_PROCESS_START` 가 없으면 자식이 측정을 시작하지
않고, `COVERAGE_FILE` 이 없으면 통합 테스트의 자식이 **임시 디렉터리**에 측정치를
남기고 사라집니다. 어느 쪽이든 숫자가 **조용히** 낮게 나옵니다 — U4 에서 63% 로
보이던 것이 실제로는 92% 였습니다.
브랜치가 바꾼 줄만 보려면:

```bash
.venv/bin/python -m coverage json -o coverage.json
.venv/bin/python tests/helpers/diff_coverage.py coverage.json --base <유닛 시작 커밋>
```

성능 하네스는 매 실행에 끼지 않습니다 (`tests/run_all.py` 는 `test_*.py` 만 모읍니다). 개발 의존성도 필요 없습니다.

```bash
python3 tests/perf/run.py --corpus both
```

| 디렉터리 | 내용 |
|---|---|
| `tests/unit/` | 설정·프리셋·오버라이드·스키마, PyYAML↔miniyaml 동등성 |
| `tests/integration/` | 실제 훅 스크립트를 턴 단위로 구동 (검증 사이클, 의미 판정, 자동 수정, 기각, 마이그레이션, CLI 계약, 린터 앵커링, 패리티) |
| `tests/rules/` | 규칙 픽스처, 규칙 시나리오(`scenarios/`) |
| `tests/semantic/` | 컨텍스트 팩 |
| `tests/structure/` | 구조 인식 계층 -- 마스킹·스코프·조건 평가·속성·결정성·이관 패리티 |
| `tests/perf/` | 성능 하네스 (자동 실행 대상 아님) |
| `tests/skills/` | 스킬·에이전트 구조와 예시 검증, 스킬 평가 시나리오(`evals/`) |
| `tests/helpers/` | 임시 git 레포, 격리된 환경의 훅 세션 실행기, 픽스처 레포 |

테스트는 pytest 없이 스크립트로 실행되고 종료 코드가 판정입니다. `helpers.isolated_env` 가 HOME·데이터 디렉터리를 격리하므로 이 머신의 사용자 규칙이나 캐시가 결과에 섞이지 않습니다.

## 규칙을 바꿀 때

1. `tests.no_match` 에 오탐 사례를 먼저 추가하고 실패를 확인
2. 규칙 수정
3. `python3 tests/rules/test_rule_fixtures.py`
4. 앵커가 `when_line_added` 단독이 아니면 `tests/rules/scenarios/` 시나리오 추가·수정
5. `python3 tests/integration/test_parity.py` — 결과가 바뀌었으면 의도한 변화인지 확인 후 `--update` 로 골든 갱신하고 **같은 커밋에** 포함
6. 새 core 규칙은 `presets/*.yaml` 에 추가 (안 하면 픽스처 테스트가 실패)

## 엔진을 바꿀 때

- 패리티 골든(`tests/integration/golden/parity.json`)이 바뀌면 모든 사용자의 지적 결과가 바뀝니다. 골든 diff 를 커밋 메시지에서 설명하세요
- Stop 훅 동작 변경은 `test_hook_cycle.py` 에 턴 시나리오로 추가
- 성능: 60개 파일 변경·후보 0건 Stop 훅이 ~60ms 수준입니다. 파일마다 git 프로세스를 띄우는 변경은 피하세요 (`gitdiff.diff_lines` 는 200개 단위 배치)

## 스킬과 에이전트를 바꿀 때

`tests/skills/test_skill_structure.py` 가 강제하는 것:

- `name`: 64자 이하 소문자·숫자·하이픈, 디렉터리명과 같음
- `description`: 1~1024자, XML 태그 없음, 무엇을 하는지 + "~할 때 사용합니다"
- SKILL.md 본문 500줄 미만, 참조 파일은 SKILL.md 에서 한 단계, 100줄 넘는 참조는 `## 목차`
- 스킬이 실행하라는 스크립트가 실제로 존재
- `rule-add/references/examples.md` 의 예시 규칙이 로드되고 자기 픽스처를 통과
- 스킬마다 평가 시나리오 3개 이상 (`tests/skills/evals/<스킬>.json`)

평가 시나리오는 자동 실행되지 않습니다. 스킬을 바꾸면 해당 시나리오를 Haiku·Sonnet·Opus 로 직접 돌려 `expected_behavior` 를 모두 만족하는지 확인하세요. 스킬 안의 경로는 `${CLAUDE_PLUGIN_ROOT}` 로 씁니다 (플러그인 로드 시 치환됨).

## 줄바꿈과 실행

`.gitattributes` 가 텍스트 파일을 CRLF 로 체크아웃합니다. 그래서 스크립트는 항상 `python3 <경로>` 로 실행합니다 (shebang 직접 실행은 macOS·Linux 에서 동작하지 않음). YAML 파서 둘 다 CRLF 를 처리하고, 생성·수정하는 파일(`dismissed.yaml`, AGENTS.md, 자동 수정 대상)은 원래 파일의 줄바꿈을 따릅니다.

## 릴리스

1. `python3 tests/run_all.py` 와 `CONVENTION_GUARD_NO_PYYAML=1` 실행 모두 통과
2. `.claude-plugin/plugin.json` 과 `marketplace.json` 의 `version`
3. 설정·규칙 형식이 바뀌었으면 `scripts/migrate.py` 와 `docs/migration-*.md`
4. 실제 세션 점검: 임시 레포에서 `claude --plugin-dir <이 레포>` 로 차단 → 수정 → 검증 통과, 의미 판정 요청 → 리뷰어 → 통과
