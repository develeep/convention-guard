---
name: convention-discover
description: 코드베이스 전체를 훑어 이 팀이 실제로 지키는 컨벤션을 찾아내고, 측정으로 검증한 것만 convention-guard 규칙으로 등록한 뒤 AGENTS.md / CLAUDE.md 로 세션 초반 컨텍스트에 주입합니다. "코드베이스 파악해서 컨벤션 만들어줘", "우리 레포 컨벤션 뽑아줘", "컨벤션 발굴", "코드베이스 분석해서 규칙 등록해줘", "지켜야 할 컨벤션 문서로 만들어줘", 규칙이 공통 규칙뿐이라 팀 관습이 하나도 안 담겼을 때 사용하세요.
---

# 코드베이스에서 컨벤션 발굴하기

`convention-setup` 은 **이 플러그인을 이 레포에 맞게 켜는** 일입니다. 이 스킬은
**이 레포의 컨벤션을 코드에서 캐내 규칙과 문서로 만드는** 일이고, 한 번 크게 도는
작업입니다. 셋업이 안 된 레포라면 `convention-setup` 을 먼저 돌리세요 — 여기서는
셋업을 다시 하지 않습니다.

세 가지 원칙이 이 스킬의 전부입니다.

1. **컨벤션은 인상이 아니라 숫자입니다.** "이 레포는 이렇게 쓰는 것 같다"는 규칙이
   될 수 없습니다. 세어보지 않은 관습을 규칙으로 만들면 남는 것은 오탐뿐입니다.
2. **살아있는 코드에서 캡니다.** 최근 6개월에 바뀐 파일이 현재의 컨벤션이고, 손대지
   않는 레거시는 표본이 아니라 노이즈입니다.
3. **발견은 세 갈래로 나갑니다.** 정규식으로 판정되는 것은 규칙으로, 판정은 못 하지만
   미리 알아야 하는 것은 컨텍스트로, 둘 다 안 되는 것은 문서로. 같은 컨벤션이 규칙과
   문서에 **중복돼도 괜찮습니다** — 중복 비용은 한 줄이고, 누락 비용은 되돌리는 작업입니다.

## 1. 전제 확인

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
```

스택이 비어 있거나 `.claude/convention-rules/config.yaml` 이 없으면 여기서 멈추고
`convention-setup` 을 먼저 돌리세요. 스택 감지가 틀린 상태로 측정하면 `applies_to.stack`
이 어긋나 후보가 전부 "해당 코드 없음" 으로 떨어집니다.

`--explain` 출력에서 이 스킬이 쓰는 것: **감지된 스택 태그**, **이미 켜져 있는 규칙
목록**(중복 발굴 방지), **린터·포맷터 유무**(린터가 잡는 것은 규칙으로 만들지 않습니다).

## 2. 코드베이스를 볼 수 있게 만들기

전체를 다 읽는 것은 불가능하고 필요도 없습니다. **구조를 먼저 얻고, 슬라이스별 대표
파일만 읽습니다.**

### (a) 지식 그래프가 붙어 있으면 그걸 씁니다

`codebase-memory` 류의 코드 지식 그래프 MCP(`list_projects`, `index_repository`,
`get_architecture`, `search_graph`, `trace_path`)가 있으면 파일 200개를 읽는 대신
질의로 구조를 받으세요. 인덱스가 없으면 `index_repository` 부터.

| 알아낼 것 | 질의 |
|---|---|
| 레이어·패키지 경계 | `get_architecture` |
| 엔트리포인트 (라우트·핸들러·커맨드) | `search_graph(label=..., name_pattern=".*(Controller\|Handler\|Command).*")` |
| **팀이 쓰는 표준 도구** | `search_graph(min_degree=10, relationship="CALLS", direction="inbound")` — 팬인 높은 헬퍼가 곧 컨벤션입니다 |
| 계층 위반 | `trace_path(direction="both")` 로 의존 방향 확인 |
| 죽은 구역 | `search_graph(max_degree=0)` — 여기서 뽑은 관습은 표본에서 빼세요 |

### (b) 없으면 git 으로 셉니다

```bash
git ls-files | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn | head -40      # 디렉터리 분포
git ls-files | awk -F. 'NF>1 {print $NF}' | sort | uniq -c | sort -rn | head -15  # 확장자 분포
git log --since=6.months --format= --name-only | sort | uniq -c | sort -rn | head -40  # 살아있는 파일
git ls-files '*test*' '*spec*' '*_test.go' | head -20                        # 테스트 위치
```

세 번째가 가장 값어치 있습니다. **자주 바뀌는 파일이 지금의 컨벤션**이고, 여기서
안 걸리는 디렉터리는 레거시로 취급해 측정에서 제외할 후보입니다.

### (c) 읽는 것은 슬라이스당 대표 3~5개

슬라이스 = 레이어 × 스택. 예: 컨트롤러 / 서비스·유스케이스 / 모델·엔티티 / 라우트 /
마이그레이션 / 테스트 / 프런트 컴포넌트 / 훅·스토어 / 설정. 슬라이스가 5개를 넘으면
`Task` 서브에이전트로 **병렬 분할**하고, 보고 형식을 고정하세요.

```
슬라이스: app/Http/Controllers
관습: 컨트롤러는 조회를 서비스에 위임한다
위반 정규식: \b[A-Z]\w+::(where|find|create)\s*\(
정상 정규식: \$this->\w*(service|repository)\w*->
대상 글롭: app/Http/Controllers/**/*.php
근거: app/Http/Controllers/OrderController.php:22, .../UserController.php:15, .../CartController.php:31
```

두 가지를 지키게 하세요.

- **3개 이상의 파일에서 반복되지 않으면 보고 금지.** 한두 건은 컨벤션이 아니라 우연입니다.
- **서브에이전트에게 규칙 파일을 쓰게 하지 마세요.** 측정 전에 규칙이 생기면 그게
  오탐의 출처입니다. 서브에이전트의 산출물은 "가설 + 정규식 + 근거 경로"까지입니다.

### (d) 지도를 파일로 남깁니다

`<repo>/.claude/convention-rules/codebase-map.md`

```markdown
# 코드베이스 지도 (convention-discover, YYYY-MM-DD)
## 소스 루트와 레이어
## 의존 방향 (무엇이 무엇을 부르는가 / 부르면 안 되는가)
## 엔트리포인트
## 공용 헬퍼 — 팀이 실제로 쓰는 표준 도구
## 테스트 위치와 명명
## 레거시·생성 코드 구역 (측정에서 제외한 곳과 그 이유)
## 읽은 대표 파일
```

이 경로는 규칙 로더가 `.yaml` 만 읽기 때문에 규칙으로 잡히지 않고, 스캔 대상에서도
제외되는 경로라 훅이 자기 문서를 지적하지 않습니다. 다음 실행의 기준점이자 팀
리뷰 대상이므로 커밋하세요. **추측은 적지 말고 확인한 것만 적으세요.**

## 3. 관습을 숫자로 바꾸기 — 여기가 게이트입니다

후보 파일을 쓰기 전에 가설 하나씩 즉석 측정합니다. 아무것도 쓰지 않고 훅과 같은
엔진·같은 판정으로 준수율만 냅니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" \
  --probe '\b[A-Z]\w+::(where|find|create)\s*\(' \
  --conforming '\$this->\w*(service|repository)\w*->' \
  --files 'app/Http/Controllers/**/*.php'
```

`--kind file`(여러 줄 패턴), `--flags i`, `--exclude 'legacy/**'`, `--examples 20` 을
쓸 수 있습니다.

| 판정 | 준수율 | 할 일 |
|---|---|---|
| 이미 100% 준수 | 위반 0, 준수 ≥3 | 회귀 방지용. `error` 로 켜도 안전합니다 |
| 추천 | ≥80% | 후보 파일로 승격. `warn` 으로 채택 |
| 합의 필요 | 30~80% | **규칙 금지.** 팀이 갈려 있다고 보고하고 합의를 먼저 |
| 표본 부족 | 해당 파일 3개 미만 | 글롭이 틀렸는지 먼저 보고, 맞다면 보류 |
| 반대 관습 | <30% | 정규식의 방향이 뒤집혔거나, 레포가 반대로 씁니다. 버리세요 |
| 해당 코드 없음 | 0 / 0 | 정규식이 아무것도 못 잡았습니다. 근거 파일로 다시 확인 |

**위반 예시를 열어보기 전에 다음 단계로 가지 마세요.** 준수율 92%인데 위반 예시가
전부 오탐이면 그 규칙은 100% 오탐입니다 — 준수율이 높아 보이는 건 정규식이 아무것도
제대로 안 잡았다는 뜻일 수 있습니다.

위반이 특정 디렉터리에 몰려 있으면 규칙 문제가 아니라 **그 구역이 레거시**입니다.
`--exclude` 를 붙여 다시 재고, 통과하면 그 exclude 를 후보의 `applies_to.exclude` 로
그대로 옮기세요.

카탈로그 후보도 같이 재세요. 이미 검증된 후보 22개가 붙어 있고, 직접 만든 정규식보다
오탐이 적습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" --all-verdicts
```

## 4. 규칙으로 등록

측정을 통과한 가설만 후보 파일로 씁니다.

```
<repo>/.claude/convention-rules/candidates/<id>.yaml
```

형식은 `${CLAUDE_PLUGIN_ROOT}/candidates/README.md`. `probe.conforming` 과 `tests`
픽스처가 필수입니다. 즉석 측정을 통과했어도 **후보 파일을 거치는 이유**는, 그래야
측정이 재현되고 다음 사람이 같은 숫자를 다시 볼 수 있기 때문입니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py"                     # 후보가 판정과 함께 뜬다
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" \
  --adopt local-candidate/<id1> local-candidate/<id2> --severity warn
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_rules.py" --repo "$CLAUDE_PROJECT_DIR"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --rule local/ --no-color
```

- 강도는 **첫 사이클에는 `warn` 만.** "이미 100% 준수" 만 `error` 후보이고, 그것도
  전수조사 건수가 0인지 확인한 뒤에.
- 판정과 위반 예시를 보여주고 `AskUserQuestion` 으로 고르게 하세요. 사용자가 "다
  등록해" 라고 했으면 **추천 이상만** 채택하고, "합의 필요" 는 목록으로 따로 보고합니다.
- 마지막 명령의 건수가 예상보다 많으면 그 규칙은 아직 `warn` 입니다. 숫자로 보고하세요.
- 채택 출력에 **`판정: 측정 없음`** 이 찍히면 멈추세요. 그 후보는 스택 게이트에 걸려
  이 레포에서 측정되지 않았다는 뜻입니다 (예: `tsconfig.json` 이 없어 `ts` 태그가
  안 붙은 레포에 TypeScript 후보를 채택). 규칙 파일은 생기지만 훅에서도, 컨텍스트
  주입에서도 같은 게이트에 걸려 아무 일도 하지 않습니다. 1번으로 돌아가세요.

## 5. 정규식으로 못 잡는 컨벤션

발굴한 것 중 절반쯤은 정규식으로 판정되지 않습니다. 광범위한 정규식으로 억지로
규칙을 만들지 마세요 — 레거시가 전부 걸려 일주일이면 규칙이 꺼집니다.

| 성격 | 어디로 |
|---|---|
| 게이트는 되지만 판정은 의미를 봐야 함 (N+1, 계층 경계) | `semantic` 규칙 (`rule-add` 6번). `agent` 훅을 켠 팀에서만 동작합니다 |
| 네이밍 철학, 폴더 구조, 에러 처리 전략, 의존 방향 | 문서로 (6번의 관리 블록 **밖**) |
| 포맷·import 순서·미사용 변수 | 규칙이 아니라 린터 설정 (`presets/`) |

## 6. 세션 초반 컨텍스트에 주입

훅은 **쓰고 난 뒤** 잡습니다. 발굴한 컨벤션은 **쓰기 전에** 알아야 값어치가 있으므로,
훅과 중복되더라도 채택한 것을 전부 넣습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --agents-md --include local --budget 0 --stdout
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --agents-md --include local --budget 0
```

| `--include` | 넣는 것 | 언제 |
|---|---|---|
| `preventive` (기본) | `semantic` + `in_context: true` | 평소 재생성 |
| `local` | 위 + **이 레포에서 채택한 규칙 전부** | 이 스킬의 기본값 |
| `all` | 적용되는 모든 규칙 | 팀이 공통 규칙조차 처음 볼 때만 |

`--budget 0` 은 그룹당 상한을 해제합니다. 본문은 `AGENTS.md` 에 들어가고 `CLAUDE.md`
에는 `@AGENTS.md` import 한 줄만 생깁니다.

그다음 **관리 블록 밖**(사람 소유, 재생성해도 보존)에 5번에서 문서로 보낸 것을 씁니다.

```markdown
## 이 코드베이스의 컨벤션
<!-- 측정 근거: .claude/convention-rules/codebase-map.md -->

### 레이어와 의존 방향
- HTTP 계층은 서비스만 부릅니다. 컨트롤러에서 모델·리포지터리 직접 호출 없음 (47/50 파일).
### 네이밍
### 에러 처리
### 하지 말 것
```

- **괄호 안 숫자를 남기세요.** 근거 없는 문장은 6개월 뒤 아무도 못 지웁니다.
- 관리 블록이 이미 갖고 있는 규칙을 손으로 또 적지 마세요. 여기 적을 것은 **정규식이
  못 잡는 것만**입니다.
- 200줄 아래로. 넘치면 경로별 상세는 `.claude/rules/` 로 보내세요.

경로 스코핑이 필요하면 파일 모드도 같이 생성합니다. `paths:` 프론트매터가 붙어 **그
파일을 읽을 때만** 컨텍스트에 들어가므로, AGENTS.md 와 중복돼도 비용이 거의 없습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --include local --budget 0
```

다른 출력 형태가 필요한 팀도 있습니다. 같은 `--include` 를 그대로 받습니다.

| 상황 | 명령 |
|---|---|
| Claude Code 만 쓰고 `AGENTS.md` 를 두고 싶지 않다 | `--claude-md --include local --budget 0` |
| 파일을 커밋하지 않고 항상 최신 규칙을 주입 | `--hook --include local --budget 0` (SessionStart 훅) |

훅 방식은 드리프트가 없는 대신 PR 에서 보이지 않습니다. 팀원 리뷰와 플러그인 없는
사람을 생각하면 파일 방식이 거의 항상 낫습니다.

## 7. 검증하고 보고

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain                          # 채택 규칙이 로드되는지
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_rules.py" --repo "$CLAUDE_PROJECT_DIR"  # 픽스처
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --range HEAD~20..HEAD --severity error --no-color
```

마지막 명령이 이 작업의 진짜 시험입니다. **최근 20커밋에 error 가 20건 넘게 나오면
너무 많이 켠 것입니다.** 강도를 내리거나 레거시 경로를 제외하세요.

보고는 다섯 줄로.

1. 조사 범위 — 슬라이스 n개, 대표 파일 m개, 조사한 추적 파일 수
2. 발견 관습 N개 중 측정 통과 M개 (탈락 사유별 한 줄)
3. 채택한 규칙 id 와 강도, 그리고 왜 그 강도인지
4. 최근 20커밋 기준 남는 건수
5. 생성·갱신한 파일 경로 (`codebase-map.md`, 후보, 규칙, `AGENTS.md`, `CLAUDE.md`)

## 다시 돌릴 때

분기마다 또는 큰 리팩터 직후. 후보 파일이 레포에 남아 있으므로 그때는 `survey.py`
한 번으로 준수율 변화만 봅니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" --all-verdicts
```

준수율이 떨어진 규칙은 **컨벤션이 바뀐 신호**입니다. 규칙을 고칠지 코드를 고칠지는
사용자가 결정할 일이니, 숫자와 함께 물어보세요. 수정률·기각 데이터로 승격을 볼
차례라면 `rule-tune` 으로 넘기세요.

## 하지 말 것

- 측정 없이 규칙 만들기. 이 스킬의 존재 이유가 그것입니다
- 추천 목록 전량 채택, 첫 사이클에 `error` 승격
- 레거시·생성 코드를 표본에 포함한 채로 측정
- 서브에이전트에게 규칙·후보 파일을 쓰게 하기
- 훅이 이미 잡는 것을 `AGENTS.md` 에 손으로 복사 (생성기가 관리 블록에 넣습니다)
- 린터가 결정론적으로 잡는 것(포맷·import 순서)을 규칙으로 만들기
