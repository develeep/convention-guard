# 스킬

[README](../../../README.md) · **한국어** · [English](../en/skills.md)

훅은 혼자서 돕니다. 스킬은 도입·검사·규칙 관리처럼 **사람이 시작하는 일**을 에이전트가 대신하게 합니다. 스킬마다 스크립트를 부르고 결과를 판단해 보고하는 절차가 들어 있습니다.

## 목차
- 부르는 법
- 언제 무엇을 쓰나
- convention-setup — 도입
- convention-check — 지금 검사
- convention-readiness — 도입 점검
- convention-discover — 컨벤션 발굴
- rule-add — 규칙 만들기
- rule-tune — 규칙 손보기
- convention-reviewer 에이전트

## 부르는 법

평소 말로 요청하면 Claude Code 가 설명에 맞는 스킬을 고릅니다.

```
convention-guard 세팅해줘
PR 올리기 전에 컨벤션 검사해줘
```

이름으로 직접 부를 수도 있습니다. 플러그인 스킬은 `convention-guard:` 접두사가 붙습니다.

```
/convention-guard:convention-setup
/convention-guard:convention-check --staged 만 봐줘
```

## 언제 무엇을 쓰나

도입부터 운영까지 대략 이 순서로 씁니다.

```
convention-setup ─→ convention-readiness ─→ (2~3주 report 모드) ─→ rule-tune ─→ mode: fix
                                                    │
        convention-discover ─→ rule-add ←───────────┘  필요한 규칙이 보이면
convention-check: 언제든 (커밋·PR 직전, 브랜치 점검)
```

| 스킬 | 이럴 때 | 말하는 예 |
|---|---|---|
| `convention-setup` | 레포에 처음 도입, 설정을 처음부터 다시 | "convention-guard 세팅해줘" |
| `convention-check` | 훅을 기다리지 않고 지금 검사 | "커밋 전에 컨벤션 검사해줘" |
| `convention-readiness` | 팀 레포에 켜기 전, 업데이트 직후, `fix` 로 올리기 전 | "도입 점검해줘" |
| `convention-discover` | 팀의 기존 컨벤션을 찾아 규칙 후보로 | "우리 컨벤션 찾아서 규칙 뽑아줘" |
| `rule-add` | 반복되는 리뷰 지적을 규칙으로 | "이 패턴 규칙으로 만들어줘" |
| `rule-tune` | 로그가 쌓인 뒤 오탐 정리, 승격, 모드 전환 | "규칙 정리해줘" |

## convention-setup — 도입

레포에 convention-guard 를 **처음부터** 셋업합니다. 기존 `config.yaml` 이 있으면 덮어써도 되는지 한 번 묻고, 아니라고 하면 멈춥니다 (기존 설정 조정은 `rule-tune` 소관).

목표는 규칙을 많이 켜는 것이 아니라 **걸리는 것이 전부 진짜이게** 만드는 것입니다.

1. **감지**: 스택·프리셋·적용 규칙·린터를 확인합니다 (`detect_stack.py`). 마커 파일(`composer.json`, `package.json`, `pyproject.toml`, `requirements.txt` 등)이 루트에 없으면 `stacks:` 를 직접 지정합니다.
2. **초안**: `.claude/convention-guard/config.yaml` 을 `mode: report` 로 씁니다 (`setup.py init`).
3. **측정 → 조정**: 최근 20커밋과 레포 전체에서 실제로 몇 건이 걸리는지 재고, 많이 걸리는 규칙은 `severity` 를 낮추고 레거시 구역은 `exclude` 로 뺍니다. 남은 지적이 진짜 위반일 때까지 반복합니다.
4. **내보내기**: 적용되는 규칙 전부와 린터 명령을 `AGENTS.md` 관리 블록으로 씁니다 (`setup.py emit --agents-md`). 에이전트가 쓰기 전에 알면 차단이 줄어듭니다. 관리 블록 밖의 내용은 보존되고, `CLAUDE.md` 에 `@AGENTS.md` 가져오기가 추가됩니다.
5. **보고**: 스택, 적용 규칙 수, 조정 내역, 남는 지적 수.

결과로 생기는 `.claude/convention-guard/config.yaml` 과 `AGENTS.md` 는 커밋 대상입니다. 도입 첫 2~3주는 `report` 로 기록만 쌓고, 그다음 `rule-tune` 으로 `fix` 전환을 판단합니다.

## convention-check — 지금 검사

Stop 훅과 **같은 파이프라인**으로 지금 검사하고, 후보를 직접 열어 위반인지 판정한 뒤 확정된 위반만 보고합니다. 요청하면 고치고 다시 검사합니다.

| 요청 | 범위 |
|---|---|
| (기본) 지금 바뀐 것 | 워킹 트리 |
| 커밋 직전 | `--staged` |
| PR 올리기 전, 브랜치 전체 | `--base-ref auto` (기본 브랜치와의 merge-base 이후 전부) |
| 이 파일 | `--files <경로>` |
| 레거시 규모, 도입 전 감사 | `--all` (명시적으로 요청했을 때만) |

- 정규식이 좁힌 결과는 **후보**입니다. 스킬이 위치를 열어 규칙의 안내에 비춰 판정합니다. 린터 실패는 확정 위반으로 맨 앞에 둡니다.
- 의미 판정 후보가 있으면 `--review` 로 다시 돌려 판정 배치를 만들고 `convention-reviewer` 에이전트에게 맡깁니다. 돌아온 `VIOLATION` 만 위반으로 보고합니다.
- 오탐은 말로 넘기지 않고 `dismiss.py` 로 기각을 기록합니다. 그래야 `rule-tune` 이 오탐과 "안 고침"을 구분합니다.
- 고칠 때는 error 부터 규칙 하나씩, 고칠 때마다 같은 범위로 다시 검사합니다. 자동 수정이 있는 규칙은 `--fix --write` 로 먼저 적용할 수 있습니다.

옵션 전체: [cli.md 의 scan.py](cli.md#scanpy--수동-검사)

## convention-readiness — 도입 점검

팀 레포에 실제로 켜도 되는지 [도입 체크리스트](production-readiness.md) 전 항목을 점검합니다. 판정은 `readiness.py` 가 하고, 스킬은 fail·warn 을 고칠 방법과 사람이 확인할 항목을 정리합니다.

- Python, 설치 범위, 훅 배선, userConfig, 설정 계층, 개인 규칙, 기각 기록, 규칙 픽스처와 도달 범위, 탐지량, 성능, 보안, CI 를 판정합니다.
- 차단·재검증·의미 판정·장애 모드는 플러그인 자체 테스트를 임시 데이터 디렉터리의 샌드박스에서 돌려 확인합니다. 레포와 훅의 로그는 건드리지 않습니다.
- `.claude/settings.json`, 개인 `pluginConfigs`, 팀 `config.yaml` 처럼 영향이 큰 수정은 **사용자에게 물은 뒤에만** 고칩니다.
- 판정: fail 1건 이상 → 도입 불가 / warn 만 → 조건부 / pass 만 → 도입 가능. `? manual`·`○ skip` 은 확인되지 않은 것으로 따로 보고합니다.

Claude Code 세션을 여는 디렉터리에서 실행하세요. 프로젝트·로컬 설정은 그 디렉터리 기준으로 읽습니다.

## convention-discover — 컨벤션 발굴

팀이 이미 가진 컨벤션을 찾아 **후보표와 근거**를 만듭니다. 규칙 파일은 쓰지 않고, 사용자가 고른 항목만 `rule-add` 로 넘깁니다.

1. **명시된 것**: `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`, `.github/copilot-instructions.md`, `CONTRIBUTING.md`, `docs/` 의 컨벤션 문서, 린터 설정, 최근 머지된 PR 의 리뷰 코멘트(`gh` 사용).
2. **코드에 숨은 것**: 최근 6개월에 자주 바뀐 파일에서 표본을 읽어 반복되는 구조를 찾습니다.
3. **분류**: 린터·포맷터 소관 / 결정론 규칙 / 의미 판정 규칙 / 지침 전용 / 이미 적용 중.
4. **측정**: 결정론 규칙은 실제 준수율(정상 ÷ (정상 + 위반))을 세고, 의미 판정 규칙은 게이트가 잡는 후보 수와 표본 판정을 봅니다. 준수율 80% 이상이면 추천, 30% 미만이면 반대 관습이라 규칙으로 만들지 않습니다.

컨벤션은 인상이 아니라 숫자입니다. 세어 보지 않은 관습을 규칙으로 만들면 오탐만 남습니다.

## rule-add — 규칙 만들기

반복되는 지적이나 컨벤션 항목을 규칙 파일로 만들고 오탐을 검증합니다.

1. **가치 판단**: 포맷·import 순서는 린터·포맷터로, 타입 추론은 phpstan/tsc/mypy 로 보냅니다. 이런 것은 규칙으로 만들지 않습니다.
2. **위치와 강도**: 이 레포 전용이면 `.claude/convention-guard/rules/<id>.yaml`, core 규칙을 바꾸는 것이면 `override: core/<id>` 파일. 새 규칙은 `warn` 으로 시작합니다.
3. **앵커 고르기**: 무엇이 "이번 변경의 책임"인지 정합니다. 잘못 고르면 레거시가 전부 걸립니다 ([rules.md 앵커](rules.md#앵커-무엇이-이번-변경의-책임인가)).
4. **사례 찾기**: 레포에서 위반 사례와 헷갈리는 정상 사례를 둘 다 찾아 `tests.match`·`tests.no_match` 로 씁니다.
5. **검증 루프**: 픽스처 테스트 → 레포 전수조사 → 결과 몇 곳을 직접 열어 확인 → 정상 코드가 걸렸으면 `no_match` 에 넣고 정규식을 좁힙니다.
6. **컨텍스트 재생성**: `setup.py emit` 으로 AGENTS.md 를 다시 씁니다.

정규식으로 판정할 수 없는 규칙(N+1, 계층 경계)은 `semantic_review` 규칙으로 만듭니다 ([semantic-review.md](semantic-review.md#규칙-작성)).

## rule-tune — 규칙 손보기

발동 로그(`log_report.py`)로 규칙 건강도를 보고, 오탐 규칙은 좁히거나 끄고, 건강한 규칙은 승격하며, `report` → `fix` 전환을 판단합니다. 도입 2~3주 뒤, 지적이 너무 많거나 에이전트가 무시하는 것 같을 때 씁니다. 로그가 아직 없으면 `convention-setup` 을 먼저 합니다.

| 지표 | 뜻 |
|---|---|
| 수정률 | 고침 ÷ (고침 + 남음) |
| 기각 | 오탐으로 기록된 수 — 오탐의 직접 증거 |
| 새로 생김 | 다른 지적을 고치다가 이 규칙을 새로 어긴 수 |
| 정밀도 | 의미 판정 규칙에서 리뷰어가 `VIOLATION` 으로 판정한 비율 |

| 조치 | 조건 |
|---|---|
| warn → error 승격 | 수정률 70% 이상, 고침+남음 10건 이상, 기각 사유가 반복되지 않음 |
| error → warn 강등 | 오탐이 남아 있는데 작업을 막고 있음 |
| 끄기 (`disable`) | 팀이 동의하지 않음 — 사용자 확인 후 |
| `mode: report` → `fix` | 차단 강도 규칙이 모두 건강하거나 데이터 부족 |

조건을 좁힐 때는 **픽스처를 먼저** 고칩니다. 오탐이었던 실제 코드를 `tests.no_match` 에 넣어 실패를 확인한 뒤 정규식을 좁힙니다. 순서를 바꾸면 같은 오탐이 돌아옵니다.

## convention-reviewer 에이전트

스킬이 아니라 서브에이전트입니다. Stop 훅이나 `scan.py --review` 의 출력에 `convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 …` 와 `review.py show <배치>` 명령이 나오면 메인 에이전트가 부릅니다. 직접 부를 일은 거의 없습니다.

- 판정 배치(`review.py show <배치>`)를 읽고 후보마다 `VIOLATION`·`VALID`·`FALSE_POSITIVE` 를 기록합니다 (`review.py record`).
- 코드를 고치지 않습니다 (Write·Edit 도구 없음). 기본 모델은 haiku 입니다.
- 메인 에이전트에게는 위반만 한 줄씩 돌려줍니다. 읽은 코드와 판단 과정은 서브에이전트 안에서 끝납니다.

자세히: [semantic-review.md](semantic-review.md)
