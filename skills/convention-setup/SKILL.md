---
name: convention-setup
description: 레포에 convention-guard 를 처음부터 도입합니다. 스택·린터·포맷터를 감지하고, config.yaml 초안을 쓴 뒤 최근 변경분에서 실제로 몇 건이 걸리는지 측정해 조정하고, 적용되는 규칙 전부와 린터를 AGENTS.md 나 .claude/rules 로 내보냅니다. 기존 설정이 있으면 한 번 확인한 뒤 덮어쓰고 새로 시작합니다. "컨벤션 설정해줘", "convention-guard 세팅", 새 레포에 도입할 때, 아직 발동 로그가 쌓이지 않았는데 설정을 처음부터 다시 잡고 싶을 때 사용합니다 (로그가 이미 있고 규칙만 손보려면 rule-tune).
---

# convention-guard 도입

항상 **최초 실행**으로 셋업합니다. 기존 설정을 이어 고치지 않습니다.
도입 첫날의 목표는 규칙을 많이 켜는 것이 아니라 **걸리는 것이 전부 진짜이게** 만드는 것입니다.

## 체크리스트

```
- [ ] 1. 기존 설정 확인 (있으면 한 번 묻고 덮어씀)
- [ ] 2. 감지 결과 확인
- [ ] 3. 설정 초안 쓰기
- [ ] 4. 측정 → 조정 → 재측정 (남는 지적이 진짜일 때까지)
- [ ] 5. 컨벤션 전부를 AGENTS.md 로 내보내기
- [ ] 6. 보고
```

### 1. 기존 설정 확인

`.claude/convention-guard/config.yaml` 이 있으면 사용자에게 **한 번만** 묻습니다: "기존 설정을 덮어쓰고 처음부터 셋업할까요?"

- 예 → 3단계에서 `init --force` 로 덮어씁니다.
- 아니오 → 멈추고, 기존 설정 조정은 rule-tune 소관이라고 알립니다.

없으면 묻지 않고 진행합니다.

### 2. 감지 결과 확인

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_stack.py"
```

- `stacks` 가 비었다: 마커 파일(`composer.json`, `package.json`, `go.mod`)이 루트에 없는 레포입니다. 3단계에서 `stacks:` 로 지정합니다.
- 린터 `[출력 파싱 불가 → 전체 출력으로 차단]`: 이번 변경과 무관한 기존 에러로도 차단됩니다. `${CLAUDE_PLUGIN_ROOT}/stacks/*.yaml` 에 `parse:` 가 필요하다고 사용자에게 알리세요 (`${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` 의 린터 절).
- 끝의 `error` 노트는 반드시 해결하고 넘어갑니다.

### 3. 설정 초안 쓰기

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" init --stdout   # 확인
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" init            # 1단계에서 덮어쓰기로 했으면 --force
```

초안은 `mode: report` 입니다. 도입 초기에는 차단 없이 기록만 쌓는 것이 기본값입니다.

`init` 이 종료 코드 2 로 `.claude/convention-rules` 가 있다고 멈추면, 그 디렉터리를 치울지 사용자에게 알리고 멈춥니다.

### 4. 측정 → 조정 → 재측정

추측으로 설정을 쓰지 말고, 실제로 걸리는 양을 봅니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --range HEAD~20..HEAD --no-lint --fail-on never --no-color
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --all --severity error --no-lint --fail-on never --json
```

`--all` 결과는 나열하지 말고 규칙별 건수로 집계해서 봅니다. 찾은 것을 이 표에 대어 `config.yaml` 을 고칩니다.

| 관찰 | 조치 |
|---|---|
| 최근 20커밋에 한 error 규칙이 10건 넘게 걸림 | `severity:` 로 warn |
| 지적이 특정 디렉터리에 몰림 | `exclude:` 에 그 경로 — 규칙 문제가 아니라 레거시 구역 |
| 포맷 규칙이 많이 걸리는데 포맷터 설정이 없음 | `${CLAUDE_PLUGIN_ROOT}/examples/formatters/` 의 설정 도입을 권고 — 포맷 규칙이 스스로 물러남 |
| 팀이 동의하지 않는 규칙 | `disable:` + 이유 주석 |
| 전수조사에만 나오고 최근 변경에는 없음 | 그대로 둠 — 변경 앵커가 레거시를 걸러내는 중 |

고친 뒤 `detect_stack.py` 로 노트에 error 가 없는지 확인하고 측정을 다시 돌립니다. 남은 지적을 몇 개 열어 보고 **진짜 위반일 때까지** 반복합니다.

`disable` 보다 `exclude` 와 `severity` 를 먼저 씁니다. 되돌리기 쉽고 팀 표준에서 영구히 빠지지 않습니다.

### 5. 컨벤션 전부를 AGENTS.md 로 내보내기

훅과 린터가 사후에 잡는 것도 **전부** 적습니다. 에이전트가 쓰기 전에 알면 차단이 줄어듭니다. 4단계 조정이 끝난 뒤에 내보내야 끈 규칙이 들어가지 않습니다.

- 규칙: 적용되는 규칙마다 한 줄. `prevent:` 가 있으면 그 줄, 없으면 `제목 — message 첫 문단`
- 린터: 설치돼 실제로 돌 린터마다 명령 한 줄

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" emit --agents-md --stdout   # AGENTS.md (기본)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" emit --stdout               # .claude/rules/ 로 경로별 분리
```

AGENTS.md 가 기본입니다. 레포가 `.claude/rules/` 를 쓰고 있을 때만 두 번째를 제안합니다. 미리보기를 사용자에게 보여주고 `--stdout` 없이 실행합니다. 관리 블록 밖의 내용은 보존되고, `--agents-md` 는 CLAUDE.md 에 `@AGENTS.md` 가져오기를 추가합니다. 생성물은 커밋 대상입니다.

### 6. 보고

```
스택: laravel, php · 프리셋: common, laravel, php, psr12, security · 적용 규칙 23개
설정: 새로 작성 (기존 config.yaml 덮어씀)
모드: report — 2~3주 뒤 rule-tune 으로 fix 전환 검토
조정:
- core/php-line-too-long → warn (최근 20커밋 14건, 체이닝 관례)
- exclude "app/Legacy/**" (전수조사 error 의 80%)
최근 20커밋 기준 남는 지적: error 2 / warn 5
AGENTS.md: 규칙 23개 + 린터 2개 (pint, phpstan)
권고: pint.json 도입 시 포맷 규칙 9개가 물러납니다
```
