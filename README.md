# convention-guard

루프가 끝나는 시점에 **이번 변경분만** 검사해서 팀 코딩 컨벤션을 피드백하는 Claude Code 플러그인.
레포마다 언어가 다른 환경(Laravel / Next / Nest / Go …)을 전제로 만들었습니다.

- 파이썬 3.8+ 외에 의존성 없음 (PyYAML이 있으면 쓰고, 없으면 내장 파서로 폴백)
- 규칙은 **공통(core) + 레포 로컬(local)** 2층으로 병합
- `error`만 차단, `warn`은 차단에 편승해서 함께 전달

---

## 동작

```
PostToolUse(Write|Edit)   터치한 파일 경로만 큐에 적재. 컨텍스트 주입 0, 출력 0.
        ↓
Stop                      ① 루프 가드: 요청(prompt)당 1회, 연속 차단 3회까지
                          ② 후속 확인: 지난 차단이 고쳐졌는지 / 기각됐는지 기록
                          ③ 조기 탈출: 변경 없음 / git 아님 / 질문으로 끝난 턴
                          ④ 스택 감지 → 린터 위임 (변경 줄에 걸린 실패는 여기서 차단)
                          ⑤ 규칙으로 "후보" 좁히기 (줄·파일·변경집합 단위, AI 호출 없음)
                          ⑥ 예산 적용 후 block + reason 으로 주입
```

핵심 네 가지:

- **이번 변경의 책임인 것만 봅니다.** 파일 전체나 줄 전체를 무차별로 스캔하면 규칙 도입 전에
  쓰인 레거시가 매번 걸려서 일주일이면 꺼집니다. 그래서 트리거마다 "무엇을 보는가"와
  "무엇이 이번 변경의 책임인가"를 정하는 앵커가 따로 있습니다. 린터도 같은 규칙을 따릅니다 —
  출력을 파싱해 변경된 줄에 걸린 것만 차단합니다.
- **맥락이 필요한 판정도 합니다.** 파일 전체를 봐야 하는 것(다줄 패턴, "A가 있으면 B도 있어야
  한다"), 파일 사이 관계("라우트 바꿨는데 테스트 없음")까지 다룹니다.
- **훅은 판정하지 않습니다.** 정규식은 후보만 좁히고, 실제 위반인지는 에이전트가 코드를 보고
  판단합니다. 오탐이면 고치지 말고 `dismiss.py`로 이유를 남기라고 지시합니다.
- **판정의 결과를 셉니다.** 차단 하나하나가 다음 턴에 "고쳐짐 / 안 고쳐짐 / 기각됨"으로
  기록됩니다. 이 숫자가 규칙을 좁힐지 지울지를 결정합니다.

`git diff`는 변경 집합 전체에 대해 한 번만 돌립니다(200개 단위 청크). 파일당 한 번씩
돌리던 때보다 60개 파일에서 0.078초 → 0.004초입니다.

## 설치

```bash
# 마켓플레이스로 배포하는 경우
/plugin marketplace add <org>/<marketplace-repo>
/plugin install convention-guard

# 로컬에서 바로 시험
cp -r convention-guard ~/.claude/plugins/
```

설치 후 아무 레포에서:

```bash
python3 ~/.claude/plugins/convention-guard/scripts/check.py --explain
```

감지된 스택, 적용되는 규칙, 켜진 린터가 한눈에 나옵니다. **규칙 소스가 둘 이상이 되는 순간
이 명령이 없으면 디버깅이 지옥이 됩니다.** 뭔가 이상하면 항상 여기부터 보세요.

## 규칙 2층 구조

우선순위는 아래에서 위로 `core` → `user` → `local`.

| 레이어 | 위치 | id 네임스페이스 | 용도 |
|---|---|---|---|
| core | 플러그인 `rules/**` | `core/...` | 팀 공통. 릴리스로 전파 |
| user | `~/.claude/convention-rules/` | `user/...` | 개인 취향 |
| local | `<repo>/.claude/convention-rules/` | `local/...` | 레포 전용 규칙·예외 |

id에 네임스페이스가 자동으로 붙기 때문에, 나중에 공통 규칙을 추가해도 로컬 규칙과 충돌하지
않습니다. 로컬에서 공통 규칙을 건드릴 때는 반드시 `core/<id>`를 명시적으로 지목하게 됩니다.

### 로컬 커스터마이징 — 대부분 이 파일 하나로 끝납니다

`<repo>/.claude/convention-rules/config.yaml`

```yaml
disable:
  - core/js-no-console          # 이 레포에서는 끔
severity:
  core/ts-no-any: info          # 강도만 조정
exclude:
  - "legacy/**"                 # 레거시 디렉터리 통째로 제외
max_rules: 3
base_ref: auto
```

레포에 남는 파일은 이 하나 더 있습니다 — `dismissed.yaml` (오탐 기각 기록, 아래 참조).
둘 다 커밋 대상입니다. 두 파일과 `.claude/rules/` 는 규칙 스캔 대상에서 제외되므로,
설정 파일에 쓴 평문 주석이 자기 자신을 걸리게 하는 일은 없습니다.

### 조건 일부만 바꾸기 — 부분 오버라이드

정규식을 복사해 오지 않고 필요한 키만 덮어씁니다.

```yaml
# <repo>/.claude/convention-rules/override-blade-query.yaml
override: core/laravel-no-query-in-blade
severity: warn
applies_to:
  exclude: ["resources/views/admin/**"]
```

`--explain`에 `core<-local [override, error→warn]`로 표시되고, 강도를 **내린** 경우
로그에 `downgraded: true`로 남습니다. 레포가 팀 표준을 조용히 무력화하는 걸 나중에 볼 수 있게
하려는 것입니다.

### 레포 전용 규칙 추가

`id`만 새로 주면 됩니다. `local/` 접두사는 자동입니다.
`examples/repo-local/` 에 config + override + 신규 규칙 예시가 들어 있습니다.

## 규칙 파일 형식

```yaml
id: laravel-no-query-in-blade
title: Blade에서 직접 쿼리 금지
severity: error          # error=차단 / warn=차단 안 함 / info
applies_to:
  stack: [laravel]       # 감지 태그와 교집합. ["*"]는 전 스택
  files: ["**/*.blade.php"]
  exclude: ["**/vendor/**"]
  version: ">=10"        # 감지된 버전과 비교 (선택)
superseded_by:           # 이 파일이 레포에 있으면 규칙이 스스로 비활성화 (선택)
  - pint.json
triggers:
  code_regex: '...'      # 추가된 줄에서 찾을 패턴
context_injection: |
  무엇이 문제이고 대신 무엇을 할지.
tests:
  should_match: ["위반 코드"]
  should_not_match: ["비슷하지만 정상인 코드"]
```

### 트리거 여섯 종류

줄 단위만으로는 볼 수 있는 게 너무 적습니다. 그렇다고 파일 전체를 그냥 스캔하면 레거시가
매번 걸립니다. 그래서 각 트리거는 **무엇을 보는가**와 **무엇이 이 변경의 책임인지 정하는
앵커**를 따로 갖습니다.

| 트리거 | 보는 범위 | 앵커 (레거시 폭발 방지) |
|---|---|---|
| `code_regex` | 추가된 줄 | 줄 자체 |
| `file_regex` | **파일 전체** (다줄 패턴) | 매치 구간이 변경된 줄과 겹칠 때만 |
| `when_line_added` + `must_contain_in_file` | 조건은 추가된 줄, 요구사항은 **파일 전체** | 조건이 새로 추가됐을 때만 |
| `absent_in_new_file` | 새로 만든 파일 전체 | 파일이 새것일 때만 |
| `when_changed` + `require_changed` | **변경 집합 전체** | 변경 집합 자체 |
| `review_when` + `review_prompt` | 서브에이전트가 판단 | 게이트가 걸렸을 때만 (아래 참조) |

핵심은 세 번째입니다. **조건은 변경된 줄에서 찾고, 요구사항은 파일 전체에서 찾습니다.**

```yaml
# "쓰기 액션을 새로 추가했는데, 이 파일 어디에도 검증이 없다"
triggers:
  when_line_added: 'public\s+function\s+(store|update|create)\s*\('
  must_contain_in_file: '(FormRequest|->validated\(\)|Validator::make\()'
```

새 `store()` 를 추가할 때만 걸립니다. 5년 된 컨트롤러의 오타를 고치려고 파일을 열었을 때는
조건이 추가된 줄에 없으므로 조용합니다.

`file_regex`는 여러 줄에 걸친 패턴용입니다. 파일 전체를 보되 매치가 변경된 줄과 겹칠 때만
보고하므로, 기존 빈 catch 블록이 있는 파일에 무관한 한 줄을 추가해도 걸리지 않습니다.

`when_changed`/`require_changed`는 파일 사이의 관계입니다 — "라우트를 바꿨는데 테스트가
없다", "스키마를 바꿨는데 타입 정의가 그대로다". 레포마다 다르므로 로컬 규칙으로 두기 좋습니다.
이 트리거도 `applies_to` 의 스택·버전·`exclude` 를 먼저 통과해야 발동합니다.

픽스처 의미는 트리거마다 다릅니다.

| 종류 | `should_match` 에 넣을 것 |
|---|---|
| `code_regex` / `file_regex` | 위반 코드 |
| `absent_in_new_file` | 해당 선언이 **없는** 파일 본문 |
| `when_line_added`+`must_contain` | 조건은 있고 요구사항은 **없는** 파일 본문 |
| `when_changed`+`require_changed` | 변경된 경로 **목록** (`["routes/api.php"]`) |
| `review_when` | 게이트에 걸리는 코드 (판정 자체는 테스트하지 않음) |

### `superseded_by` — 포맷터가 있으면 물러나기

포맷터가 저장할 때 고쳐주는 항목을 훅이 또 지적하면 순수한 소음입니다.
`superseded_by`에 적은 설정 파일이 레포에 있으면 그 규칙은 스스로 비켜섭니다.
포맷터를 아직 안 쓰는 레포에서는 안전망으로 남습니다.

```
○ error core/php-no-var-keyword  core  [superseded by pint.json]
```

레포 config의 `respect_supersede: false`로 강제로 켤 수 있습니다.

## 스택 감지

`stacks/*.yaml`이 마커 파일로 판정하고, 매칭된 스택의 **태그를 합집합**으로 씁니다.
Next 레포는 `js, ts, react, next, next-app`을 모두 갖게 되므로 React 공통 규칙이 자연히 적용됩니다.

```yaml
id: laravel
tags: [php, laravel]
detect:
  file: composer.json
  contains: '"laravel/framework"'
  version_regex: '"laravel/framework"\s*:\s*"[^0-9]*(\d+)'
lint:
  - cmd: ["./vendor/bin/pint", "--test", "{files}"]
    if_exists: vendor/bin/pint
```

레포 1개 = 스택 1세트를 전제로 합니다(모노레포 미지원). 감지가 빗나가면 레포 config의
`stacks: [laravel]`로 강제할 수 있습니다.

## 린터 위임

**린터가 판정할 수 있는 것은 규칙으로 만들지 마세요.** 포맷·import 순서·미사용 변수는
pint / eslint / golangci-lint 가 결정론적으로 더 잘합니다. 규칙에는 린터로 표현할 수 없는
팀 관습만 담을 때 값어치가 생깁니다 — 레이어 경계, 에러 처리 패턴, API 응답 형태, 네이밍 의도.

린터가 실패하면 정규식 검사 결과보다 위에 붙습니다. `if_exists`에 지정한 바이너리가
없으면 조용히 건너뛰므로, 툴체인이 없는 레포가 차단되는 일은 없습니다.

**각 린터는 자기가 다루는 파일만 받고, 출력은 파싱해서 변경된 줄에만 적용합니다.**
`files` 글롭이 앞쪽을, `parse`가 뒤쪽을 정합니다.

```yaml
lint:
  - cmd: ["npx", "--no-install", "eslint", "--format=json", "{files}"]
    if_exists: node_modules/.bin/eslint
    files: ["**/*.{js,jsx,mjs,cjs,ts,tsx}"]
    parse: eslint-json
```

`files`가 없으면 `package.json`만 고친 턴에 eslint가 그 파일을 받아 "File ignored" 경고를
내고, 그게 차단으로 이어집니다. 린터에게 다룰 줄 모르는 파일을 건넨 것이지 컨벤션 위반이
아닙니다. 변경된 파일 중 그 린터가 가진 게 하나도 없으면 명령 자체를 건너뜁니다.

`parse`가 없으면 더 나쁩니다. `phpstan app/Legacy.php`는 그 파일 전체를 보고
`go vet ./...`은 모듈 전체를 봅니다. 5년 된 파일의 한 줄을 고치려고 열었을 때 남이 쓴
에러로 매 턴 차단되면, 규칙 트리거에 앵커를 붙인 의미가 없어집니다. 그래서 출력에서
`file:line`을 꺼내 **이번 변경이 추가한 줄과 겹치는 것만 차단**하고, 나머지는 차단하지 않고
"참고"로만 전달합니다.

| `parse` | 출력 형태 | 쓰는 곳 |
|---|---|---|
| `eslint-json` | `--format=json` | eslint |
| `phpstan-json` | `--error-format=json` | phpstan |
| `golangci-json` | `--out-format=json` | golangci-lint |
| `unix` | `file:line[:col]: message` | go vet, phpstan `--error-format=raw`, golangci-lint 기본 출력 |
| `github` | `::error file=...,line=...::msg` | biome `--reporter=github` |
| `diff` | 유니파이드 diff (`-` 쪽 줄번호) | php-cs-fixer `--diff`, pint `--test -v` |

파싱이 불가능하거나(`parse` 미지정) 파싱에 실패하면 예전처럼 출력 전체로 차단합니다.
진짜 린터 실패를 조용히 버리는 게 더 나쁜 오류이기 때문입니다. 어느 쪽인지는
`--explain`이 린터마다 알려줍니다.

```
linter : ./vendor/bin/phpstan analyse ... {files}   [parse: unix → 변경 줄만 차단]
```

`{dirs}` 플레이스홀더도 있습니다. 변경된 파일들의 디렉터리로 치환되므로,
패키지 단위로만 동작하는 도구를 레포 전체로 돌리지 않아도 됩니다.

```yaml
  - cmd: ["go", "vet", "{dirs}"]       # ./... 이 아니라 이번에 건드린 패키지만
```

경고로는 차단하지 않습니다. eslint에 `--max-warnings 0`을 붙이지 않은 것도 같은 이유입니다 —
팀이 의도적으로 남겨둔 warning 이 작업을 막으면 안 됩니다.

### presets/ — 린터 설정 원본

팀 컨벤션 문서의 포맷 항목은 규칙이 아니라 여기에 넣습니다.

```bash
cp presets/php/pint.json <repo>/pint.json
```

`presets/php/pint.json`은 PSR-12 + 팀 문서의 세부 항목(닫는 태그 생략, `declare(strict_types=1)`,
`elseif`, nullable·가변인자·캐스트 공백, import 정렬)을 담고 있습니다. 이 파일을 넣는 순간
아래 PHP 포맷 규칙 8개가 `superseded by pint.json`으로 물러납니다.

## PHP / PSR-12 규칙 구성

| 규칙 | 강도 | 포맷터가 대신 못 함? |
|---|---|---|
| `php-strict-types-required` | error | ✅ 부재 검사 — 포맷터는 risky 설정이라 흔히 꺼둡니다 |
| `php-namespace-required` | error | ✅ 부재 검사 — 포맷터가 만들어주지 않습니다 |
| `php-line-too-long` | info | ✅ 120자 초과는 사람이 끊어야 합니다 |
| `php-no-closing-tag` | error | ⬜ pint.json 있으면 물러남 |
| `php-no-short-open-tag` | error | ⬜ |
| `php-no-var-keyword` | error | ⬜ |
| `php-use-elseif` | warn | ⬜ |
| `php-control-structure-spacing` | warn | ⬜ |
| `php-nullable-type-spacing` | warn | ⬜ |
| `php-variadic-spacing` | warn | ⬜ |
| `php-cast-spacing` | warn | ⬜ |
| `php-indent-spaces` | warn | ⬜ |

`php-line-too-long`이 `info`인 이유는 Laravel 체이닝에서 오탐이 잦기 때문입니다.
info는 차단도 주입도 하지 않고 로그와 한 줄 요약에만 남습니다. 로그의 수정률을 보고
`severity: { core/php-line-too-long: warn }`으로 올리세요.

## 서브에이전트 판정 (선택)

### 먼저 정정할 것: 컨텍스트 격리는 이미 되어 있습니다

`command` 훅의 stdout은 `UserPromptSubmit` / `SessionStart` 등 일부 이벤트에서만 메인
컨텍스트로 들어갑니다. **Stop 에서는 들어가지 않습니다.** 메인 에이전트가 보는 것은
`decision: block` 의 `reason` 뿐이고, 규칙 원문·스택 정보·후보 목록은 전부 훅 안에서
소멸합니다. 그러니 "서브에이전트로 옮겨서 컨텍스트를 아낀다"는 이득은 0입니다.

### 서브에이전트가 실제로 주는 것: 판정 능력

정규식이 판정할 수 없는 것들이 있습니다. N+1 쿼리, 계층 경계, 추상화가 기존 패턴과
맞는지 — 코드 모양이 아니라 의미를 봐야 하는 것들입니다. 여기에만 LLM이 값어치를 합니다.

### 왜 전부 맡기면 안 되는가

| 문제 | 내용 |
|---|---|
| 비용 | Stop 은 **매 턴** 발생합니다. 무조건 판정하면 턴마다 LLM 1회 + 파일 읽기 |
| 지연 | 도구를 쓰는 서브에이전트는 수십 초. 훅 타임아웃과 싸우게 됩니다 |
| 비결정성 | 같은 코드에 매번 다른 판정. 컨벤션 검사에서 결정론은 미덕입니다 |
| **수렴 실패** | 정규식은 규칙 집합이 유한해 끝이 있습니다. LLM은 고칠 때마다 새로운 걸 찾아냅니다 |

마지막이 제일 위험합니다. `max_consecutive_blocks` 가 없으면 영원히 안 끝납니다.

### 그래서 2단 게이트

```
Stop ─┬─ command 훅 : 결정론 검사 (항상, 빠름)        → error 차단
      └─ agent 훅   : 1) check.py --semantic-queue 실행
                      2) EMPTY 면 즉시 {"ok": true} ← 대부분의 턴이 여기서 끝
                      3) 후보가 있을 때만 파일을 읽고 판정
                         → 확신한 것만 {"ok": false, "reason": ...}
```

**응답 스키마는 `{"ok": true}` / `{"ok": false, "reason": "..."}` 입니다.** 0.6.0 전에는
프롬프트가 `{}` 와 `{"decision": "block"}` 을 반환하게 돼 있어서, 서브에이전트가 위반을
찾아내도 판정이 조용히 버려졌습니다. `ok` 가 없는 응답은 통과로 처리됩니다.

판정 상태는 `session-<id>-semantic.json` 에 따로 저장합니다. Stop 의 훅들은 **병렬로**
실행되므로 결정론 검사와 상태 파일을 공유하면 마지막에 쓴 쪽이 상대의 차단 카운터를
지워버립니다.

`semantic` 규칙은 정규식을 **게이트로만** 씁니다. `foreach` 가 추가된 턴에만 N+1 판정이
돌고, 나머지 턴에는 Bash 한 번으로 끝납니다. 세션당 판정 횟수도 기본 1회로 묶여 있습니다.

```yaml
id: laravel-n-plus-one
severity: warn
triggers:
  review_when: '\bforeach\s*\(|->each\s*\('    # 게이트일 뿐, 판정이 아님
review_prompt: |
  반복문 안에서 Eloquent 관계에 접근해 쿼리가 N번 나가는지 판단하세요.
  이미 eager load 되어 있으면 위반이 아닙니다.
  확실하지 않으면 보고하지 마세요.
```

### 켜는 법

```bash
cp hooks/hooks.with-semantic-review.json hooks/hooks.json
```

`agent` 훅 타입은 실험적 기능입니다. 기본 설정(`hooks/hooks.json`)은 결정론 검사만 하고,
`semantic` 규칙은 로드는 되지만 아무 일도 하지 않습니다. 먼저 결정론 부분을 몇 주 굴려
로그를 쌓은 뒤에 켜시길 권합니다.

판정 모델은 `hooks.json` 의 `model` 로 지정합니다. 게이트가 대부분을 걸러주므로 가벼운
모델로 충분하고, 그래야 매 턴 돌아도 부담이 없습니다.

## 테스트 (CI에 넣으세요)

```bash
python3 tests/run_all.py                         # 전부
python3 tests/run_all.py --repo /path/repo       # 레포 로컬 오버레이까지
python3 scripts/test_rules.py                    # 규칙 픽스처만
```

`should_match` 픽스처가 없으면 실패합니다. 규칙이 100개를 넘어가면 서로 간섭하기 시작하고,
오탐 한 번이면 에이전트가 reason 전체를 형식적으로 무시하게 됩니다. 픽스처가 그걸 막는
유일한 장치입니다.

규칙 픽스처 외에 엔진 쪽 회귀 테스트가 세 개 더 있습니다. 전부 실제로 있었던 버그입니다.

| 스위트 | 지키는 것 |
|---|---|
| `tests/test_diff_anchor.py` | 무엇이 "이번 변경"인가 — 스테이징된 신규 파일, 줄번호, base_ref, `paired` 스택 게이트 |
| `tests/test_lint_anchor.py` | 린터 출력 파싱과 변경 줄 교집합 |
| `tests/test_session_policy.py` | 차단 예산, 후속 추적, 기각, `report` 모드 |

## 오탐 기각 — 판단을 숫자로 남기기

훅은 "오탐이면 고치지 말고 왜 해당하지 않는지 남기세요"라고 지시합니다. 그 판단이
채팅에만 남으면 아무것도 되지 않습니다. 로그에는 `fixed: false` 만 남고, 그건 지적을
그냥 무시한 것과 구별되지 않습니다. 수정률로 규칙을 정리하는 사이클이 정확히 이 지점에서
무너집니다.

```bash
python3 scripts/dismiss.py --rule core/php-line-too-long \
                           --file app/Http/Controllers/OrderController.php \
                           --line 84 --reason "체이닝을 끊으면 가독성이 더 나빠짐"

python3 scripts/dismiss.py --rule core/js-no-console --file scripts/seed.ts \
                           --whole-file --reason "시드 스크립트는 콘솔 출력이 인터페이스"
python3 scripts/dismiss.py --list
```

차단 reason 마지막에 이 명령이 실제 규칙 id·경로·줄번호까지 채워져서 따라옵니다.
기록은 레포에 남으므로 커밋해서 팀과 공유하세요.

`<repo>/.claude/convention-rules/dismissed.yaml`

```yaml
dismissed:
  - rule: "core/php-line-too-long"
    file: "app/Http/Controllers/OrderController.php"
    hash: "6f1c93ab24"
    reason: "체이닝을 끊으면 가독성이 더 나빠짐"
    at: "2026-09-16"
    # app/Http/Controllers/OrderController.php:84  $result = $this->repo->where(...
```

**지문은 줄 번호가 아니라 코드의 지문입니다.** 위에 줄이 추가돼도 억제가 유지되고,
그 코드 자체가 바뀌면 다시 지적됩니다 — 바뀐 코드는 새 판단이기 때문입니다.
`hash` 를 지우면(`--whole-file`) 그 파일에서 규칙 전체가 꺼집니다.

`dismiss.py` 는 훅과 **같은 엔진으로 다시 스캔**해서 그 위치의 지문을 만듭니다. 그래서
지문이 어긋날 일이 없고, 코드가 이미 바뀌었다면 기각할 것이 없다고 알려줍니다.

감사할 때는 `scan.py --no-dismiss` 로 기각분까지 전부 볼 수 있습니다.

## 규칙 개선 사이클

모든 발동이 `${CLAUDE_PLUGIN_DATA}/firings.jsonl`에 쌓입니다.

```json
{"event":"match","rule_id":"core/ts-no-any","severity":"warn","shown":true,"source":"core"}
{"event":"followup","rule_id":"core/ts-no-any","file":"src/a.ts","fixed":false}
{"event":"followup","rule_id":"core/ts-no-any","file":"src/b.ts","dismissed":true}
{"event":"dismissed","rule_id":"core/ts-no-any","file":"src/b.ts","reason":"외부 SDK 타입이 any"}
{"event":"lint","cmd":"./vendor/bin/phpstan analyse ...","anchored":true,"blocking":false}
```

`followup`은 차단 하나하나에 대해 **다음 Stop 시점에 딱 한 번** 기록됩니다. 위치(규칙 +
파일 + 코드 지문) 단위라, 같은 규칙이 다른 파일에서 새로 걸린 것은 "안 고쳐진 지적"으로
세지 않습니다. 정기적으로 이렇게 보세요.

```bash
python3 scripts/log_report.py
```

```
규칙                                       강도   발동  표시     수정률  기각  판정
core/php-line-too-long                     info    41     0  12% (2/17)    6  오탐 확정 — 팀이 기각함
core/laravel-controller-needs-validation   error    9     9   89% (8/9)    0  건강함

린터  (실패 / 그중 차단 / 출력 파싱 성공)
  ./vendor/bin/phpstan analyse --no-progress ...      12 /    3 /   12
```

수정률은 **지적한 뒤 다음 턴에 그 지적이 실제로 사라진 비율**이고, 기각은 **에이전트나
사람이 "이 경우는 위반이 아니다"라고 판단해 남긴 건수**입니다. 두 숫자를 나눠 놓은 이유가
있습니다 — 예전에는 오탐을 올바르게 거절한 것과 지적을 그냥 무시한 것이 로그에서 똑같이
`fixed: false` 로 보였습니다.

**기각이 많은 규칙 = 오탐. 기각 없이 수정률만 낮은 규칙 = 팀이 동의하지 않는 규칙.**
앞쪽은 조건을 좁히고, 뒤쪽은 지우세요. `rule-tune` 스킬이 이 구분을 대신 해 줍니다.
규칙 5개로 시작해 로그를 보고 늘리는 편이, 30개로 시작하는 것보다 거의 항상 낫습니다.

린터 표에서 "출력 파싱 성공"이 실패 건수보다 적으면, 그 린터는 변경 줄로 좁혀지지 않아
출력 전체로 차단하고 있다는 뜻입니다. 규칙이 아니라 `stacks/*.yaml` 의 `parse` 를 보세요.

## 설정

플러그인 기본값은 `config.yaml`, 레포별 덮어쓰기는 `.claude/convention-rules/config.yaml`.

| 키 | 기본값 | 설명 |
|---|---|---|
| `max_rules` | 4 | 한 번에 주입할 error 규칙 상한 |
| `max_warns` | 3 | 차단 시 함께 보낼 warn 상한 |
| `max_consecutive_blocks` | 3 | **연속** 차단 상한. 차단하지 않은 턴이 한 번 나오면 0으로 초기화됩니다. 요청당 1회 차단은 `prompt_id` 가드가 이미 보장하므로, 이 값은 루프 방지 전용입니다. 상한에 걸려도 로그와 한 줄 요약은 계속 남습니다 |
| `once_per_session` | true | 같은 규칙 재발동 억제. **안 고쳐진 지적은 예외적으로 한 번 더** 올라오고, **오탐으로 기각한 건은 이 예산을 쓰지 않습니다** |
| `run_linters` | true | 스택별 린터 위임 (출력 파싱 후 변경 줄에만 적용) |
| `base_ref` | `''` | `auto`면 기본 브랜치와의 merge-base diff를 HEAD diff와 **합집합**으로 씁니다 (세션 중 커밋한 변경까지 검사). `origin/HEAD` 를 먼저 물어보고 없을 때만 main/master 를 추측합니다 |
| `skip_if_question` | true | 질문으로 끝난 턴은 검사 생략 |
| `respect_supersede` | true | `superseded_by` 설정 파일이 있으면 해당 규칙 비활성화 |
| `block_level` | `error` | `report` 면 기록만 하고 차단하지 않음 |
| `semantic_review` | false | 서브에이전트 심층 판정 |
| `max_semantic_rules` | 2 | 한 번에 서브에이전트에 맡길 규칙 상한 |
| `max_semantic_reviews_per_session` | 1 | 세션당 서브에이전트 판정 횟수 |

## 세션 시작 컨텍스트 주입 (선택)

훅은 **쓰고 난 뒤** 잡습니다. 되돌리는 비용이 큰 규칙은 **쓰기 전에** 알고 있는 편이 낫습니다.

```bash
python3 scripts/emit_rules.py --stdout   # 미리보기
python3 scripts/emit_rules.py            # .claude/rules/ 에 생성
```

### 전부 넣으면 안 되는 이유

이 플러그인이 존재하는 이유가 "긴 규칙 목록은 Lost in the Middle 로 묻힌다"입니다.
규칙 37개를 CLAUDE.md 에 쏟아붓는 건 정확히 그 안티패턴이고, 게다가 그중 대부분은
훅이 이미 잡습니다. 그래서 **역할을 나눕니다.**

| | 컨텍스트 | 훅 |
|---|---|---|
| 역할 | 예방 — 쓰기 전에 안다 | 검출 — 쓰고 나서 잡는다 |
| 대상 | 잡힌 뒤 고치는 비용이 큰 것 | 기계적으로 판정되는 것 |
| 예 | 검증 계층 누락, `'use client'`, N+1, 계층 경계 | 포맷, 디버그 잔여물, 네이밍 |

내보내는 대상은 `semantic` 규칙(정규식 판정 불가라 예방이 유일한 수단)과
`in_context: true` 로 표시한 소수뿐입니다. 기본 예산은 파일당 12개입니다.

### paths 스코핑

`.claude/rules/*.md` 는 `paths:` 프론트매터를 지원해서 **해당 파일을 읽을 때만**
컨텍스트에 들어갑니다. 생성기는 규칙의 `files` 글롭을 모아 이걸 자동으로 붙입니다.

```markdown
---
paths:
  - "app/**/*.php"
  - "database/migrations/**/*.php"
---
# PHP 컨벤션 — 쓰기 전에 알아야 할 것

- 쓰기 액션(store/update/create)은 FormRequest 로 받고 $request->validated() 를 쓰세요.
- 마이그레이션에는 반드시 down() 을 함께 구현하세요.
```

PHP 규칙은 PHP 파일을 건드릴 때만 들어갑니다. 세션 시작 비용이 거의 없고,
Next 레포에서 Laravel 규칙을 읽을 일도 없습니다.

### 규칙에 표시하기

```yaml
in_context: true
context_line: 쓰기 액션(store/update/create)은 FormRequest 로 받고 $request->validated() 를 쓰세요.
```

`context_line` 은 **명령형 한 줄**로 쓰세요. `context_injection` 은 "~가 없습니다" 같은
사후 지적문이라 예방용으로는 어색합니다. 없으면 `context_injection` 첫 줄로 대체됩니다.

### 다른 출력 형태

```bash
python3 scripts/emit_rules.py --claude-md   # CLAUDE.md 관리 블록으로
python3 scripts/emit_rules.py --hook        # SessionStart 훅 JSON 으로
```

`--claude-md` 는 경로 스코핑이 없어 **매 세션 전부 로드**됩니다. 한 파일로 모아 리뷰하고
싶을 때만 쓰세요. `--hook` 은 파일 없이 항상 최신 규칙을 주입합니다 (SessionStart 는
command 훅 stdout 이 컨텍스트로 들어가는 몇 안 되는 이벤트입니다).

```json
{"hooks": {"SessionStart": [{"hooks": [
  {"type": "command",
   "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/emit_rules.py\" --hook"}
]}]}}
```

파일 방식은 PR 에서 보이고 플러그인 없는 사람에게도 문서가 됩니다.
훅 방식은 드리프트가 없습니다. 팀 상황에 맞는 쪽을 고르세요.

### 재생성과 수기 내용

관리 블록(`<!-- convention-guard:begin -->` ~ `end`) 안만 교체되므로 밖에 쓴 내용은
보존됩니다. HTML 주석은 컨텍스트 주입 전에 제거되므로 마커 자체는 토큰을 쓰지 않습니다.

## 줄바꿈 형식

이 레포의 텍스트 파일은 **CRLF** 로 고정되어 있습니다. `.gitattributes` 가 그걸 유지합니다 —
이 파일이 없으면 각자의 `core.autocrlf` 설정에 따라 체크아웃할 때 조용히 LF 로 돌아갑니다.

```
* text=auto eol=crlf
```

세 가지만 알아두세요.

- **스크립트는 `python3 <경로>` 로 실행합니다.** 훅·스킬·문서가 전부 이 형태이고, CRLF 때문에
  shebang 직접 실행(`./scripts/scan.py`)은 macOS·Linux 에서 동작하지 않습니다.
  오해를 줄이려고 실행 비트는 떼어 두었습니다.
- **규칙 YAML 은 양쪽 다 읽습니다.** 내장 파서가 CRLF 를 정규화하고, PyYAML 도 그대로 처리합니다.
  두 파서가 50개 설정 파일에서 동일한 결과를 내는 것을 확인했습니다.
- **`emit_rules.py` 가 생성하는 `.claude/rules/*.md` 는 대상 레포의 형식을 따릅니다.**
  이 플러그인의 형식과 무관합니다.

macOS·Linux 에서 스크립트를 직접 실행해야 한다면 `.gitattributes` 에서 `*.py` 만 예외로 두세요.

```
*.py text eol=lf
```

## 마켓플레이스 배포

### 필요한 파일 두 개

```
convention-guard/
└── .claude-plugin/
    ├── plugin.json        # 플러그인 자기 설명
    └── marketplace.json   # 배포 카탈로그 (마켓플레이스 레포에 둡니다)
```

`skills/` · `commands/` · `agents/` · `hooks/hooks.json` 은 **자동 발견**되므로
`plugin.json` 에 적을 필요가 없습니다. 적으면 `skills` 는 추가로 스캔되고
`commands`·`agents` 는 기본 디렉터리를 **대체**하므로, 잘못 적으면 오히려 사라집니다.

### marketplace.json

**필수 필드는 `name` · `owner` · `plugins` 셋입니다.** `owner` 는 객체이고 그 안의 `name` 이
필수입니다. 빠지면 마켓플레이스 추가 자체가 `owner: Invalid input` 으로 실패합니다.

```json
{
  "name": "develeep-convention-guard",
  "owner": { "name": "shlee" },
  "plugins": [
    { "name": "convention-guard", "source": "./" }
  ]
}
```

플러그인 항목은 `name` 과 `source` 가 필수입니다. `source` 형태는 **마켓플레이스 레포와
플러그인이 같은 레포인지**에 따라 갈립니다.

| 상황 | `source` | 비고 |
|---|---|---|
| 이 레포가 곧 플러그인 (현재 설정) | `"./"` | 레포 루트에 `.claude-plugin/` 둘 다 있음 |
| 한 마켓플레이스에 플러그인 여러 개 | `"./plugins/<이름>"` | 서브디렉터리 경로 |
| 플러그인이 다른 레포에 | `{"type":"git","url":"...","ref":"v0.5.2"}` | 태그로 버전 고정 |
| 아티팩트 서버의 zip | `{"type":"archive","url":"...","hash":"sha256:..."}` | 릴리스마다 해시 갱신 필요 |

```bash
/plugin marketplace add develeep/convention-guard
/plugin install convention-guard
```

수정한 뒤에는 캐시된 마켓플레이스를 갱신해야 반영됩니다.

```bash
/plugin marketplace update develeep-convention-guard
```

### userConfig — 설치한 사람이 고르는 것

레포 `config.yaml` 이 **팀 설정**이라면 `userConfig` 는 **이 설치의 개인 설정**입니다.
설치할 때 UI 로 물어보고, 훅에는 `CLAUDE_PLUGIN_OPTION_<KEY>` 환경변수로 전달됩니다.

| 키 | 값 | 효과 |
|---|---|---|
| `report_only` | boolean | 켜면 지적을 기록만 하고 차단하지 않습니다 (내부적으로 `block_level: report`) |
| `semantic_review` | boolean | 서브에이전트 심층 판정 (agent 훅을 쓸 때만) |
| `log_dir` | 디렉터리 | `firings.jsonl` 위치. 팀 로그를 한곳에 모을 때 |

**우선순위는 `플러그인 기본값 < userConfig < 레포 config.yaml`** 입니다.
레포에 커밋된 팀 설정이 이기므로, 한 사람이 조용히 팀 표준을 낮출 수 없습니다.
레포가 말이 없는 항목에서만 개인 설정이 적용됩니다.

`log_dir` 은 로그 파일만 옮깁니다. 세션 상태는 플러그인 데이터 디렉터리에 남으므로,
공유 로그 경로를 써도 다른 사람의 진행 중인 세션과 충돌하지 않습니다.

### 릴리스 체크리스트

```bash
python3 tests/run_all.py               # 픽스처 + 엔진 회귀
python3 -m compileall -q scripts       # 문법
```

1. `plugin.json` 의 `version` 올리기
2. `source` 가 `git` 타입이면 `ref` 를 같은 태그로 (`"./"` 면 불필요)
3. 태그 푸시
4. 설치한 쪽에서 `/plugin marketplace update develeep-convention-guard`

## 함께 오는 스킬 4개

플러그인에 번들되어 있어 설치하면 바로 뜹니다.

| 스킬 | 언제 | 하는 일 |
|---|---|---|
| `convention-setup` | 새 레포에 도입할 때 | 레포 구조·린터·레거시 규모를 실제로 측정해 `config.yaml` 초안 작성 |
| `convention-check` | 커밋·PR 직전 | 훅 없이 지금 검사. 오탐을 걸러 정리해서 보고 |
| `rule-add` | 리뷰 지적이 반복될 때 | 트리거 종류를 고르고 정규식·픽스처를 짜서 테스트까지 |
| `rule-tune` | 2~3주에 한 번 | 로그 수정률로 오탐 규칙을 찾아 좁히거나 승격·삭제 |

`convention-setup` 은 마지막 단계에서 `.claude/rules/` 생성까지 해줍니다.

네 개가 한 사이클입니다. `setup` 으로 켜고 → `check` 로 확인하며 쓰고 →
리뷰에서 나온 것을 `add` 로 규칙화하고 → `tune` 으로 쓸모없는 것을 걷어냅니다.

## 훅 없이 실행하기

```bash
P=~/.claude/plugins/convention-guard/scripts/scan.py

python3 "$P"                          # 워킹 트리
python3 "$P" --staged                 # 커밋 직전
python3 "$P" --range main..HEAD       # PR 올리기 전
python3 "$P" --files app/X.php        # 지정 파일 전체
python3 "$P" --all                    # 레포 전수조사 (레거시 감사)
python3 "$P" --base-ref auto          # 세션 중 커밋한 변경까지 함께
python3 "$P" --no-dismiss             # 기각 기록을 무시하고 전부
```

Stop 훅과 **같은 엔진**(`lib/engine.py`)을 씁니다. 수동 실행과 자동 실행이 다른 답을 내면
아무도 안 믿게 되므로 로직을 공유합니다.

`--all` 만 예외적으로 모든 파일을 "새 파일"로 취급해 부재 검사까지 적용합니다.
레거시 감사가 목적이므로 그게 맞고, 그래서 명시적으로 켜야 합니다.

### CI

```yaml
- run: |
    python3 plugins/convention-guard/scripts/scan.py \
      --range origin/$BASE_REF..HEAD \
      --fail-on error --no-color
```

`--fail-on`: `error`(기본) / `warn` / `info` / `never`. 도입 초기에는 `never` 로
리포트만 남기다가 로그가 쌓이면 올리세요.

## 알려진 한계

- **모노레포 미지원.** 레포 루트에서 한 번만 스택을 판정합니다. 한 레포에 Next + Nest가 섞여
  있으면 양쪽 규칙이 모두 켜집니다. 필요해지면 `stack.py`의 판정을 파일 경로 기준으로 올리고
  `applies_to.files`로 나누는 방향이 맞습니다.
- **정규식은 결국 정규식입니다.** `file_regex` 로 다줄 패턴까지는 잡지만, 타입 추론이나
  호출 그래프가 필요한 판정은 못 합니다. 그건 AST 린터(phpstan, tsc, golangci-lint)나
  `semantic` 규칙의 몫입니다.
- **세션 중 커밋한 변경.** 기본값은 `HEAD` 기준 diff라 이미 커밋된 변경은 보이지 않습니다.
  `base_ref: auto` 로 바꾸면 merge-base diff를 HEAD diff와 합집합으로 봅니다 — 같은 파일에
  미커밋 변경이 함께 있어도 커밋된 쪽이 빠지지 않습니다.
- **Stop은 "작업 완료"가 아니라 "턴 종료"입니다.** 질문 휴리스틱과 변경 없음 조기 탈출로
  대부분 걸러지지만, 완벽하지는 않습니다.