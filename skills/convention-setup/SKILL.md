---
name: convention-setup
description: 이 레포에 맞는 convention-guard 설정을 만듭니다. 레포 구조·스택·린터·레거시 규모를 실제로 훑어보고 .claude/convention-rules/config.yaml 초안을 씁니다. "컨벤션 설정해줘", "이 레포에 규칙 붙여줘", "convention-guard 세팅", 새 레포에 도입할 때, 규칙이 너무 많이 걸려서 조정이 필요할 때 사용하세요.
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

`CLAUDE.md` 에 넣고 싶다면 `--claude-md` 를 쓰되, 그쪽은 경로 스코핑이 없어서 매 세션
전부 로드된다는 점을 사용자에게 알려주세요.

## 도입 순서 권고

한 번에 다 켜지 마세요.

1. 포맷터 설정부터 (`presets/` 복사) — 포맷 규칙 대부분이 자동으로 물러납니다
2. 2~3주는 `error` 를 최소한으로. `warn` 은 로그만 쌓입니다
3. 예방 규칙만 `.claude/rules/` 로 내보내기 (5~10개, 그 이상은 묻힙니다)
4. `rule-tune` 스킬로 수정률을 본 뒤 건강한 규칙만 `error` 로 승격
