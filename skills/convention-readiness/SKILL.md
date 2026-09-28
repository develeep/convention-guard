---
name: convention-readiness
description: convention-guard 를 팀 레포에 실제로 켜도 되는지 도입 체크리스트(docs/production-readiness.md) 전 항목을 점검합니다. 스크립트 한 번으로 Python·설치 범위·훅 배선·userConfig·설정 계층·개인 규칙·기각 기록·규칙 픽스처와 도달 범위·탐지량·성능·보안·CI 를 판정하고, 차단·재검증·의미 판정·장애 모드는 플러그인 테스트를 샌드박스에서 돌려 확인한 뒤, FAIL·WARN 을 고칠 방법과 사람이 확인할 항목만 보고합니다. "도입 점검해줘", "실서비스에 켜도 돼?", "도입 체크리스트 돌려줘", "플러그인이 제대로 동작하는지 확인", 업데이트 직후, 팀원 머신 점검, fix 모드로 올리기 전에 사용합니다 (설정을 새로 잡는 것은 convention-setup, 코드 위반 검사는 convention-check).
---

# 도입 점검

판정은 스크립트가 합니다. 체크리스트를 손으로 하나씩 돌리지 않습니다.
**검사하지 못한 것을 통과로 보고하지 않습니다** — `MANUAL`·`SKIP` 은 확인되지 않은 것입니다.

## 체크리스트

```
- [ ] 1. readiness.py 실행
- [ ] 2. FAIL → WARN 순으로 항목 설명 찾기
- [ ] 3. 고칠 것 제안 (사용자 동의 후 수정)
- [ ] 4. 고친 항목만 재점검 (FAIL 0 이 될 때까지)
- [ ] 5. 판정 보고
```

### 1. 실행

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/readiness.py"
```

세션을 연 디렉터리에서 실행합니다 — Claude Code 의 프로젝트·로컬 설정(B2·B5)은 그 디렉터리 기준이라 `--cwd` 로 git 루트를 넘기면 모노레포 하위 프로젝트에서 틀립니다. 전체 점검은 10초 안팎이고, 샌드박스 테스트와 탐지량 측정은 임시 데이터 디렉터리에서 돌아 레포와 훅의 로그·세션 상태를 건드리지 않습니다.

| 요청 | 옵션 |
|---|---|
| (기본) 전체 | 없음 |
| 레거시 규모까지 | `--all` (전수조사 — 큰 레포에서 느림) |
| 탐지량을 잴 커밋 수 | `--commits N` (기본 20) |
| 설치·설정만 빠르게 | `--quick` (샌드박스·탐지량·성능 생략) |

종료 코드 `0` FAIL 없음 / `1` FAIL 있음 / `2` 검사 불가 (git 레포가 아님 — 사용자에게 알리고 멈춤).

### 2. 항목 설명 찾기

출력 한 줄 = 체크리스트 항목 id 하나, `→` 줄이 고칠 방법입니다. `→` 만으로 원인이 분명하지 않을 때만 그 항목을 찾아 읽습니다 — 문서 전체를 읽지 않습니다.

```bash
grep -n -A8 '\*\*B5\.' "${CLAUDE_PLUGIN_ROOT}/docs/production-readiness.md"
```

`F`·`G`·`H` 처럼 숫자 없는 id 는 절 전체입니다 — `'^## F\.'` 로 찾습니다.

`F`·`G`·`H`·`D1`·`D3`·`D4`·`C2` 같은 **샌드박스** 줄의 FAIL 은 레포 문제가 아니라 이 머신에서 플러그인이 기대대로 돌지 않는다는 뜻입니다. `→` 의 실패 단언을 그대로 보고하고, 레포를 고치려 하지 않습니다. 예외는 `D1` — 실패한 파일이 레포의 `.claude/convention-guard/rules/` 나 `~/.claude/convention-guard/rules/` 에 있으면 그 규칙의 픽스처나 정규식 문제이므로 rule-add 스킬의 검증 루프로 고칩니다.

### 3. 고칠 것 제안

고칠 방법을 항목별로 한 줄씩 제안하고, **사용자가 동의한 것만** 고칩니다. 특히 다음은 반드시 묻습니다.

- `.claude/settings.json` (B2) — 커밋되어 팀 전체에 영향
- `~/.claude/settings.json` 의 `pluginConfigs` (B5) — 사용자 개인 설정
- `config.yaml` 의 `mode`·`severity`·`exclude` (C1·E1) — 팀 표준

WARN 중 의도된 것은 그대로 둡니다 (예: 아직 없는 스택의 규칙이 D2 에 걸림, 개인 규칙을 일부러 쓰는 C5).

### 4. 재점검

고친 항목이 전부 설치·설정 항목(A·B·C·D2·D5·J·K)이면 `--quick` 으로 다시 돌립니다. 규칙이나 설정을 바꿔 탐지량이 달라질 수 있으면(E1) 전체로 다시 돌립니다. FAIL 이 0 이 될 때까지 반복합니다.

### 5. 판정 보고

| 결과 | 판정 |
|---|---|
| FAIL 1건 이상 | **도입 불가** — 무엇을 고쳐야 하는지 |
| WARN 만 | **조건부** — 남긴 WARN 과 그 이유 |
| PASS 만 (+MANUAL) | **도입 가능** |

MANUAL 항목은 항상 "사람이 확인할 것"으로 따로 적습니다. 출력에 없는 수동 항목 중 빠뜨리기 쉬운 것: A2 팀원의 Windows 네이티브, E3 오탐 샘플 확인, L1~L3 2~3주 운영, B6 스킬 행동 평가.

```
판정: 조건부 — FAIL 0 · WARN 2 · PASS 41 (점검 11초, 플러그인 3.0.1)
고침:
- B5 log_dir './logs' → ~/convention-guard-logs (상대경로라 레포마다 로그가 흩어짐)
남은 WARN:
- B2 user 범위에서만 켜짐 — 팀원 적용은 .claude/settings.json 커밋 후 (사용자 보류)
- D2 core/laravel-migration-needs-down 가 닿는 파일 없음 — 아직 마이그레이션 없음, 의도됨
사람이 확인할 것:
- K1 CI 에 scan.py 없음 — docs/production-readiness.md K 절
- A2 팀원 중 Windows 네이티브 사용자
- 로그 확인 시: CLAUDE_PLUGIN_DATA="<B4 경로>" python3 .../log_report.py --repo .
다음: report 로 2~3주 → rule-tune
```
