# 명령

[README](../../../README.md) · **한국어** · [English](../en/cli.md)

스킬이 부르는 스크립트를 터미널이나 CI 에서 직접 실행하는 방법입니다. 모든 스크립트는 `python3 <경로>` 로 실행합니다. 아래의 `$CG` 는 플러그인 설치 경로입니다 ([구하는 법](installation.md#설치-위치와-데이터-디렉터리)).

## 목차
- 한눈에 보기
- scan.py — 수동 검사
- detect_stack.py — 무엇이 적용되나
- setup.py — 설정 초안과 컨텍스트 문서
- dismiss.py — 오탐 기각
- log_report.py — 규칙 건강도
- readiness.py — 도입 점검
- engine.py — 구조 엔진
- review.py — 의미 판정 배치
- CI 에 넣기

## 한눈에 보기

| 스크립트 | 하는 일 | 주로 부르는 곳 |
|---|---|---|
| `scan.py` | 훅 없이 검사. 종료 코드 0/1/2 | convention-check, CI |
| `detect_stack.py` | 감지된 스택·프리셋·적용 규칙·린터와 그 사유 | convention-setup |
| `setup.py` | `init` 설정 초안, `emit` 규칙을 AGENTS.md 등으로 | convention-setup, rule-add |
| `dismiss.py` | 오탐을 `dismissed.yaml` 에 기록 | 훅의 차단 메시지, convention-check |
| `log_report.py` | 발동 로그로 규칙별 수정률·기각률·정밀도 | rule-tune |
| `readiness.py` | 도입 체크리스트 자동 점검 | convention-readiness |
| `engine.py` | 구조 엔진 상태·설치 | SessionStart 훅, CI |
| `review.py` | 의미 판정 배치 보기·기록 | convention-reviewer 에이전트 |
| `session_start.py` · `collect.py` · `check.py` | 훅 진입점 (SessionStart / Pre·PostToolUse / Stop) | `hooks/hooks.json` — 직접 실행하지 않음 |

대부분의 스크립트는 `--cwd <레포>` 로 다른 레포를 검사할 수 있고 (기본: 현재 디렉터리), 출력 형식은 공통입니다. 오류는 stderr 에 `convention-guard: error: …` 로 나옵니다.

## scan.py — 수동 검사

Stop 훅과 같은 파이프라인을 돌립니다. 같은 변경이면 훅과 같은 결과가 나옵니다. 다만 훅은 **에이전트가 쓴 줄**만 보고, `scan.py` 는 git 이 보여 주는 변경을 봅니다.

```bash
python3 "$CG/scripts/scan.py"                         # 워킹 트리 (기본)
python3 "$CG/scripts/scan.py" --staged                # 커밋 직전
python3 "$CG/scripts/scan.py" --range main..HEAD      # 브랜치 변경분
python3 "$CG/scripts/scan.py" --files app/X.php       # 지정 파일 전체
python3 "$CG/scripts/scan.py" --all --severity error  # 레포 전수조사 (레거시 감사)
```

**범위** (하나만 고릅니다)

| 옵션 | 검사 대상 | 무엇이 "추가된 줄"인가 |
|---|---|---|
| (없음) | 워킹 트리: HEAD 대비 변경 + 새 파일 | 추가된 줄 |
| `--staged` | 스테이지된 변경 (본문도 index 에서 읽음) | 추가된 줄 |
| `--range A..B` | 리비전 범위 (본문은 B 에서 읽음) | 추가된 줄 |
| `--files a b …` | 지정한 파일 전체 | 파일 전체를 새 파일로 취급 |
| `--all` | 추적 중인 파일과 무시되지 않은 새 파일 중 텍스트 파일 전부 | 파일 전체를 새 파일로 취급 |
| `--base-ref <ref>` | (워킹 트리와 함께) HEAD 대비 변경에 `<ref>` 대비 변경을 합침. `auto` 면 기본 브랜치와의 merge-base | 추가된 줄 |

**출력·필터**

| 옵션 | 효과 |
|---|---|
| `--severity error\|warn\|info` | 이 강도 이상만 **출력** (기본 info). 종료 코드는 모든 지적으로 판단 |
| `--rule <id 일부>` | id 에 이 문자열이 들어간 규칙 하나만 |
| `--no-lint` | 린터 위임 생략 (빠름) |
| `--no-dismiss` | 기각 기록을 무시하고 전부 — 무엇이 억제돼 있는지 볼 때 |
| `--max-hits N` | 규칙당 위치 수 (기본 10) |
| `--json` | 기계가 읽을 형태. `summary`(개수·`exit_code`), `scope`, `findings`, `review`, `fixes`, `unchecked` 등 |
| `--no-color` | 색 끔 |

**수정·판정·CI**

| 옵션 | 효과 |
|---|---|
| `--fix` | `fix.auto` 가 있는 규칙의 자동 수정안을 보여 줌 |
| `--fix --write` | 수정안을 적용하고 남은 것을 보고 |
| `--review` | 의미 판정 후보로 판정 배치를 만들고, 캐시된 `VIOLATION` 판정을 결과에 포함 |
| `--fail-on error\|warn\|info\|never` | 이 강도 이상이 있으면 종료 코드 1 (기본 error) |
| `--fail-on-pending` | `--review` 에서 판정이 남은 후보가 있으면 종료 코드 1 |
| `--require-engine` | 구조 엔진이 없어 구조 조건을 확인하지 못했으면 종료 코드 2 |

**종료 코드**

| 코드 | 뜻 |
|---|---|
| `0` | 통과 — `--fail-on` 기준 미만. warn·info 후보는 있을 수 있으니 출력을 읽으세요 |
| `1` | `--fail-on` 이상의 지적, 변경 줄에 걸린 린터 실패, 또는 `--fail-on-pending` 의 판정 대기 |
| `2` | 검사 불가 — git 이 아님, 범위 해석 실패, 레포 밖 경로, 규칙·설정·기각 파일 오류, (`--require-engine`) 엔진 없음 |

`2` 는 "지적 없음"이 아니라 검사를 끝내지 못했다는 뜻입니다. stderr 를 확인하세요.

`--review` 없이는 의미 판정 후보가 종료 코드에 들어가지 않습니다. 출력 끝 `■ 다음` 에 `semantic 규칙 후보 N건` 으로만 나옵니다.

## detect_stack.py — 무엇이 적용되나

```bash
python3 "$CG/scripts/detect_stack.py"            # --cwd <레포>, --json
```

설정 파일 위치, 감지된 스택 태그, 켜진 프리셋, 린터마다 상태, 그리고 34개 규칙 전부를 `✔ on` / `○ off` 와 사유(`preset 비활성`, `스택/버전 불일치`, superseded, config disable, `warn->error` 같은 강도 조정)로 보여 줍니다.

린터 줄의 `= 참고:` 는 이렇게 읽습니다.

| 표시 | 뜻 |
|---|---|
| `설치 안 됨 — 건너뜀` | 린터 바이너리가 없어 돌리지 않음 |
| `parse … — 변경 줄만 차단` | 출력을 읽어 변경된 줄에 걸린 실패만 차단 |
| `출력 파싱 불가 — 전체 출력으로 차단` | 이번 변경과 무관한 기존 에러로도 차단될 수 있음 — [린터 위임](configuration.md#린터-위임) |

설정 오류가 있으면 종료 코드 2 입니다.

## setup.py — 설정 초안과 컨텍스트 문서

```bash
python3 "$CG/scripts/setup.py" init --stdout              # 이 레포에 맞춘 config.yaml 초안 미리보기
python3 "$CG/scripts/setup.py" init                       # .claude/convention-guard/config.yaml 작성 (있으면 종료 코드 1)
python3 "$CG/scripts/setup.py" init --force               # 기존 파일 덮어쓰기
python3 "$CG/scripts/setup.py" emit --agents-md --stdout  # 적용 규칙 전부 + 린터를 AGENTS.md 관리 블록으로 (미리보기)
python3 "$CG/scripts/setup.py" emit --agents-md           # AGENTS.md 에 쓰고 CLAUDE.md 에 @AGENTS.md 추가
python3 "$CG/scripts/setup.py" emit --claude-md           # CLAUDE.md 관리 블록으로
python3 "$CG/scripts/setup.py" emit                       # .claude/rules/ 에 경로별 파일로 (--out <디렉터리>)
```

`init` 초안은 `mode: report` 입니다. `emit` 은 관리 블록 밖의 사람이 쓴 내용을 보존합니다. 규칙마다 `prevent:` 가 있으면 그 줄을, 없으면 `제목 — message 첫 문단` 을 씁니다.

## dismiss.py — 오탐 기각

후보가 위반이 아니면 고치지 말고 기각을 기록합니다. 기각은 `규칙:파일:코드 지문` 키로 남아 **그 코드가 그대로인 동안** 다시 지적되지 않습니다. 위에 줄이 추가돼 줄 번호가 밀려도 유지되고, 그 줄이 바뀌면 풀립니다.

```bash
# 훅의 차단 메시지가 보여 준 키 그대로
python3 "$CG/scripts/dismiss.py" --key core/js-no-console:src/log.js:257280dd62 --reason "CLI 출력용" --by agent
# 위치로
python3 "$CG/scripts/dismiss.py" --rule core/js-no-console --file src/log.js --line 7 --reason "CLI 출력용"
python3 "$CG/scripts/dismiss.py" --list
```

| 옵션 | 효과 |
|---|---|
| `--rule` `--file` `--line` | 기각할 위치 (그 줄을 다시 검사해 지문을 구함) |
| `--key 규칙:파일:지문` | 다시 검사하지 않고 그대로 기록 |
| `--reason "<한 줄>"` | 왜 위반이 아닌지 (필수) |
| `--by agent\|human` | 누가 판단했는지 (기본 human) |
| `--whole-file` | 이 파일 전체에서 이 규칙을 끔 |
| `--all-identical` | 같은 코드가 파일에 여러 곳 있을 때 모두 기각 |
| `--list` | 기록된 기각 목록 |

`.claude/convention-guard/dismissed.yaml` 을 커밋해 팀과 공유하세요. 팀이 합의한 예외의 기록입니다.

## log_report.py — 규칙 건강도

```bash
CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/convention-guard-develeep-convention-guard \
  python3 "$CG/scripts/log_report.py" --repo . --since 21
```

| 옵션 | 효과 |
|---|---|
| `--repo <경로>` | 이 레포에서 발생한 이벤트만 |
| `--since N` | 최근 N일 |
| `--log <경로>` | 로그 파일 직접 지정 (`log_dir` 을 바꿨을 때 `<log_dir>/firings.jsonl`) |
| `--json` | 기계가 읽을 형태 |

`CLAUDE_PLUGIN_DATA` 를 붙이지 않으면 훅과 다른 디렉터리를 읽어 비어 보입니다 ([데이터 디렉터리](installation.md#설치-위치와-데이터-디렉터리)). 숫자를 읽는 법은 [skills.md 의 rule-tune](skills.md#rule-tune--규칙-손보기)에 있습니다.

## readiness.py — 도입 점검

```bash
python3 "$CG/scripts/readiness.py"            # 전체 (~10초)
python3 "$CG/scripts/readiness.py" --quick    # 샌드박스 테스트·측정 생략 (~1초)
```

| 옵션 | 효과 |
|---|---|
| `--quick` | 설치·설정 항목만 |
| `--all` | 레포 전수조사 error 건수 포함 (큰 레포에서 느림) |
| `--commits N` | 탐지량을 잴 최근 커밋 수 (기본 20) |
| `--cwd` `--json` | 레포 경로, 기계가 읽을 형태 |

출력 한 줄이 [도입 체크리스트](production-readiness.md)의 항목 id 하나입니다. 종료 코드 `0` fail 없음 / `1` fail 있음 / `2` git 레포가 아님.

## engine.py — 구조 엔진

```bash
python3 "$CG/scripts/engine.py" status    # 설치 경로와 플랫폼. --json
python3 "$CG/scripts/engine.py" ensure    # 없으면 설치하고 끝날 때까지 기다림. --quiet
```

`--dir <디렉터리>` 로 엔진 위치를 바꿀 수 있습니다 (기본: 데이터 디렉터리의 `engine/`). `lock`·`verify-lock` 은 플러그인 개발자가 고정 휠을 갱신·검증할 때 씁니다.

## review.py — 의미 판정 배치

convention-reviewer 에이전트가 쓰는 도구입니다. 사람이 쓸 일은 판정 내역을 볼 때 정도입니다.

```bash
python3 "$CG/scripts/review.py" show    "<배치 참조>"   # 배치 보기 (--json)
python3 "$CG/scripts/review.py" summary "<배치 참조>"   # 판정 요약
python3 "$CG/scripts/review.py" record  "<배치 참조>" < verdicts.json   # 판정 기록 (리뷰어용)
```

`record` 는 후보 id 마다 `{"id": 1, "verdict": "VIOLATION", "reason": "…"}` 를 담은 JSON 배열을 stdin 으로 받습니다. 판정은 `VIOLATION`·`VALID`·`FALSE_POSITIVE` 중 하나이고, 모든 id 에 이유가 있어야 기록됩니다.

배치 참조(`<db 경로>#<번호>`)는 Stop 훅이나 `scan.py --review` 가 알려 준 문자열을 그대로 씁니다.

## CI 에 넣기

훅은 각자의 로컬 안전망이고, 팀 전체의 강제는 CI 에서 합니다. CI 에는 Claude Code 가 없으므로 플러그인 저장소를 받아 `scan.py` 를 직접 실행합니다.

```yaml
# .github/workflows/conventions.yml
on: pull_request
jobs:
  conventions:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # 없으면 base ref 가 없어 종료 코드 2
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: git clone --depth 1 https://github.com/develeep/convention-guard "$RUNNER_TEMP/cg"
      - run: python3 "$RUNNER_TEMP/cg/scripts/engine.py" ensure
      - run: >-
          python3 "$RUNNER_TEMP/cg/scripts/scan.py"
          --range "origin/${{ github.base_ref }}..HEAD"
          --fail-on error --require-engine --no-color
```

- **종료 코드를 그대로 쓰세요.** `|| true` 로 감싸면 `2`(검사 불가)가 통과로 읽힙니다. 기본 브랜치 이름을 하드코딩하지 말고 `github.base_ref` 를 씁니다.
- `engine.py ensure` 가 구조 엔진을 설치하고, `--require-engine` 이 엔진 없이 구조 조건을 건너뛴 결과를 실패(2)로 만듭니다.
- 도입 초기에는 `--fail-on never` 로 리포트만 남기고, 로그를 본 뒤 `error` 로 올립니다.
- 의미 판정 규칙을 쓴다면 `--review --fail-on-pending` 을 더합니다. CI 에는 리뷰어도 판정 캐시도 없어서, 붙이지 않으면 판정이 남은 후보가 통과로 읽힙니다. 붙이면 판정 대기 후보가 있을 때 실패하므로, 판정은 로컬 세션에서 받아 둡니다.
- 플러그인 버전을 고정하려면 `git clone` 대신 특정 커밋을 체크아웃하세요.
- `--json` 출력의 `summary.exit_code` 로 다른 도구와 연결할 수 있습니다.
