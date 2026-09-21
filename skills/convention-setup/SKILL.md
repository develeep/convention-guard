---
name: convention-setup
description: 레포에 convention-guard 를 도입하거나 다시 맞춥니다. 스택·린터·포맷터를 감지하고, 최근 변경분에서 실제로 몇 건이 걸리는지 측정해 .claude/convention-guard/config.yaml 을 조정한 뒤, 예방 규칙을 AGENTS.md 나 .claude/rules 로 내보냅니다. "컨벤션 설정해줘", "convention-guard 세팅", 새 레포에 도입할 때, 아직 발동 로그가 쌓이지 않았는데 지적이 너무 많거나 이상해서 설정을 다시 잡을 때 사용합니다 (로그가 이미 있으면 rule-tune). 0.x 설정(.claude/convention-rules)이 남아 있으면 마이그레이션부터 합니다.
---

# convention-guard 도입

도입 첫날의 목표는 규칙을 많이 켜는 것이 아니라 **걸리는 것이 전부 진짜이게** 만드는 것입니다.
그래야 에이전트가 차단 메시지를 진지하게 읽습니다.

## 체크리스트

```
- [ ] 1. 0.x 설정이면 마이그레이션
- [ ] 2. 감지 결과 확인
- [ ] 3. 설정 초안 쓰기
- [ ] 4. 측정 → 조정 → 재측정 (남는 지적이 진짜일 때까지)
- [ ] 5. 예방 규칙 내보내기
- [ ] 6. 보고
```

### 1. 0.x 설정이면 마이그레이션

`.claude/convention-rules/` 가 있으면 새로 만들지 말고 옮깁니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/migrate.py"            # 미리보기 (diff)
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/migrate.py" --write
```

`✗` 가 붙은 파일은 의미가 바뀔 수 있어 쓰지 않은 것입니다. 메시지대로 원본을 고치고 다시 실행하세요.

### 2. 감지 결과 확인

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_stack.py"
```

- `stacks` 가 비었다: 마커 파일(`composer.json`, `package.json`, `go.mod`)이 루트에 없는 레포입니다. 3단계에서 `stacks:` 로 지정합니다.
- 린터 `[출력 파싱 불가 → 전체 출력으로 차단]`: 이번 변경과 무관한 기존 에러로도 차단됩니다. `stacks/*.yaml` 에 `parse:` 가 필요하다고 사용자에게 알리세요 (`${CLAUDE_PLUGIN_ROOT}/docs/configuration.md` 의 린터 절).
- 끝의 `error` 노트는 반드시 해결하고 넘어갑니다.

### 3. 설정 초안 쓰기

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" init --stdout   # 확인
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" init
```

초안은 `mode: report` 입니다. 도입 초기에는 차단 없이 기록만 쌓는 것이 기본값입니다.

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
| 포맷 규칙이 많이 걸리는데 포맷터 설정이 없음 | `examples/formatters/` 도입을 권고 — 포맷 규칙이 스스로 물러남 |
| 팀이 동의하지 않는 규칙 | `disable:` + 이유 주석 |
| 전수조사에만 나오고 최근 변경에는 없음 | 그대로 둠 — 변경 앵커가 레거시를 걸러내는 중 |

고친 뒤 `detect_stack.py` 로 노트에 error 가 없는지 확인하고 측정을 다시 돌립니다. 남은 지적을 몇 개 열어 보고 **진짜 위반일 때까지** 반복합니다.

`disable` 보다 `exclude` 와 `severity` 를 먼저 씁니다. 되돌리기 쉽고 팀 표준에서 영구히 빠지지 않습니다.

### 5. 예방 규칙 내보내기

훅은 쓰고 난 뒤 잡습니다. 되돌리는 비용이 큰 규칙(`prevent:` 가 있는 것)만 쓰기 전에 컨텍스트에 넣습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" emit --agents-md --stdout   # AGENTS.md 를 쓰는 레포
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" emit --stdout               # .claude/rules/ 로 경로별 분리
```

미리보기를 사용자에게 보여주고 고른 방식으로 `--stdout` 없이 실행합니다. 관리 블록 밖의 내용은 보존됩니다. 생성물은 커밋 대상입니다.

### 6. 보고

```
스택: laravel, php · 프리셋: common, laravel, php, psr12, security · 적용 규칙 23개
모드: report — 2~3주 뒤 rule-tune 으로 fix 전환 검토
조정:
- core/php-line-too-long → warn (최근 20커밋 14건, 체이닝 관례)
- exclude "app/Legacy/**" (전수조사 error 의 80%)
최근 20커밋 기준 남는 지적: error 2 / warn 5
권고: pint.json 도입 시 포맷 규칙 9개가 물러납니다
```
