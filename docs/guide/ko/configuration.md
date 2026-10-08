# 설정

[README](../../../README.md) · **한국어** · [English](../en/configuration.md)

## 목차
- 우선순위와 위치
- 전체 키
- mode
- presets
- limits
- 린터 위임
- userConfig
- 환경 변수
- 설정 오류

## 우선순위와 위치

```
플러그인 config.yaml  <  userConfig (설치할 때 고른 값)  <  <repo>/.claude/convention-guard/config.yaml
```

레포 설정이 최종입니다. 개인 설정으로 팀 표준을 조용히 약화시킬 수 없습니다.
레포 설정에는 바꿀 키만 적습니다. 그룹(`limits` 등)의 일부 키만 적으면 나머지는 기본값이 유지됩니다.

초안 만들기: `python3 scripts/setup.py init --stdout`

## 전체 키

| 키 | 기본값 | 설명 |
|---|---|---|
| `mode` | `report` | `report` 기록만 / `fix` 차단 / `auto-fix` 안전한 규칙은 자동 수정 후 차단 |
| `presets` | `auto` | `auto` 또는 목록. `[auto, architecture]` 처럼 섞을 수 있음 |
| `stacks` | `[]` | 감지가 빗나갈 때만 강제 지정 |
| `disable` | `[]` | 끌 규칙 id |
| `severity` | `{}` | 규칙별 강도. `core/php-line-too-long: warn` |
| `exclude` | `[]` | 검사하지 않을 경로 글롭. (400KB 넘는 파일과 앞 8KB 에 NUL 이 있는 바이너리는 설정과 관계없이 건너뛰고, 큰 파일은 "큰 파일 미검사"로 알립니다) 규칙과 같은 문법이고, 여기서는 `legacy/` 를 `legacy/**` 로, 앞의 `/` 를 레포 루트로 읽습니다 |
| `generated` | 기본 목록 | 어떤 규칙도 읽지 않는 경로 글롭: 빌드 산출물(`**/dist/**`, `**/build/**`, `**/*.min.js` …), 생성 코드(`**/*.generated.*`, `**/*_pb2.py` …), lock 파일(`package-lock.json`, `pnpm-lock.yaml`), 테스트(`**/tests/**`, `**/*.test.*`, `**/test_*.py` …). 목록 전체는 `scripts/lib/config.py` 의 `GENERATED`. `.gitignore` 된 경로는 이것과 별개로 이미 빠집니다. 레포 config 에 쓰면 목록이 **통째로** 바뀌고, `[]` 이면 끕니다. 경로마다 확인은 `detect_stack.py --path` |
| `limits.max_error_rules` | 4 | 한 번에 보여줄 error 규칙 수 |
| `limits.max_warn_rules` | 3 | 차단할 때 함께 보낼 warn 규칙 수 |
| `limits.max_locations_per_rule` | 3 | 규칙당 위치 수 |
| `limits.max_consecutive_blocks` | 3 | 한 요청 안의 연속 차단 상한. 새 요청이 시작되거나 차단할 것이 없는 턴에서 초기화 |
| `limits.max_verify_attempts` | 1 | 검증에서 남은/새 위반으로 다시 차단하는 횟수 |
| `linters.enabled` | `true` | 스택별 린터 위임 |
| `linters.timeout` | 90 | 린터 명령 하나당 초 |
| `semantic_review.enabled` | `false` | 의미 판정 |
| `semantic_review.max_candidates` | 5 | 배치당 후보 수 |
| `semantic_review.context_budget_lines` | 400 | 배치당 컨텍스트 줄 수 |
| `semantic_review.verdict_ttl_days` | 30 | 판정 캐시 유효 기간 |
| `skip_if_question` | `true` | 에이전트가 질문으로 턴을 끝내면 검사 생략 |
| `respect_supersede` | `true` | 포맷터 설정이 있으면 해당 포맷 규칙 비활성 |
| `once_per_session` | `true` | 세션에서 고쳐진 규칙은 다시 지적하지 않음 (기각은 예산을 쓰지 않음). `when_code_added` 규칙은 해당 없음 — 같은 코드를 두 번 묻지 않는 것은 판정 캐시가 맡음 |

## mode

| mode | 결정론 error | 의미 판정 요청 | 자동 수정 |
|---|---|---|---|
| `report` | 기록 + 한 줄 요약, 차단 안 함 | 안 함 | 안 함 |
| `fix` | 차단 → 검증 사이클 | 후보 있으면 요청 | 안 함 |
| `auto-fix` | `fix` 와 같음 | `fix` 와 같음 | `fix.auto` 규칙을 먼저 적용 |

도입 첫 2~3주는 `report` 로 로그를 쌓고, `rule-tune` 스킬로 건강도를 본 뒤 `fix` 로 올리기를 권합니다.

## presets

`auto` 는 `common`, `security`, 그리고 감지된 스택 태그와 겹치는 프리셋입니다. `architecture`, `performance`, `layering` 은 명시해야 켜집니다. 목록: [rules.md](rules.md#프리셋)

```yaml
presets: [auto, architecture]     # auto + 계층 경계 의미 판정
presets: [laravel, security]      # 고른 것만 (common·php·psr12 는 빠짐)
```

## limits

연속 차단 상한과 검증 횟수는 함께 루프를 막습니다.

```
차단(1) → 수정 → 검증: 남음 → 차단(2, 마지막 검증) → 수정 → 검증: 남음 → 기록만 하고 종료
```

`max_consecutive_blocks` 는 한 요청 안의 루프 가드입니다. 걸린 뒤에도 같은 요청 안에서는 위반이 남아 있는 동안 기록만 합니다. 새 요청이 시작되면(continuation 이 아닌 Stop) 초기화되므로, 지난 요청에서 남긴 위반이 다음 요청의 새 위반까지 막지 않습니다. 요청을 넘어 다시 나오는 위반은 "지난 턴에도 지적했습니다"로 표시됩니다.

## 린터 위임

`stacks/*.yaml` 의 `lint` 항목입니다.

```yaml
lint:
  - cmd: ["./vendor/bin/phpstan", "analyse", "--error-format=raw", "{files}"]
    if_exists: vendor/bin/phpstan       # 없으면 조용히 건너뜀
    files: ["**/*.php"]                 # 이 린터가 받을 파일
    parse: unix                         # 출력에서 file:line 을 읽는 방식
```

| parse | 출력 형식 |
|---|---|
| `eslint-json` | `eslint --format=json` |
| `phpstan-json` | `phpstan --error-format=json` |
| `unix` | `file:line[:col]: message` |
| `github` | `::error file=...,line=...` |
| `diff` | 유니파이드 diff (`pint --test -v`, `php-cs-fixer --diff`) |

파싱된 위치가 **변경된 줄**이면 차단하고, 같은 파일의 다른 줄이면 참고로만 전달합니다. `parse` 가 없거나 출력을 읽지 못하면 출력 전체로 차단합니다(진짜 실패를 버리는 것이 더 나쁘기 때문). `{dirs}` 는 변경 파일의 디렉터리 목록으로 바뀝니다.

`detect_stack.py` 가 린터마다 `= 참고: parse … — 변경 줄만 차단` / `= 참고: 출력 파싱 불가 — 전체 출력으로 차단` / `= 참고: 설치 안 됨 — 건너뜀` 을 보여줍니다.

## userConfig

플러그인 설치 시 고르는 값입니다.

| 키 | 효과 |
|---|---|
| `report_only` | `true` → `mode: report`, `false` → `mode: fix`. 고르지 않으면 플러그인 기본값(`report`). 레포 config 에 `mode` 가 있으면 그쪽이 이깁니다 |
| `semantic_review` | `semantic_review.enabled` |
| `log_dir` | `firings.jsonl` 위치 (레포 경로는 고르지 마세요 — git 에 잡힘) |

4.0 에는 훅의 검사 범위를 넓히는 설정(3.x 의 `scope.base_ref`)과 수집할 MCP 도구 목록
(3.x 의 `collect.edit_tools`)이 없습니다. 훅은 편집 사건 원장이 기록한 **에이전트가 쓴 줄**만
검사합니다. MCP 도구 호출은 관찰하지 않으므로 MCP 도구가 쓴 줄은 검사하지 않습니다. 브랜치 전체를 보려면 `scan.py --range <base>..HEAD`
를 쓰세요. 남아 있는 옛 키는 "알 수 없는 설정 (무시)" 경고가 됩니다 (훅에서는 검사한 턴의 `검사 경고`).

## 환경 변수

| 변수 | 효과 |
|---|---|
| `CLAUDE_PLUGIN_DATA` | 상태 저장소(`convention-guard.db`)와 구조 엔진의 위치. Claude Code 가 훅에 넘깁니다. 없으면 `$XDG_CACHE_HOME/convention-guard`, 그다음 `~/.cache/convention-guard` |
| `CONVENTION_GUARD_ENGINE_DIR` | 구조 엔진 설치 디렉터리 (기본: `$CLAUDE_PLUGIN_DATA/engine`) |
| `CONVENTION_GUARD_NO_ENGINE` | 비어 있지 않으면(값과 무관 — `0` 도) 구조 엔진을 쓰지 않습니다 — 모든 구조 조건이 UNKNOWN 이 되고 "구조 엔진 없음 (꺼짐)" 으로 알립니다 |
| `CONVENTION_GUARD_WHEELS` | 오프라인 설치: `lock.json` 에 적힌 휠을 둔 디렉터리. 다운로드 대신 여기서 설치하고 sha256 검사는 같습니다 |

## 설정 오류

설정이 잘못되면 추측으로 검사하지 않습니다.

| 상황 | 훅 | scan.py / detect_stack.py |
|---|---|---|
| config 파싱 실패, 알 수 없는 mode, 없는 프리셋 | 검사를 건너뛰고 사유를 알림 | 종료 코드 2 |
| `dismissed.yaml` 파싱 실패 | 같음 — 기각을 무시한 채 검사하지 않음 | 같음 |
| `dismissed.yaml` 에 `version: 4` 가 없음 (4.0 이전 형식) | 경고하고 그 기각은 적용하지 않음 | 같음 — `dismiss.py` 는 그 파일에 덧붙이지 않음 |
| 규칙 파일 오류 | 같음 | 같음 |
| 알 수 없는 키 | 무시하고, 검사한 턴이면 `검사 경고` 로 알림 | 경고 |
