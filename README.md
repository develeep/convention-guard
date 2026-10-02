# convention-guard

AI 코딩 에이전트가 작업을 끝낼 때마다 **에이전트가 쓴 코드**가 팀 컨벤션을 지켰는지 검사하고,
위반이면 고치게 한 뒤 **고쳐졌는지 다시 검증**하는 Claude Code 플러그인.

> 에이전트에게 컨벤션을 기억시키는 것이 아니라, 잊더라도 작업이 끝날 때 다시 검증되는 환경을 만듭니다.

```
도구 호출마다 → 편집 사건 원장: 이 줄은 누가 썼나 (에이전트 / 원래 있던 줄 / 사람 / 남의 커밋)
Stop → 에이전트가 쓴 줄 → 정규식 게이트 → 구조 확인(tree-sitter) → 후보
                                                   ├ 후보 없음 → 통과 (AI 호출 0)
                                                   ├ 결정론 후보 → 에이전트가 판단·수정
                                                   └ 의미 판정 후보 → convention-reviewer 에이전트
     → 수정 → 같은 범위 재검사 → 고쳐짐 / 기각 / 남음 / 새로 생김 → 남았으면 한 번 더
```

- **에이전트가 쓴 줄만 봅니다.** 도구 호출 전후 내용을 비교해 줄마다 출처를 기록합니다. 원래 있던 레거시, 사람이 옆에서 고친 줄, `git pull` 로 들어온 남의 커밋에는 반응하지 않습니다.
- **놓친 것은 말합니다.** 수집 훅이 죽었거나, Pre 없이 Post 만 왔거나, 도구 밖에서 파일이 바뀌었거나, 구조를 읽지 못했으면 이름을 붙여 알립니다. 읽지 못한 것이 "통과"로 보이지 않습니다.
- **주석과 문자열은 코드가 아닙니다.** 주석 처리해 둔 `console.log(`, 문자열 안의 `dd(` 는 지적하지 않고, 템플릿 리터럴의 `${...}`·f-string 의 `{...}` 안은 코드로 봅니다. tree-sitter 구문 트리로 판정하며, 플러그인이 엔진을 스스로 설치합니다.
- **후보는 위반이 아닙니다.** 정규식은 후보를 좁히고, 판정은 코드를 본 에이전트가 합니다. 오탐은 기각 기록으로 남고, 그 코드가 그대로인 동안 다시 지적되지 않습니다.
- **의미 판정은 필요할 때만.** N+1·계층 경계처럼 정규식으로 안 되는 규칙은 후보가 있고 판정 기록이 없을 때만, 함수 하나 분량의 컨텍스트로 서브에이전트가 판정합니다.
- **고친 뒤 검증합니다.** 수정이 새 위반을 만들었는지까지 확인하고, 연속 차단 상한으로 루프를 막습니다.

Python 3.10+. 구조 엔진(tree-sitter, 약 1.5MB 내려받음)은 첫 세션에 백그라운드로 설치됩니다. Laravel / PHP / Blade, Next / React / Nest / JS·TS, Python 규칙 34개 번들.

> **4.0 은 하위 호환을 끊었습니다.** 3.x 의 `dismissed.yaml`(`version: 4` 가 없는 파일), 판정 캐시, 세션 상태를 읽지 않습니다. 기각은 다시 하고, 설정의 `scope.base_ref`·`collect.edit_tools` 는 지우세요 (남아 있으면 "알 수 없는 설정" 경고). Go 규칙은 4.0 에서 빠졌습니다.

## 설치

```bash
/plugin marketplace add develeep/convention-guard
/plugin install convention-guard@develeep-convention-guard
```

로컬에서 시험: `claude --plugin-dir /path/to/convention-guard`

설치 직후 기본값은 `mode: report` 입니다. 검사 결과를 기록하지만 작업을 차단하지 않습니다.

## 시작하기

에이전트에게 **"convention-guard 세팅해줘"** 라고 하면 `convention-setup` 스킬이 아래를 대신합니다.

```bash
S=~/.claude/plugins/.../convention-guard/scripts   # 설치 위치

python3 $S/engine.py status                 # 구조 엔진이 설치됐는지
python3 $S/detect_stack.py                  # 감지된 스택·프리셋·적용 규칙·린터
python3 $S/setup.py init                    # .claude/convention-guard/config.yaml 초안 (mode: report)
python3 $S/scan.py --range HEAD~20..HEAD    # 최근 변경분에 몇 건이 걸리는지 측정
python3 $S/setup.py emit --agents-md        # 적용 규칙 전부 + 린터를 AGENTS.md 로
```

도입 첫 2~3주는 `mode: report` 로 기록만 쌓고, `rule-tune` 스킬로 건강도를 본 뒤 `mode: fix` 로 올리세요.

## 레포에 두는 것

```
.claude/convention-guard/
├── config.yaml      팀 설정 (플러그인 기본값에서 바꿀 키만)
├── dismissed.yaml   오탐으로 기각한 지적 (dismiss.py 가 씀, version: 4)
└── rules/           이 레포 전용 규칙, core 규칙 오버라이드
```

모두 커밋 대상입니다. 예시: [examples/repo-local/](examples/repo-local/)

```yaml
# .claude/convention-guard/config.yaml
mode: fix
presets: [auto, architecture]       # auto + 계층 경계 의미 판정
severity:
  core/php-line-too-long: warn
exclude: ["app/Legacy/**"]
semantic_review:
  enabled: true
```

## 스킬

| 스킬 | 언제 |
|---|---|
| `convention-setup` | 도입 (언제나 최초 실행 기준으로 새로 셋업) |
| `convention-readiness` | 실서비스에 켜기 전 도입 체크리스트 전 항목 점검 |
| `convention-discover` | CLAUDE.md·PR 리뷰·코드에서 팀 컨벤션을 찾아 규칙 후보로 |
| `convention-check` | 훅 없이 지금 검사 (커밋·PR 직전, 브랜치, 전수조사) |
| `rule-add` | 반복되는 리뷰 지적을 규칙으로 |
| `rule-tune` | 로그로 오탐 규칙을 좁히고 건강한 규칙을 승격 |

## 스크립트

| 스크립트 | 역할 |
|---|---|
| `scan.py` | 수동·CI 검사. `--staged` `--range` `--files` `--all` `--fix` `--review` `--fail-on-pending` `--require-engine`. 종료 코드 0/1/2 |
| `engine.py` | 구조 엔진 `status` / `ensure`(설치하고 기다림) / `verify-lock` |
| `detect_stack.py` | 무엇이 감지되고 어떤 규칙이 왜 적용되는지 |
| `dismiss.py` | 오탐 기각 기록 |
| `review.py` | 의미 판정 배치 보기·기록 (리뷰어 에이전트용) |
| `log_report.py` | 규칙 건강도 |
| `readiness.py` | 도입 체크리스트([docs/production-readiness.md](docs/production-readiness.md)) 자동 점검. `--quick` `--all` |
| `setup.py` | `init` 설정 초안, `emit` 적용 규칙 전부와 린터를 컨텍스트 문서로 |
| `session_start.py` / `collect.py` / `check.py` | SessionStart(엔진 설치) / Pre·PostToolUse(원장) / Stop 훅 |

CI:

```yaml
- run: python3 plugins/convention-guard/scripts/engine.py ensure
- run: python3 plugins/convention-guard/scripts/scan.py --range "origin/${{ github.base_ref }}..HEAD" --fail-on error --require-engine --no-color
```

의미 판정 규칙을 쓴다면 `--review --fail-on-pending` 을 더하세요. CI 에는 리뷰어를 돌릴
에이전트가 없어서, 붙이지 않으면 판정이 남은 후보를 통과로 읽습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 전체 흐름, 편집 사건 원장, 관찰 누락, decide(), 구조 엔진, 검증 사이클 |
| [docs/rules.md](docs/rules.md) | 규칙 레이어, 형식, 앵커, 구조 조건, 오버라이드, 프리셋 |
| [docs/semantic-review.md](docs/semantic-review.md) | 의미 판정 흐름, 최소 컨텍스트, 판정 캐시, 비용 |
| [docs/configuration.md](docs/configuration.md) | 전체 설정 키, mode, 린터 위임, 환경 변수, 설정 오류 |
| [docs/development.md](docs/development.md) | 테스트(엔진 있음/없음), 규칙·엔진·스킬 변경 절차, 릴리스 |
| [docs/production-readiness.md](docs/production-readiness.md) | 실 서비스 도입 체크리스트 — 배선·정확도·장애 모드·CI·운영 |
| [docs/design-4.0.md](docs/design-4.0.md) | 4.0 설계와 결정 |

## 알려진 한계

- **모노레포**: 스택은 레포 루트에서 한 번 판정합니다. 한 레포에 여러 스택이 섞이면 해당 규칙이 모두 켜지므로 `applies_to.files` 와 `exclude` 로 나누세요.
- **정규식은 정규식입니다.** 타입 추론이나 호출 그래프가 필요한 판정은 린터(phpstan, tsc, mypy)나 의미 판정 규칙의 몫입니다.
- **도구 호출 구간 안의 사람 편집**: 에이전트의 도구가 도는 그 순간 사람이 같은 파일을 고치면 에이전트 줄로 봅니다.
- **구조 엔진 플랫폼**: musl aarch64 와 free-threaded Python 에는 휠이 없어 엔진 없이 돕니다 ("구조 엔진 없음 (미지원 플랫폼)").
- **Stop 은 "작업 완료"가 아니라 "턴 종료"입니다.** 질문으로 끝난 턴은 건너뛰지만, 중간 보고로 끝난 턴도 검사될 수 있습니다.
- **의미 판정 요청은 메인 에이전트가 무시할 수 있습니다.** 한 번 더 요청하고, 그다음은 `review_skipped` 로 기록합니다.

## 라이선스

MIT
