---
name: convention-setup
description: 이 레포에 맞는 convention-guard 설정을 만듭니다. 레포 구조·스택·린터·레거시 규모를 실제로 훑어보고, 전수조사로 이 레포가 이미 지키는 컨벤션을 찾아 규칙을 추천하고, config.yaml 과 AGENTS.md 를 씁니다. "컨벤션 설정해줘", "이 레포에 규칙 붙여줘", "convention-guard 세팅", "우리 프로젝트 컨벤션 규칙 추천해줘", "AGENTS.md 만들어줘", 새 레포에 도입할 때 사용하세요.
---

# 레포에 맞는 컨벤션 설정 만들기

기본값으로 켜면 레거시가 많은 레포에서는 지적이 쏟아지고, 일주일 만에 꺼집니다.
**도입 첫날의 목표는 규칙을 많이 켜는 게 아니라, 걸리는 것이 전부 진짜이게 만드는 것**입니다.
그래야 에이전트가 reason 을 진지하게 읽습니다.

## 1. 현재 상태 파악 (추측하지 말고 실행할 것)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
```

감지된 스택, 적용 규칙, 린터가 나옵니다. 스택이 비어 있으면 마커 파일
(`composer.json` / `package.json` / `go.mod`)이 레포 루트에 있는지 확인하세요.
모노레포라 루트에 없다면 `stacks:` 로 강제 지정해야 합니다.

## 2. 레포 구조 훑기

`Glob` 과 `Read` 로 직접 확인하세요. 아래를 알아내는 것이 목적입니다.

- **소스 루트**: `app/`, `src/`, `internal/`, `packages/*` 중 무엇인가
- **레거시 구역**: 손대지 않기로 한 디렉터리가 있는가 (`legacy/`, `app/Old*`, 벤더 포크 등)
- **생성 코드**: 마이그레이션, 프로토버프 산출물, `*.generated.*` — 규칙을 걸면 안 되는 곳
- **테스트 위치**: `tests/`, `__tests__/`, `*_test.go` — paired 규칙을 쓸 수 있는지 판단용
- **포맷터**: `pint.json`, `.php-cs-fixer*`, `.eslintrc*`, `biome.json`, `.golangci.yml`

포맷터 설정이 없는데 포맷 규칙이 켜져 있으면 지적이 많아집니다. 포맷터를 먼저
도입하도록 권하는 편이 거의 항상 낫습니다 (`presets/php/pint.json` 참고).

## 3. 실제로 얼마나 걸리는지 측정

**이 단계를 건너뛰지 마세요.** 설정을 추측으로 쓰면 반드시 빗나갑니다.

```bash
# 최근 작업 분량에 대해 몇 건이나 걸리는지
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --range HEAD~20..HEAD --no-color

# 레포 전체 레거시 규모 (결과가 많을 수 있음)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --severity error --no-color
```

읽는 법:

- 최근 20커밋에 **error 가 20건 넘게** 나오면 그 규칙들은 이 레포에서 아직 `error` 가
  아닙니다. `warn` 으로 내리거나 해당 디렉터리를 `exclude` 하세요.
- 특정 파일·디렉터리에 지적이 몰리면 그건 규칙 문제가 아니라 **그 구역이 레거시**라는
  신호입니다. 규칙을 끄지 말고 경로를 제외하세요.
- 전수조사에서만 나오고 최근 변경에서는 안 나오면 그대로 두세요. 앵커가 제 일을 하는 중입니다.

## 4. 린터 출력이 이번 변경에 앵커되는지 확인

린터 실패는 파싱된 `file:line` 이 **이번 변경이 추가한 줄**과 겹칠 때만 차단합니다.
나머지는 차단하지 않고 "참고"로만 전달됩니다. 파싱이 불가능하거나 실패하면 예전처럼
출력 전체로 차단합니다 — 진짜 실패를 조용히 버리는 게 더 나쁘기 때문입니다.

**레포에 린터가 있는데 `parse:` 가 없으면 남의 레거시 에러까지 이번 턴을 막습니다.**
도입 첫 주에 규칙이 꺼지는 전형적인 경로입니다. `--explain` 으로 먼저 확인하세요.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
```

린터마다 `[parse: unix → 변경 줄만 차단]` 또는 `[출력 파싱 불가 → 전체 출력으로 차단]` 이
찍힙니다. 후자가 보이면 `stacks/*.yaml` 의 해당 lint 항목에 `parse:` 를 지정하세요.

| parse | 맞춰야 할 출력 |
|---|---|
| `eslint-json` | `eslint --format=json` |
| `phpstan-json` | `phpstan --error-format=json` |
| `golangci-json` | `golangci-lint --out-format=json` |
| `unix` | `file:line:col: message` (go vet, golangci 기본, phpstan `--error-format=raw`) |
| `github` | `::error file=...,line=...` (biome `--reporter=github`) |
| `diff` | 유니파이드 diff (`pint --test -v`, `php-cs-fixer --diff`) |

명령에는 `{files}`(변경 파일 목록) 또는 `{dirs}`(그 파일들의 패키지 디렉터리)를 씁니다.
패키지 단위로만 도는 도구는 `{dirs}` 여야 합니다 — `go vet ./...` 는 매 턴 모듈 전체를
다시 컴파일하고 남의 에러까지 끌고 옵니다.

## 5. config.yaml 쓰기

`<repo>/.claude/convention-rules/config.yaml`

```yaml
# 이 레포에서 끌 규칙 — 왜 끄는지 주석을 반드시 남길 것
disable:
  - core/js-no-console      # 디버그 로그를 관례적으로 커밋하는 레포

# 강도 조정 — 끄는 것보다 내리는 편이 거의 항상 낫습니다
severity:
  core/php-line-too-long: info

# 레거시·생성 코드 제외
exclude:
  - "legacy/**"
  - "**/*.generated.*"
  - "database/migrations/**"

max_rules: 3
max_consecutive_blocks: 3   # 연속 차단 상한. 한 번 통과하면 초기화됩니다
base_ref: auto      # 세션 중 커밋한 변경까지 검사하려면
```

`stacks:` 는 **적지 마세요.** 감지 결과를 기록하는 칸이 아니라, 감지가 빗나갔을 때만
쓰는 강제 지정 입력입니다. 미리 박아두면 나중에 Laravel 을 올리거나 TypeScript 를 추가했을 때
굳어버린 목록이 실제와 어긋납니다. `--explain` 의 스택이 맞으면 그걸로 된 것입니다.

원칙 두 가지:

- **`disable` 보다 `exclude` 와 `severity` 를 먼저 쓰세요.** 규칙을 끄면 팀 표준에서
  영구히 이탈하지만, 경로 제외와 강도 조정은 되돌리기 쉽습니다.
- **`disable` 에는 이유를 주석으로 남기세요.** 6개월 뒤 왜 껐는지 아무도 기억 못 합니다.

## 5-1. 이 레포가 이미 지키는 컨벤션 찾기 (규칙 추천)

사용자가 "규칙도 추천해줘" 라고 하거나, 공통 규칙만으로는 팀 컨벤션이 덜 담긴다고
판단되면 이 단계를 하세요. **규칙 추천은 새 규칙을 발명하는 게 아니라, 이 레포가 이미
지키고 있는 것을 굳히는 일**입니다. 92%가 한 방향으로 쓰고 있으면 그건 컨벤션이고 남은
8%는 회귀입니다. 50:50이면 컨벤션이 아니라 취향 차이이고, 그걸 규칙으로 만들면 오탐으로만
보입니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py"                 # 추천 목록
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" --all-verdicts  # 탈락한 것까지
```

후보마다 준수/위반 파일 수, 준수율, 판정, 실제 위반 예시가 나옵니다.

| 판정 | 뜻 | 권하는 것 |
|---|---|---|
| 이미 100% 준수 | 위반 0건 | 회귀 방지용. `error` 로 켜도 안전합니다 |
| 추천 | 준수율 ≥80% | `warn` 으로 채택. 위반 몇 건은 `exclude` 하거나 그때그때 고치기 |
| 합의 필요 | 30~80% | **채택하지 마세요.** 사용자에게 "팀이 갈려 있다"고 알리고 합의를 먼저 |
| 표본 부족 | 해당 파일 3개 미만 | 판단 보류. 코드가 더 쌓인 뒤 다시 재세요 |
| 반대 관습 | <30% | 이 레포는 반대로 씁니다. 채택하면 안 됩니다 |
| 공통 규칙이 이미 덮음 / 이미 채택됨 | — | 할 일 없음 |

**목록을 그대로 다 채택하지 마세요.** 판정과 위반 예시를 사용자에게 보여주고,
`AskUserQuestion` 으로 무엇을 켤지 고르게 하세요. 도입 첫날에는 3~5개면 충분합니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/survey.py" \
  --adopt candidate/<id1> candidate/<id2> --severity warn
```

채택하면 후보 파일이 `<repo>/.claude/convention-rules/<id>.yaml` 로 복사되고
(`local/` 네임스페이스), 픽스처도 함께 따라옵니다. 바로 검증하세요.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_rules.py" --repo "$CLAUDE_PROJECT_DIR"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --rule local/ --no-color
```

전수조사 건수가 예상보다 많으면 그 규칙은 아직 `warn` 입니다. 사용자에게 몇 건인지
숫자로 보고하세요.

### 카탈로그에 없는 이 레포만의 컨벤션

`survey.py` 는 플러그인 카탈로그(`candidates/**`)를 잽니다. 레포를 훑다가 카탈로그에
없는 관습을 발견했다면 — 사내 네이밍, 자체 헬퍼 사용법, 팀 전용 에러 처리 —
후보 파일을 직접 써서 같은 방식으로 **측정한 뒤에만** 제안하세요.

```
<repo>/.claude/convention-rules/candidates/<id>.yaml
```

형식은 `${CLAUDE_PLUGIN_ROOT}/candidates/README.md` 에 있습니다. `probe.conforming`
(정상 패턴)과 `tests` 픽스처가 필수입니다. 쓴 다음 `survey.py` 를 다시 돌려 준수율이
실제로 높게 나오는지 확인하세요. **"그렇게 보였다"로 규칙을 만들지 마세요 —
숫자가 없으면 제안하지 않는 게 맞습니다.**

## 6. 검증하고 설명하기

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --range HEAD~20..HEAD --severity error --no-color
```

`--explain` 에 `disabled by config.yaml`, `severity←config`, `superseded by ...` 가
의도대로 찍히는지 확인하세요.

마지막에 사용자에게 보고할 것:

1. 감지된 스택과 적용 규칙 수
2. 무엇을 끄거나 내렸고 **왜** 그랬는지
3. 지금 상태에서 최근 변경분에 몇 건이 남는지
4. 포맷터가 없다면 그걸 먼저 도입하라는 권고

## 7. 예방용 규칙을 컨텍스트에 넣기

훅은 **쓰고 난 뒤** 잡습니다. 되돌리는 비용이 큰 것들은 **쓰기 전에** 알고 있는 편이 낫습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --stdout   # 먼저 미리보기
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py"            # .claude/rules/ 에 생성
```

`.claude/rules/*.md` 는 `paths:` 프론트매터로 **해당 파일을 읽을 때만** 컨텍스트에
들어갑니다. PHP 규칙은 PHP 파일을 건드릴 때만 들어가므로 세션 시작 비용이 거의 없습니다.

**전체 규칙을 넣지 마세요.** 기계가 판정할 수 있는 것은 훅이 잡습니다. 컨텍스트에 넣을 것은
`semantic` 규칙(정규식으로 판정 불가)과 `in_context: true` 로 표시한 소수뿐이고,
기본 예산은 파일당 12개입니다. 목록이 길어지면 묻힙니다.

생성물은 커밋하세요. 팀원 리뷰 대상이고, 플러그인을 안 쓰는 사람에게도 문서가 됩니다.
관리 블록(`<!-- convention-guard:begin -->`) 밖의 수기 내용은 재생성해도 보존됩니다.

`.claude/rules/` 는 경로 스코핑이 되는 대신 Claude Code 전용입니다. 팀이 다른 도구도
쓰거나 사람이 읽을 문서가 필요하면 8번으로 가세요.

## 8. AGENTS.md 쓰기

에이전트가 세션 시작에 읽는 프로젝트 문서입니다. **본문은 `AGENTS.md` 에 두고
`CLAUDE.md` 는 그걸 가리키게** 합니다 — Claude Code 는 `@AGENTS.md` 를 import 로
전개하고, 다른 도구는 `AGENTS.md` 를 그대로 읽으므로 내용이 한 곳에만 있습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --agents-md --stdout  # 미리보기
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py" --agents-md           # 생성
```

이 명령이 만드는 것은 **관리 블록 안쪽(예방용 규칙 요약)뿐**입니다. 블록 밖은 사람
소유이고 재생성해도 보존됩니다. 그래서 **문서가 없던 레포라면 블록 밖을 당신이 한 번
채워주세요.** 추측해서 쓰지 말고 실제로 확인한 것만 적습니다.

| 섹션 | 어디서 알아내는가 |
|---|---|
| 프로젝트 한 줄 요약 | README, `composer.json`/`package.json` 의 description |
| 빌드·테스트·린트 명령 | `package.json` 의 scripts, `composer.json` 의 scripts, `Makefile`, CI 워크플로 |
| 디렉터리 구조 | 2번에서 파악한 소스 루트·테스트 위치·레거시 구역 |
| 이 레포에서 하지 말 것 | 생성 코드 직접 수정, 레거시 구역 리팩터링 등 실제로 확인한 것만 |

세 가지 원칙:

- **200줄 아래로.** 길면 전부 묻힙니다. 훅이 이미 잡는 것은 여기 적지 마세요.
- **명령은 실행해 보고 적으세요.** `npm test` 가 없는데 적혀 있으면 에이전트가 없는
  명령을 계속 시도합니다.
- **경로별 상세 규칙은 `.claude/rules/`** 로 보내세요 (7번). AGENTS.md 는 모든 세션에
  전부 로드됩니다.

이미 `AGENTS.md` 나 `CLAUDE.md` 가 있는 레포라면 블록만 갱신되고 나머지는 그대로입니다.
`CLAUDE.md` 가 이미 `@AGENTS.md` 를 직접 import 하고 있으면 건드리지 않습니다.
생성 후 두 파일을 사용자에게 보여주고 커밋을 권하세요.

## 도입 순서 권고

한 번에 다 켜지 마세요.

1. 포맷터 설정부터 (`presets/` 복사) — 포맷 규칙 대부분이 자동으로 물러납니다
2. 2~3주는 `error` 를 최소한으로. `warn` 은 로그만 쌓입니다
3. 추천 규칙은 3~5개만 `warn` 으로 채택 (5-1번). 전수조사 건수를 보고 정하세요
4. 예방 규칙만 `.claude/rules/` 로 내보내기 (5~10개, 그 이상은 묻힙니다)
5. `AGENTS.md` 는 200줄 아래로 유지
6. `rule-tune` 스킬로 수정률을 본 뒤 건강한 규칙만 `error` 로 승격
