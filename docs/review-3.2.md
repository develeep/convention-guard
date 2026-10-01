# convention-guard 탐색·판정 로직 리뷰 (master HEAD `889c2f9`, 3.2.0)

- 분석 대상: `git archive HEAD` 사본. 작업 트리의 커밋되지 않은 변경은 보지 않았습니다. 그 변경에는 `foreign-<session>.jsonl` 기준선, 수정된 `hooks.json`·`scope.py`·`state.py` 가 들어 있습니다.
- 인용은 전부 `경로:줄` 형식이고 HEAD 사본 기준입니다.
- 재현 파일은 모두 세션 스크래치패드 `…/scratchpad/` 아래에 있습니다. 경로는 항목마다 적었습니다.
- 재현 파일의 절대 경로: `/tmp/claude-0/-root-convention-guard/e544610c-456f-4d16-b4d5-624f824704c9/scratchpad/` (이 리뷰 세션의 임시 디렉터리라 지워졌을 수 있습니다. 없으면 각 항목의 재현 설명을 보고 다시 만드세요)
- 사용자에게 확인받은 의도 네 가지를 반영했습니다.
  1. 필수 요소 탐색에서 주석은 **제외**합니다.
  2. 연속 차단 상한은 **요청 안의 루프 가드**입니다.
  3. `in_scope` 는 **본문만** 루프 안으로 봅니다.
  4. 의미 판정은 **함수 단위를 유지**하고, 그 안의 후보는 전부 보여 줍니다.

---

## 1. 현재 동작 방식

### 1.1 수집 (Pre/PostToolUse → `collect.py`)

| 단계 | 입력 → 출력 | 위치 |
|---|---|---|
| 훅 연결 | PreToolUse 는 **Bash 만**, PostToolUse 는 `Write\|Edit\|MultiEdit\|NotebookEdit\|Bash` | `hooks/hooks.json:4-27` |
| 어댑터 | stdin JSON 을 받아 `hook_event_name` 으로 분기합니다. 예외가 나도 삼키고 종료 코드는 0 입니다 | `scripts/collect.py:17-29` |
| 루트 | `CLAUDE_PROJECT_DIR` 가 있으면 그것, 없으면 payload `cwd` 를 쓰고 `git rev-parse --show-toplevel` 로 확정합니다 | `scripts/lib/paths.py:24-47` |
| Pre(Bash) | 세션 최초 HEAD 를 기록합니다(O_EXCL 이라 처음 값이 유지됨). **현재 HEAD** 기준 dirty 파일의 sha1 을 스냅샷으로 남깁니다 | `scripts/lib/hooks.py:56-67`, `scripts/lib/state.py:71-83`, `scripts/lib/gitdiff.py:72-93` |
| Post(Bash) | 스냅샷을 읽습니다(없으면 기록하지 않고 끝). **세션 base** 기준 변경 파일 중 sha 가 달라진 것만 `touched-<sid>.txt` 에 덧붙입니다 | `scripts/lib/hooks.py:91-105`, `scripts/lib/state.py:130-152` |
| Post(편집 도구) | 입력의 `file_path` 계열 키와 `edits[]` 에서 경로를 뽑아 루트 기준 상대 경로로 바꾸고, `..` 로 시작하면 버립니다. 기록 단위는 **파일**입니다 | `scripts/lib/hooks.py:70-81`, `:106-115` |

### 1.2 Stop 훅 → 범위(ChangeScope)

| 단계 | 내용 | 위치 |
|---|---|---|
| 어댑터 | GC 를 돌린 뒤 `hooks.on_stop` 을 부릅니다. 예외는 `systemMessage "건너뜀 — 내부 오류"` 로 바꿉니다 | `scripts/check.py:17-35` |
| 분기 | ① 설정 오류 ② 다른 요청의 열린 사이클이면 abandoned 로 닫음 ③ 열린 사이클이면 `_verify` ④ 질문으로 끝난 턴이면 건너뜀 ⑤ 그 밖에는 `_open` | `scripts/lib/hooks.py:261-302` |
| 범위 | touched 목록, 설정 base_ref, 세션 base 를 모읍니다(현재 HEAD 와 같은 ref 는 버림). 그다음 `ChangeScope.from_touched` 를 호출합니다 | `scripts/lib/hooks.py:321-343`, `scripts/lib/scope.py:69-73` |
| 추가된 줄 | untracked 파일은 전체를 읽습니다. 나머지는 ref 마다 `git diff -U0 --no-renames` 를 200개씩 묶어 돌리고, `+` 줄만 워킹 트리 줄 번호로 합칩니다 | `scripts/lib/gitdiff.py:230-268`, `:210-227`, `:169-207`, `:29-30` |
| 새 파일 | untracked 이거나 index 가 HEAD 대비 새로 추가한 파일입니다 | `scripts/lib/gitdiff.py:105-120` |
| 필터 | `SKIP_EXT` 확장자와 400KB 초과 파일은 범위에서 뺍니다 | `scripts/lib/gitdiff.py:20-25`, `:130-137`, `scripts/lib/scope.py:32-33` |
| 파일 본문 | 어느 범위든 **워킹 트리**를 읽습니다 | `scripts/lib/scope.py:53-56`, `scripts/lib/gitdiff.py:140-148` |
| 기타 범위 | `scan.py` 가 staged/range/files/all 로 같은 클래스를 만듭니다 | `scripts/lib/scope.py:75-135` |

### 1.3 파이프라인

`pipeline.run` 한 곳에서 처리합니다(`scripts/lib/pipeline.py:52-98`).

- **순서**: 스택 감지(`scripts/lib/stack.py`) → 규칙 로드(core, user, local 레이어 → 오버라이드 → 프리셋 → disable) → 기각 로드(파싱 오류는 error 노트) → 린터(변경된 줄에 걸린 것만 차단, `scripts/lib/lint.py`) → 적용 필터(스택·버전·supersede·files 글롭, `scripts/lib/rules/select.py:86-103`) → `detect.run` 두 번(결정론 규칙, 의미 판정 규칙).
- **순서의 결정성**: 규칙·파일 순회는 정렬돼 있고 결과 정렬도 안정 정렬이라 같은 입력이면 같은 순서가 나옵니다(`scripts/lib/detect.py:243-252`).

### 1.4 탐지와 앵커 (`scripts/lib/detect.py:129-240`)

`add()` 는 다음 순서로 동작합니다(`:137-151`).

1. Candidate 를 만듭니다.
2. 기각 여부를 봅니다.
3. 구조 조건이 있을 때만 구조 판정을 합니다. REJECT 면 버리고, UNKNOWN 이면 후보를 남긴 채 "구조 미확인"으로 기록합니다.

| 앵커 | 판정 | 위치 |
|---|---|---|
| line | 추가된 줄마다 `compiled_when.search` 로 **첫 매치 하나**만 봅니다 | `:176-184` |
| absent | 새 파일에서 `added_body` 에 필수 요소가 없으면 후보입니다 | `:186-193` |
| file | 워킹 트리 본문에서 `finditer` 로 찾고, 매치 줄 범위가 변경된 줄과 겹쳐야 후보입니다 | `:195-215` |
| requires | 파일 전체 **원문**에서 필수 요소를 찾고, 추가된 줄의 트리거 중 첫 것을 후보로 냅니다 | `:217-238` |
| paired | 변경 집합에 A 는 있고 B 는 없을 때 후보입니다 | `:153-170` |

- **후보 키**: `규칙:파일:sha1(공백 정규화한 clip 스니펫)[:10]`. 스니펫은 strip 한 뒤 120자로 자릅니다(`scripts/lib/candidate.py:22-30`, `:42`, `:47-50`).
- **기각 매칭**: `(rule, file)` 또는 `(rule, file, hash)` 가 정확히 일치해야 합니다(`scripts/lib/dismiss.py:54-55`, `:86-98`).

### 1.5 구조 조건 필터 (`scripts/lib/structure/`)

- **분석과 캐시**: `analyze(text, lang)` 는 sha1 을 키로 프로세스 안에서만 캐시합니다(`scripts/lib/structure/__init__.py:36-50`).
- **마스킹**: 스택 상태 기계가 주석·문자열·정규식 리터럴·태그 밖 텍스트를 구간으로 표시합니다(`scripts/lib/structure/native/mask.py`). 실패하면 `ok=False` 가 됩니다.
- **정규식 리터럴 판별**: 앞 글자가 `_REGEX_AFTER_PUNCT` 에 있거나, 앞 단어가 `_REGEX_AFTER_WORD` 에 있어야 정규식으로 봅니다(`mask.py:56-61`, `:278-296`).
- **블록 트리**: 코드 영역의 `{` 마다 헤더를 뽑습니다. 헤더 시작점은 괄호 깊이 0 의 직전 `;{}` 이고, 최대 12줄까지만 거슬러 올라갑니다(`scripts/lib/structure/native/scopes.py:159-203`).
- **블록 분류**: `_classify` 가 헤더를 catch 키워드 → class 키워드 → 반복 메서드 이름 → 함수 정규식 → loop 키워드 → branch 키워드 순서로 봅니다. 각 단계는 헤더 **어디서든** `search` 합니다(`scopes.py:245-272`).
- **언어 정의**: 키워드와 정규식은 `langs.py` 에 데이터로 있습니다(`scripts/lib/structure/native/langs.py:19-47`, `:119-234`). 단 Python 헤더만은 `scopes.py:36` 에 하드코딩돼 있습니다.
- **조건 평가** (`scripts/lib/structure/conditions.py:37-106`): `not_in` 은 구간 포함으로 판정합니다. `in_scope` 는 **줄 번호**로 스코프 사슬을 모아 AND 로 판정합니다(`scripts/lib/structure/model.py:175-186`). `block_empty` 는 가장 안쪽 블록 본문이 공백뿐인지 봅니다. 결론의 우선순위는 REJECT > UNKNOWN > ACCEPT 입니다.

### 1.6 의미 판정 (`scripts/lib/semantic.py`, `scripts/lib/context.py`)

- **진입 조건**: `semantic_on` 이 켜져 있고 `semantic_hits` 가 있으면 `triage` 합니다(`scripts/lib/hooks.py:354-356`).
- **컨텍스트 팩**: 감싸는 함수(구조 계층의 `innermost`)를 쓰고, 못 찾으면 ±30줄로 대신합니다. 여기에 imports(`IMPORT_RE`), 변경 hunk, 관련 파일(심볼 정규식 → 글롭 → 앞 60줄)을 붙입니다(`scripts/lib/context.py:142-233`).
- **캐시 키**: `review_hash = fingerprint(definition_hash|context_hash|related_hash)` 이고 캐시 키는 `rule:file:review_hash` 입니다(`scripts/lib/semantic.py:89-93`, `scripts/lib/candidate.py:52-59`).
- **분류**: 캐시가 VIOLATION 이면 지적, VALID 나 FALSE_POSITIVE 면 제외, 없으면 배치에 넣습니다. 배치에서 같은 `review_key` 는 한 번만 묻습니다(`scripts/lib/semantic.py:123-142`, `:153-188`).
- **리뷰어**: 리뷰어는 `review.py show` 로 배치를 보고 판정한 뒤 `record` 로 기록하며, 기록은 캐시에 합쳐집니다(`scripts/review.py`, `scripts/lib/semantic.py:68-78`).

### 1.7 검증 사이클과 기각

- **`_open`** (`scripts/lib/hooks.py:535-628`)
  - `once_per_session` 으로 이미 정리된 규칙은 뺍니다(`:360-361`).
  - 표시 예산을 적용합니다: 규칙당 3개, error 규칙 4개, warn 규칙 3개(`:553-557`).
  - 차단 여부는 `has_blocking ∧ ¬report ∧ streak < cap` 입니다(`:565-568`).
  - `opened` 에는 **표시한 후보만** 넣고, `seen` 에는 현재 후보를 전부 넣습니다(`:609-612`).
- **`_verify`** (`scripts/lib/hooks.py:484-532`) → `classify` (`scripts/lib/cycle.py:71-86`)
  - `opened ∩ current` 는 still, 빠졌는데 기각됐으면 dismissed, 빠졌으면 fixed, `current − seen − opened` 는 new 입니다.
  - error 가 남으면 `max_verify_attempts` 까지 다시 차단합니다.
- **`_close`** (`scripts/lib/hooks.py:445-464`)
  - `fired_rules` 는 규칙 단위로 정리합니다.
  - 남은 차단 대상이 없을 때만 연속 차단 수를 0 으로 되돌립니다.

---

## 2. 추천 (우선순위 순)

재현 경로의 약칭은 다음과 같습니다.

| 약칭 | 경로 | 영역 |
|---|---|---|
| `M` | `scratchpad/repro-main/` | 직접 재현 |
| `COL` | `scratchpad/repro-collect/` | 수집·범위 |
| `DET` | `scratchpad/repro-detect/` | 탐지·앵커 |
| `STR` | `scratchpad/repro-structure/` | 구조 계층 |
| `SEM` | `scratchpad/repro-semantic/` | 의미 판정 |
| `CYC` | `scratchpad/repro-cycle/` | 검증 사이클 |

서브에이전트가 재현한 항목은 이 보고서에 넣기 전에 직접 코드를 열고, 핵심 재현을 다시 돌려 확인했습니다.

### R1. 블록 종류(loop·class·catch)를 헤더 안 키워드·메서드명 목록으로 판별한다

- **영역**: 구조 인식 계층 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - `_classify` 는 헤더 문자열 **어디서든** 다음 목록을 `search` 합니다(`scripts/lib/structure/native/scopes.py:236-272`).
    - `class_keywords`, `catch_keywords`, `loop_keywords`, `branch_keywords`(`scripts/lib/structure/native/langs.py:131-215`)
    - 반복 메서드 이름 목록 `ITERATION_CALLS`(`langs.py:23-29`)
  - 키워드 경계는 `(?<![\w$])` 뿐이라 멤버 접근(`.class`, `::class`, `->for(`)을 막지 못합니다(`scopes.py:241`).
  - 헤더 시작점은 직전 `;` 입니다(`scopes.py:186-203`).
  - Python 은 `_PY_HEADER`(def/class/except)만 인식합니다(`scopes.py:36`).
- **문제**: 기준 4(하드코딩 탐색)에 그대로 해당하고, 그 결과 기준 1~3 을 모두 해칩니다.
  - **미탐**
    - Go 3절 `for i := 0; i < n; i++ {` 는 헤더가 `i++` 로 잘려 loop 가 아닙니다.
    - Python 에는 loop 개념이 없어 `in_scope: loop` 가 **항상 REJECT** 입니다. UNKNOWN 도 아니라서 조용한 통과가 됩니다.
    - Kotlin `items.forEach {` 는 loop 가 아닙니다.
    - **core `laravel-n-plus-one`** 에서 `foreach ([User::class, Post::class] as $m) {` 는 `::class` 때문에 class 로 분류되고, loop 판정은 REJECT 입니다.
  - **오탐**
    - JS `repo.find({ where: … })` 는 `find` 가 목록에 있어 loop 가 됩니다.
    - `if (xs.some(x => x.ok)) {` 도 loop 가 됩니다.
    - `if (n.class === "a") {` 는 class 가 됩니다.
    - `.catch(cb)`, `.finally(cb)` 는 catch 가 됩니다.
  - **불안정**: 세미콜론 없는 JS 에서 직전 줄에 `users.map(...)` 이 있으면 다음 `if {` 가 loop 가 됩니다. `;` 를 붙이면 판정이 뒤집힙니다(STR `repro5.py`).
- **재현**: `M/struct_repro.py` 20건 중 7건이 기대와 다릅니다. 아래 사례는 모두 직접 재실행했습니다.

  | 사례 | 기대 | 실제 |
  |---|---|---|
  | Go 3절 for | accept | reject |
  | Python for / while | accept | reject |
  | Kotlin forEach | accept | reject |
  | JS `repo.find({` | reject | accept |
  | PHP `::class` foreach | accept | reject |
  | `if (xs.some(..)) {` | reject | accept |

- **제안** (표준 라이브러리)
  - (a) **정규식 보강**: lookbehind 를 `(?<![\w$.:>])` 로 넓히고, 키워드를 문장 시작에 앵커합니다. 싸지만 목록은 그대로 남아 새 형태마다 정규식을 또 손봐야 합니다.
  - (b) **헤더 토크나이저 + 언어별 데이터 필드** ← **선택**
    - 이미 마스킹된 헤더를 식별자·구두점·연산자 토큰으로 자릅니다. 분류는 **첫 유효 토큰**(라벨·수식어는 건너뜀)과 **`{` 바로 앞 토큰 모양**으로 합니다.
    - 멤버 연산자(`. -> :: ?.`) 바로 뒤의 단어는 키워드로 보지 않습니다.
    - 반복 호출은 "`{` 가 아직 닫히지 않은 `(` 안에 있고, 그 `(` 앞이 `.name`/`->name` 인 경우"로만 인정합니다. 예: `xs.map(x => {`. `if (xs.some(..)) {` 는 `(` 가 닫혀 있어 제외됩니다.
    - `langs.py` 에 추가할 데이터 필드: `statement_keywords={kind:[…]}`, `modifiers`, `member_ops`, `lambda_heads`, `newline_ends_statement`(Go·Kotlin·Swift). 마지막 필드로 Go 의 `;` 절단도 해결합니다.
  - (c) **블록 트리의 괄호 스택 활용**: `_brace_blocks` 가 `{` 마다 열린 `(` 스택을 기록하게 해서 "호출 인자 안의 블록"을 구조로 압니다. (b) 의 반복 호출 판정을 이 방식으로 구현합니다.
  - **Python**: 표준 라이브러리 `ast` 를 1차 백엔드로 씁니다. `lineno`/`end_lineno` 로 For/While/Try/FunctionDef/Lambda/컴프리헨션 범위를 정확히 얻습니다. `SyntaxError` 가 나면 (b) 방식의 들여쓰기 규칙으로 폴백합니다. 1,100줄 기준 `ast.parse` 는 5.8ms 입니다(STR `perf.py`).
- **선택 이유**: (b)+(c) 하나로 K1~K10 을 함께 고칩니다. "언어 추가 = 데이터 한 줄"이라는 원칙(`langs.py:3-5`)을 지키고, Python 하드코딩(`scopes.py:36`)도 데이터로 옮깁니다. 비용은 헤더 길이에 선형입니다.
- **트레이드오프**
  - 판정이 바뀌므로 패리티 골든을 `--update` 하고, 같은 커밋에서 diff 를 설명해야 합니다.
  - 필터 계층이라 스니펫·줄·지문은 바뀌지 않고 기각 기록도 유지됩니다.
  - 분석은 조건 규칙이 매치했을 때만 돌기 때문에 후보 0건 예산은 영향이 없습니다.
- **선택적 백엔드**: tree-sitter 노드 타입(`for_statement`, `class_constant_access_expression` 등)으로 정확히 대체할 수 있습니다(3장).

### R2. 함수 판별에 구멍이 크다 — JS/TS 메서드는 구조적으로 절대 함수가 안 된다

- **영역**: 구조 계층 → `in_scope: function` · 컨텍스트 팩 · 판정 캐시 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - JS 메서드 정규식의 두 번째 대안은 `…\{\s*$` 로 끝납니다(`scripts/lib/structure/native/langs.py:33-38`). 그런데 헤더는 `{` **앞에서** 잘립니다(`scripts/lib/structure/native/scopes.py:176`). 그래서 이 대안은 절대 매치할 수 없습니다. Java 와 C 정규식은 `\{?` 라서 동작합니다(`langs.py:43`, `:45`).
  - 함수 정규식은 한 줄씩 검사합니다(`scopes.py:261-262`). 그래서 여러 줄 시그니처는 인식하지 못합니다.
- **문제**
  - 다음은 모두 함수로 보지 않습니다: class/object 메서드, 화살표 콜백(`app.get('/', async (req,res) => {`), 클래스 필드 화살표, PHP 익명 `function`, Go `defer func() {`, Rust 클로저, Java 람다, Swift `-> Int {`.
  - 반대로 C 의 `} else if (b) {` 는 함수가 됩니다. C 패턴에 `NOT_A_NAME` 이 없기 때문입니다(`langs.py:45`).
  - 영향 1: `in_scope: function` 미탐.
  - 영향 2: 의미 판정 팩이 ±30줄 창으로 대체됩니다(`scripts/lib/context.py:178-183`). 이웃 메서드를 고치면 불필요하게 재판정하고, 30줄 밖의 변경은 캐시가 오래된 채 남습니다.
- **재현**: 직접 확인했습니다.

  | 사례 | 기대 | 실제 |
  |---|---|---|
  | `class A { run(a) {` 의 innermost function | 메서드 | None |
  | `app.get('/', async (req,res) => {` | 콜백 | None |
  | C `else if` | 바깥 함수 | 함수로 잡힌 블록 `(3,5)` |

  STR `repro2.py` 와 SEM `r13_jsmethod.py`, `r1_regions.py` 도 같은 결과입니다.
- **제안**
  - (a) 즉시 수정: `\{\s*$` 를 `\{?\s*$` 로 바꿉니다(한 글자). SEM `r14_jsfix.py` 사본에서 전체 테스트와 골든이 통과했습니다. 뒤집어 말하면 이 경로를 검사하는 테스트가 없다는 뜻입니다.
  - (b) 한 줄 검사가 실패하고 헤더에 줄바꿈이 있으면 `' '.join(header.split())` 로 한 번 더 시도합니다.
  - (c) R1 의 `lambda_heads` 필드(`=>`, `->`, `|…|`, `function(`, `func(`)로 "`{` 직전이 람다 머리면 함수"라고 판정합니다.
  - C 패턴에는 `NOT_A_NAME` 을 붙입니다.
  - **선택**: (a)+(b) 를 먼저 넣고, (c) 는 R1 과 함께 합니다. (a) 는 위험이 거의 없고 효과가 가장 큽니다.
- **트레이드오프**: 영향받는 JS 파일의 팩 해시가 한 번 바뀌어 재판정이 한 번 생깁니다. `tests/structure/test_scopes.py` 와 `tests/semantic/test_context_pack.py` 에 메서드 사례를 추가해야 합니다.
- **선택적 백엔드**: tree-sitter `method_definition`, `arrow_function`, `func_literal`, `closure_expression` 노드.

### R3. 표시 예산 밖 error 가 남았는데 "✔ 재검증 통과"로 닫고, 그 뒤 세션 내내 침묵한다

- **영역**: 검증 사이클 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - `opened` 에는 표시한 후보만 들어갑니다(`scripts/lib/hooks.py:609`).
  - `_close` 는 opened 키가 사라진 규칙을 `fired_rules` 로 정리합니다(`:453-457`).
  - 그다음부터 `once_per_session` 이 그 규칙을 조용히 뺍니다(`:360-372`).
  - 차단 사유에 "… N건 더" 표시가 없습니다(`scripts/lib/report.py:94-118`).
- **문제**
  - 보여 준 것만 고쳐도 통과합니다. 이것은 `tests/integration/test_hook_cycle.py:123-136` 이 의도한 동작입니다.
  - 하지만 라벨이 "재검증 통과"라서, 남은 error 가 통과로 보입니다.
  - 더 나쁜 점: 같은 규칙의 새 위반이 이후 세션 내내 아무 출력 없이 지나갑니다.
- **재현**: CYC `s1_budget.py` 와 `s1c.py` 를 직접 재실행했습니다.
  - error 규칙 5개 중 4개를 보여 주고, 4개를 고쳤습니다. 결과는 `✔ 재검증 통과 — 고쳐짐 4` 이고, 파일에는 `BAD5` 가 남아 있으며, `fired_rules` 에 4개 규칙이 들어갑니다.
  - 규칙 하나에 위치가 4개인 경우: 3개를 보여 주고 3개를 고치면 통과입니다. 그 뒤 새 `BAD` 를 추가해도 decision 은 None 이고 요약은 비어 있습니다.
- **제안**
  - (a) **페이지 넘기기**: 검증할 때 `seen ∩ current − opened` 인 error 를 다음 차단으로 올립니다(`review_page` 와 같은 방식).
  - (b) **차단은 그대로, 통과라고 속이지 않기** ← **선택**
    1. `_close` 에 `current` 를 넘겨, `current` 에 키가 하나도 없는 규칙만 정리합니다.
    2. 닫는 메시지에 "미표시 N" 을 넣고 종류를 warn 으로 바꿉니다.
    3. 그 키들을 `unresolved` 에 넣어 다음 요청에서 다시 올립니다.
    4. `hook_reason` 에 규칙별 `…N건 더` 와 숨긴 규칙 수를 표시합니다.
  - (c) 예산 제거: `REASON_LIMIT` 때문에 기각합니다.
- **선택 이유**: 기존 테스트의 의도(보여 준 것만 고치면 턴 통과)를 지키면서, 거짓 통과와 영구 침묵을 없앱니다. 집합 연산이라 비용은 거의 0이고, 지문도 바뀌지 않습니다.
- **트레이드오프**: 요약 문구와 `fired_rules` 내용이 바뀝니다. 출력 형식 테스트를 갱신해야 합니다. 패리티 골든은 영향이 없습니다.
- **같은 뿌리의 문제**
  - **C6**: `VERIFY_CAP=50` 이 `seen` 을 자릅니다(`scripts/lib/hooks.py:35`, `detect.py:151`). 그래서 이미 있던 후보가 "새로 생김"으로 보입니다(CYC `s8_cap.py`: 55건일 때 3개를 고치면 `새로 생김 3`). 상한에 걸린 규칙을 표시해 두고, 그 규칙의 new 는 "남음(미표시)"으로 분류합니다.
  - **C9**: `once_per_session` 으로 뺀 error 도 알림에서는 개수를 셉니다.

### R4. 연속 차단 상한이 요청을 넘어 누적되어, 새 요청의 새 위반까지 막지 못한다

- **영역**: Stop 정책 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**: `_close` 는 차단 대상이 남으면 연속 차단 수(streak)를 유지합니다(`scripts/lib/hooks.py:460-461`). 상한에 걸린 `_open` 은 차단 대상이 있는 한 초기화하지 않습니다(`:584-585`).
- **문제**: 사용자가 확인해 준 의도는 "요청 안의 루프 가드"입니다. 하지만 지금은 무시된 error 하나가 상한을 채우면, 다른 요청에서 다른 파일에 생긴 다른 규칙의 error 도 "차단 안 함"이 됩니다.
- **재현**: CYC `s5_streak.py` 를 직접 재실행했습니다.
  - p1: 무시했고 streak 2.
  - p2: 같은 error 로 다시 차단, streak 3.
  - p3: 새 파일에 새 규칙 error 가 생겼는데 `기록 — error 2 · 차단 안 함: 연속 차단 3회 상한`.
- **제안**
  - (a) **요청 경계에서 초기화** ← **선택**. `_belongs_to_new_request` 가 참인 첫 Stop, 또는 continuation 이 아닌 Stop 에서 `consecutive_blocks=0` 으로 만듭니다.
  - (b) 상한에 걸려도 `unresolved` 반복이 아닌 새 키는 차단합니다.
  - (c) 반복만 있는 차단은 streak 에 세지 않습니다.
- **선택 이유**: 의도와 정확히 일치하고 코드 한 곳만 바뀝니다. 요청 안의 무한 루프는 여전히 `max_verify_attempts` 와 상한이 막습니다. 요청을 넘는 잔소리는 `unresolved` 의 "지난 턴에도 지적" 표시로 구분됩니다.
- **트레이드오프**: `tests/integration/test_hook_cycle.py:179-191` (`case_consecutive_cap`) 는 서로 다른 prompt(q0~q3)에 걸쳐 누적되는 동작을 단언합니다. 이 테스트는 같은 요청 안의 continuation 시나리오로 바꿔야 합니다. `CLAUDE.md` 절차상 Stop 동작 변경이라 턴 시나리오도 추가해야 합니다.

### R5. line 앵커가 줄당 첫 매치만 보므로, 첫 매치가 문자열·주석이면 진짜 위반을 놓친다

- **영역**: 탐지 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**: `rule['compiled_when'].search(text)` 로 첫 매치 하나만 구조 판정에 넘깁니다(`scripts/lib/detect.py:179-183`). 픽스처 실행기도 같습니다(`scripts/lib/rules/fixtures.py:72`).
- **문제**
  - 정확도: `not_in` 이 첫 매치를 REJECT 하면 그 줄 전체가 사라집니다.
  - 안정성: 같은 위반 앞에 무해한 문자열 하나만 붙여도 판정이 뒤집힙니다.
  - 검증 사이클: 에이전트가 위반 줄 앞에 `"dd("` 를 넣기만 해도 fixed 로 분류됩니다.
- **재현**: `M/r1` 의 `app/A.php:8` `$label = "dd("; dd($user);` 에 `scan.py --rule php-no-debug-output` 을 돌렸습니다. 기대는 8행 후보, 실제는 9·10행만 나옵니다. STR `repro3.py` 의 JS `console.log` 도 같은 결과입니다.
- **제안**
  - (a) 조건이 있는 규칙만 `finditer` 로 돌면서 REJECT 가 아닌 첫 매치를 채택합니다 ← **선택**.
  - (b) 마스킹된 줄(주석·문자열을 공백으로 바꾼 줄)에 정규식을 돌립니다. 하지만 `'use client'` 처럼 문자열 자체가 대상인 규칙이 깨집니다.
- **선택 이유**: 스니펫·줄·지문이 줄 단위라 모두 그대로입니다. 조건 없는 규칙은 1.x 경로를 그대로 탑니다(`detect.py:135`).
- **트레이드오프**: 무시할 수준입니다. 픽스처 실행기(`fixtures.py:72`)도 같이 바꿔야 픽스처와 실제 판정이 어긋나지 않습니다.

### R6. `must_contain_in_file` 이 주석·문자열 안의 매치로도 충족된다 (사용자 확인: 의도 아님)

- **영역**: 앵커(requires / absent) · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - requires 는 필수 요소를 파일 원문에서 찾습니다(`scripts/lib/detect.py:223`). 주석에 "only the trigger is judged … (Q10=A, DR-18)" 이라고 적혀 있습니다(`:230-231`).
  - absent 는 `added_body` 원문에서 찾습니다(`:191`).
  - `read_text` 는 `utf-8` 로 읽어 BOM(U+FEFF)이 남습니다(`scripts/lib/gitdiff.py:145`).
- **문제**: 보안·정확성 규칙의 미탐입니다. BOM 이 있으면 `^` 앵커 필수 요소가 오탐을 냅니다.
- **재현**
  - `M/req` 를 직접 재현했습니다. `store(Request $request)` 만 있을 때 `laravel-controller-needs-validation` 이 7행에서 발동합니다. 함수 안에 `// TODO: FormRequest 로 교체할 것` 한 줄을 넣으면 **후보 0** 이 됩니다.
  - DET `f4`: `$note = "->validated() 는 나중에";` 도 같은 결과입니다.
  - DET `f5` A: BOM 다음에 `'use client';` 가 오면 `next-client-hook-needs-directive` 오탐이 납니다.
- **제안**
  - (a) `compiled_must.finditer` 로 돌면서 **주석 구간 밖의 첫 매치**가 있어야 충족으로 봅니다. 주석 구간은 기존 `FileStructure.comments` 를 씁니다. 분석에 실패하면 원문 매칭으로 폴백하고 "구조 미확인"으로 기록합니다.
  - (b) 규칙별 opt-in 키 `must_not_in: [comment, string]` 를 둡니다. 문자열은 기본으로 제외할 수 없습니다. `'use client'` 요구 자체가 문자열 리터럴이기 때문입니다.
  - (c) 문서화만 합니다.
  - **선택**: 주석은 (a) 로 **기본 제외**하고, 문자열 제외는 (b) 로 opt-in 합니다. 별도로 `utf-8-sig` 로 디코딩하고, `parse_diff` 에서 첫 줄의 BOM 을 벗깁니다.
- **선택 이유**: 사용자 의도와 일치합니다. 구조 분석은 원문 정규식이 이미 매치한 파일에서만 돕니다. 즉 필수 요소가 있는 것처럼 보이는 파일에서만 비용이 생깁니다.
- **트레이드오프**
  - DR-18 을 뒤집는 결정이므로 코드 주석과 `docs/rules.md` 를 고쳐야 합니다.
  - 지금까지 조용하던 파일에서 후보가 새로 나올 수 있어 패리티 골든 diff 를 검토해야 합니다.
  - 앵커가 `when_line_added` 단독이 아니므로 `tests/rules/scenarios/` 에 "주석만 있는 필수 요소" 시나리오를 추가해야 합니다.
- 참고: 범위를 함수로 좁히는 문제(`update()` 가 같은 파일 `store()` 의 FormRequest 덕분에 통과하는 문제)는 별개의 결정으로 남깁니다.

### R7. 의미 판정 — 한 함수의 후보들이 한 질문으로 묶이지만 리뷰어는 첫 후보만 본다

- **영역**: 의미 판정 배치 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - `review_hash` 에는 후보를 식별하는 정보가 없습니다(`scripts/lib/semantic.py:89-93`).
  - `build_batch` 는 같은 키를 건너뜁니다(`:159-164`). 그래서 배치 항목에는 첫 후보의 줄과 스니펫만 들어갑니다. 그런데 판정 하나가 함수 안 모든 후보에 적용됩니다.
  - `hooks.py` 의 `by_key` dict 는 같은 키의 **마지막** 후보를 남깁니다(`scripts/lib/hooks.py:473`). 배치 항목은 첫 후보이므로 서로 어긋납니다.
- **문제**: 두 번째 루프의 진짜 N+1 이 첫 루프에 대한 VALID 로 지워집니다. 미탐입니다.
- **재현**: SEM `r4_dedupe.py` 를 직접 재실행했습니다. 후보는 7행과 11행이지만 배치 항목은 7행 하나입니다. VALID 를 기록하면 `cleared=[(7,'VALID'),(11,'VALID')]` 가 됩니다.
- **제안** (사용자 확인: 함수 단위 유지)
  - (a) 배치 항목에 함수 안의 모든 후보 줄과 스니펫을 `lines: [...]` 로 넣고, `show()` 가 전부 렌더링합니다. 지시문에는 "나열된 줄 중 하나라도 위반이면 VIOLATION, 사유에 줄을 명시"를 넣습니다. `hooks.py:473` 은 `setdefault` 로 바꿔 첫 후보가 이기게 합니다 ← **선택**.
  - (b) `review_hash` 에 `code_hash` 를 넣어 후보 단위로 판정합니다. 호출 수가 늘고 모든 키가 바뀝니다.
- **선택 이유**: 캐시 키 형식과 비용이 그대로이고, 배치 스키마만 바뀝니다.
- **트레이드오프**: 배치 버전을 올려야 합니다. `agents/convention-reviewer.md` 도 고쳐야 합니다.

### R8. 관련 파일 지문이 "보여 준 앞 60줄"만 덮어서, 캐시된 VALID 가 오래된 채 남는다

- **영역**: 판정 캐시 · **우선순위**: 높음 (core `laravel-n-plus-one`) · **확신도**: 높음
- **현재 로직**: `related_hash` 는 보여 준 섹션 텍스트만 해시합니다(`scripts/lib/context.py:114-127`). 관련 파일은 `other_lines[:take]` 까지만 섹션에 들어갑니다(`:219-230`). 그런데 리뷰어에게는 잘린 뒤쪽도 Read 하라고 안내합니다.
- **재현**: SEM `r2_hashes.py` 를 직접 재실행했습니다. `app/Models/Order.php` 75행의 `protected $with = ['items']` 를 지워도 ctx, rel, key 가 모두 `9e0d9cbb13` 그대로입니다.
- **제안**
  - (a) 실린 관련 파일마다 **파일 전체 지문**을 `related_hash` 에 접어 넣습니다. 표시 방식은 그대로 둡니다 ← **선택**.
  - (b) 60줄 상한을 올립니다. 경계가 뒤로 밀릴 뿐입니다.
  - (c) 파일 머리 대신 개요(시그니처, `$with`)를 추출합니다. 코드가 늘고 여전히 휴리스틱입니다.
- **선택 이유**: 코드 세 줄이면 되고, 해시가 "판정이 의존한 것"이라는 문서의 약속(`docs/semantic-review.md`)과 맞습니다.
- **트레이드오프**
  - Model 을 고치면 그 Model 을 쓰는 곳이 재판정됩니다. 전환할 때 N+1 캐시가 한 번 전부 무효가 됩니다.
  - 리뷰어가 팩 밖에서 추가로 Read 한 파일은 여전히 어떤 해시에도 들어가지 않습니다. 리뷰어가 읽은 경로를 `record` 에 남기게 하는 것을 다음 단계로 둡니다.
- **같은 영역의 부수 항목**
  - `changed_hunks` 가 관련 파일보다 먼저 예산을 씁니다(`context.py:196-202`, 이어서 `:204`). 그래서 파일의 다른 곳이 바뀌면 `related_hash` 가 흔들립니다(SEM `r2` b1, 예산 80: `17094c8396`→`804b270a5a`). `related_files` 블록을 앞으로 옮깁니다.
  - 해시되는 imports 에 줄 번호가 들어갑니다(`context.py:188-194`). 그래서 파일 맨 위에 라이선스 주석을 넣기만 해도 재판정됩니다(SEM `r3_layer.py`). 해시는 정렬한 줄 텍스트 집합으로 계산합니다.

### R9. 마스킹 실패 하나가 파일 전체의 구조 조건을 끈다

- **영역**: 구조 계층 마스킹 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - 마스킹이 한 번 실패하면 `ok=False` 가 되고, 그 파일의 모든 조건이 UNKNOWN 이 됩니다(`scripts/lib/structure/conditions.py:38-39`). 후보는 남긴 채 "구조 미확인"으로 표시됩니다.
  - 정규식 리터럴인지는 앞 글자 집합과 앞 단어 목록으로 판별합니다(`scripts/lib/structure/native/mask.py:59-61`, `:278-286`).
  - 한 줄짜리 문자열이 줄바꿈을 만나면 실패로 처리합니다(`mask.py:322-323`).
- **문제**: 흔한 코드 모양 하나가 `js-no-console`, `ts-no-any`, `php-no-debug-output` 같은 `not_in` 규칙을 파일 단위로 무력화합니다. 주석·문자열 안의 매치가 다시 올라오고, 미확인 알림이 붙습니다.
- **재현**: 직접 확인한 사례입니다.
  - `const f = s => /"/.test(s);` 는 `unterminated_string:1` 입니다. `>` 가 문자 집합에 없기 때문입니다.
  - `a + /"/.test(s)`, `if (x) /"/.test(s)` 도 실패합니다.
  - JSX `<p>Don't do this</p>` 는 `unterminated_string:2` 입니다.
  - Rust `fn f<'a>(x: &'a str)` 는 ok=False 입니다.
  - PHP heredoc 의 `{$u->dd()}` 보간은 코드가 아닌 문자열 하나(`Span(11,35)`)로 처리됩니다. heredoc 프레임의 패턴이 종료자뿐이라 `interp` 대안이 없기 때문입니다(`mask.py:301-310`).
  - C# `@"…\"`, Swift `#"…"#`, C++ `R"(…)"` 와 `1'000` 은 STR `repro4.py` 에서 확인했습니다.
- **제안**
  - (a) **데이터 보강**
    - 정규식 문맥: 앞 토큰이 `=>` 인 경우를 추가합니다.
    - Rust 문자 리터럴 가드 `'(?=\\?.')`, C# `@"` Multiline(`""` 이스케이프), Swift `#"`/`"#`, C++ `R"(`/`)"`, 숫자 구분자 가드를 넣습니다.
    - heredoc 패턴을 `종료자|esc|interp` 교대로 만듭니다.
    - `java` 한 줄에 묶인 Kotlin, Swift, C#, Dart 를 각자 행으로 분리합니다(`langs.py:166-179`).
  - (b) **정규식 문맥 판정을 여집합으로 뒤집기**: "앞 토큰이 값으로 끝나면 나눗셈, 그 밖에는 정규식"으로 판정합니다. 값으로 끝나는 토큰은 식별자, 숫자, `)`, `]`, `}`, 닫는 따옴표뿐입니다. 이 집합은 닫혀 있고 작습니다. 제어문 괄호 다음(`if (…) /re/`)만 예외라서, R1 토크나이저가 제어문 `)` 를 표시합니다. 단 `in`/`of` 같은 키워드가 변수명일 때(`of / 2`)는 여전히 모호합니다.
  - (c) **JSX**: `LangDef` 에 `jsx` 플래그를 둡니다. `(`, `return`, `=>`, `,`, `?` 뒤의 `<Ident` 는 텍스트 프레임을 엽니다. 텍스트는 `{`(코드), `</`, `/>` 에서 끝납니다. 기존 태그와 텍스트 프레임 장치를 재사용합니다. Blade 와 같은 모양입니다.
  - **선택**: (a)+(c) 를 지금 하고, (b) 는 R1 토크나이저와 함께 합니다. 목록 추가가 아니라 문법 사실을 데이터로 옮기는 작업이라 기준 4 에 맞습니다.
- **트레이드오프**
  - 행과 픽스처가 늘어납니다.
  - JSX 의 `<` 는 TS 제네릭·비교 연산자와 모호합니다. 앞 토큰으로 게이트해야 합니다.
  - 지문 영향은 없습니다(필터 계층).
- **선택적 백엔드**: tsx·rust·c# tree-sitter 문법이 모두 기본으로 처리합니다.

### R10. `in_scope` 가 줄 단위라 헤더 줄과 같은 줄의 형제 문장이 "안"이 된다 (사용자 확인: 본문만)

- **영역**: 구조 조건 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**: `_in_scope` 는 `line_of(span.start)` 로 줄을 구하고, 그 줄을 포함하는 스코프 노드 전부를 모읍니다(`scripts/lib/structure/conditions.py:69-76`, `scripts/lib/structure/model.py:175-186`). 노드의 `start_line` 은 헤더 줄입니다(`scripts/lib/structure/native/scopes.py:180`).
- **재현**: 직접 확인했습니다.
  - `for (const x of await load()) {` 의 `await load` 는 loop 가 ACCEPT 됩니다. 기대는 REJECT 입니다.
  - `for (…) { a(x); } b();` 의 `b()` 도 loop 가 ACCEPT 됩니다. 기대는 REJECT 입니다.
- **제안**
  - (a) 노드 **본문 Span(오프셋)** 포함으로 판정합니다. `body` 는 이미 모델에 있습니다(`model.py:84`) ← **선택**.
  - (b) 줄 단위를 유지하고 헤더 줄만 뺍니다. 같은 줄 형제 문제는 남습니다.
- **선택 이유**: 사용자 의도와 일치하고, 계산이 더 정확하며, 비용은 같습니다.
- **트레이드오프 (중요)**
  - core `laravel-n-plus-one` 은 트리거 자체가 `foreach (` / `->each(` **헤더 줄**입니다(`rules/php/laravel/laravel-n-plus-one.yaml:11-14`). 본문만 인정하면 이 규칙의 `in_scope: loop` 가 거의 모든 후보를 REJECT 합니다.
  - 따라서 규칙도 같이 바꿔야 합니다. 트리거 정규식이 이미 "반복 시작"을 표현하므로 `in_scope` 를 빼고 `not_in` 만 남기는 것을 권합니다. 이렇게 하면 R1 의 `::class` 미탐도 이 규칙에서는 사라집니다.
  - 픽스처와 패리티 골든을 갱신해야 합니다.

### R11. 후보 지문이 120자로 자른 스니펫에서 계산된다

- **영역**: 후보 키 · 기각 · 사이클 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**: `Candidate(..., clip(text))` 에서 `fingerprint(snippet)` 를 계산합니다(`scripts/lib/detect.py:183`, `:213`, `:234`, `scripts/lib/candidate.py:28-30`, `:42`). file 앵커는 `\n` 을 ` ⏎ ` 로 바꾼 다음 지문을 냅니다(`detect.py:213`).
- **문제**
  - 120자 뒤가 바뀌어도 키가 그대로라서, 기각이 만료되지 않습니다. "코드가 바뀌는 순간 만료"라는 약속(`candidate.py:7-10`)과 어긋납니다.
  - core `php-line-too-long` 은 120자를 넘는 줄에만 매치하므로 이 문제에 항상 걸립니다.
  - file 매치가 공백으로 끝나면, 뒤따르는 빈 줄 수가 바뀔 때마다 키와 겹침 창이 달라집니다(DET `f3`).
- **재현**: CYC `s3_trunc.py`, DET `f1`: 앞 120자가 같은 두 줄이 같은 키 `local/bad:a.txt:9ba65c989c` 를 받습니다. 하나를 기각한 뒤 꼬리를 `evil()` 로 바꿔도 후보 0 입니다.
- **제안**
  - (a) **전체 줄(또는 전체 매치)** 을 공백 정규화한 값으로 해시하고, 스니펫은 표시용으로만 자릅니다. 전환 기간에는 기각이 옛 해시와 새 해시를 모두 인정합니다. 옛 해시는 줄이 120자를 넘을 때만 계산합니다 ← **선택**.
  - (b) 상한을 올립니다. 경계가 뒤로 밀릴 뿐입니다.
  - (c) 자른 해시에 길이를 더합니다. 여전히 충돌합니다.
- **선택 이유**: 키가 바뀌는 후보는 120자를 넘는 줄과 file 앵커뿐이고, 이중 매칭으로 사용자 기록이 살아남습니다.
- **트레이드오프**
  - 기각 기록 형식은 그대로지만 새 해시로 쓰기 시작하므로 `scripts/migrate.py` 에 해시 갱신 경로가 필요할 수 있습니다.
  - file 앵커는 매치 앞뒤 공백을 잘라 줄 범위를 계산하고, `⏎` 없이 지문을 냅니다. 이 변경도 같은 이중 매칭 안에 넣습니다.
  - 패리티 골든에는 해시가 없어 영향이 없습니다(`tests/integration/golden/parity.json`).

### R12. 사람·다른 사람의 줄과 다른 터미널의 커밋이 에이전트 책임으로 잡힌다

- **영역**: 수집·범위 · **우선순위**: 높음 · **확신도**: 높음
- **현재 로직**
  - 편집 도구는 **파일**만 기록합니다(`scripts/lib/hooks.py:106-115`). Stop 은 그 파일에서 HEAD 또는 세션 base 대비 추가된 줄 전부를 검사합니다(`scripts/lib/gitdiff.py:230-268`).
  - Bash Pre 는 **현재 HEAD** 기준으로 스냅샷을 찍습니다(`hooks.py:62-64`). Bash Post 는 **세션 base** 기준으로 비교합니다(`:96-97`).
- **문제**
  - 오탐 1: 세션 전에 사람이 같은 파일에 넣은 줄.
  - 오탐 2: 에이전트의 `git merge`·`pull` 이 가져온 동료의 줄.
  - 오탐 3 (Pre/Post 기준 불일치): 세션 base 와는 다르지만 현재 HEAD 에서는 깨끗한 파일은 스냅샷에 없습니다. 그래서 다음 Bash 호출에서 `before.get(rel)` 이 None 이 되어 그 파일을 에이전트 것으로 가져갑니다. 다른 터미널에서 사람이 커밋한 파일도 여기에 해당합니다.
- **재현**: COL `h.py`.
  - R1: 사람이 세션 전에 `# TODO` 를 넣었고 에이전트가 같은 파일을 편집했습니다 → 후보가 납니다.
  - R3: `git merge` → 동료의 TODO 가 후보가 됩니다.
  - R2: 에이전트가 `a.py` 를 편집하는 동안 사람이 다른 곳에서 `b.py` 를 커밋했고, 에이전트가 `ls` 를 실행했습니다 → touched 가 `[a.py, b.py]` 이고 `b.py:2` 가 후보입니다.
  - Pre/Post 기준 불일치는 코드로 확인했습니다(`hooks.py:62-64` vs `:96-97`).
- **제안**
  - (a) **줄 기준선**: 편집 도구에도 PreToolUse 를 달고, 파일을 처음 건드리기 직전의 추가 줄을 `(file, fingerprint)` 멀티셋으로 남깁니다. Bash 가 HEAD 를 옮기면, 워킹 트리 sha 가 바뀐 파일에 한해 그 커밋이 가져온 줄을 남깁니다. Stop 에서는 개수만큼 빼 줍니다 ← **선택**.
  - (b) 처음 건드릴 때 파일 사본을 데이터 디렉터리에 두고 Stop 에서 `difflib` 으로 비교합니다. 정확하지만 저장과 계산 비용이 큽니다.
  - (c) `git stash create` 스냅샷. 사용자 레포에 객체를 쓰고 untracked 파일을 놓칩니다.
  - 기준 불일치는 Pre 가 `record_base` 뒤에 세션 base 를 읽어 `changed_paths` 에 넘기도록 **한 줄**로 고칩니다.
- **선택 이유**: 비용은 Pre 에서 치르고, Stop 에서는 집합 뺄셈뿐입니다. 후보 키도 바뀌지 않습니다.
- **트레이드오프**: 에이전트가 쓴 줄이 이미 있던 추가 줄과 글자까지 같으면(예: `}`) 놓칠 수 있습니다. 안전한 쪽의 실패입니다.
- **참고**: 작업 트리의 미커밋 변경(`foreign-<session>.jsonl`, `hooks.json` 수정)이 바로 이 방향입니다. 다만 분석 대상이 아니라 검토하지 않았습니다. 기준 불일치 수정이 그 변경에 들어 있는지는 확인이 필요합니다.

### R13. diff 결과가 사용자 git 설정과 줄바꿈 변환에 따라 달라진다

- **영역**: 범위 · **우선순위**: 중간 (안정성) · **확신도**: 높음
- **현재 로직**: `DIFF_FLAGS` 는 색·접두·ext-diff·rename 만 고정합니다(`scripts/lib/gitdiff.py:29-30`). `diff.algorithm`, textconv, CR 무시 여부는 고정하지 않습니다.
- **재현**
  - COL `r8c` 를 직접 재실행했습니다. 같은 변경인데 myers 는 `+{` 한 줄, histogram 과 patience 는 이미 있던 `return; y(); if (a) {` 까지 추가로 봅니다.
  - COL R6: LF 파일을 CRLF 로 다시 쓰면 레거시 TODO 가 걸립니다.
  - COL R15: 기존 코드를 `if True:` 로 감싸 들여쓰기만 바꾸면 레거시 TODO 가 걸립니다.
- **제안**
  - (a) `--diff-algorithm=myers --indent-heuristic --no-textconv --ignore-cr-at-eol` 을 추가합니다 ← **선택**.
  - (b) histogram 으로 고정합니다. 코드에는 더 낫지만, 기본 설정 사용자에게서도 골든이 바뀝니다.
  - (c) `--ignore-space-change` 까지 넣습니다. 들여쓰기 규칙을 가립니다.
- **선택 이유**: myers 는 git 의 기본값이라 기본 설정 사용자는 결과가 그대로입니다. 설정이 다른 기계의 판정만 기본값에 맞춰집니다.
- **트레이드오프**: `--ignore-cr-at-eol` 은 git 2.16 이상이 필요합니다. 재들여쓰기를 에이전트 책임으로 볼지는 별도 결정으로 남깁니다.

### R14. 파일 이동이 "전체 추가"가 되고, 세션 중 커밋·빈 레포에서 새 파일 판정이 꺼진다

- **영역**: 범위 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**
  - `--no-renames` 입니다(`scripts/lib/gitdiff.py:29`).
  - 새 파일은 untracked 이거나 HEAD 대비 index 에 추가된 파일뿐입니다. 세션 base 는 보지 않습니다(`gitdiff.py:105-120`, `scripts/lib/scope.py:73`).
  - HEAD 가 없으면 base 를 기록하지 않습니다(`scripts/lib/state.py:73`). 첫 커밋 뒤에는 base 가 HEAD 와 같아져 버려집니다(`scripts/lib/hooks.py:335`).
- **재현**
  - DET `f7`: `git mv` 한 레거시 파일의 `dd($x);` 가 걸립니다.
  - COL R4b: 그냥 `mv` 하면 파일이 새 파일로 판정되어 absent 규칙까지 발동합니다.
  - COL R5, DET `f11`: 세션 중에 커밋한 새 파일은 `is_new=False` 입니다. 훅 결과와 `--range` 결과가 서로 다릅니다.
  - COL R14: 빈 레포에서 `git commit` 한 뒤 Stop 하면 None 입니다. 조용한 통과입니다.
- **제안**
  - 이동
    - (a) `-M` 로 rename 을 감지합니다 ← **선택**. untracked 파일로 옮긴 경우는 blob sha1(`'blob %d\0'` + 내용, hashlib)을 삭제된 추적 파일의 blob id 와 비교해 짝을 찾습니다.
    - (b) `--no-renames` 는 유지하고 삭제된 줄 지문을 뺍니다. `parse_diff` 가 `-` 줄도 모아야 합니다.
  - 새 파일: ref 마다 `git diff --name-only --diff-filter=A <ref>` 를 추가합니다. `untracked` 를 두 번 부르는 부분(`gitdiff.py:242`, `:120`)은 하나로 합칩니다. 기록 파일 없이 모든 진입점에서 똑같이 동작합니다.
  - 빈 레포: 빈 트리 id 를 base 로 기록합니다. SHA-256 레포는 `git hash-object -t tree --stdin </dev/null` 로 구합니다.
- **트레이드오프**
  - rename 유사도 임계값이 작은 파일을 잘못 짝지어 진짜 줄을 가릴 수 있습니다. 70% 를 권합니다.
  - 패리티 골든에 rename 이 있으면 결과가 바뀝니다.
  - 추가되는 프로세스는 ref 당 1개이고, 파일당 프로세스는 없습니다.

### R15. `--staged`·`--range` 가 줄 번호는 index·범위에서, 본문은 워킹 트리에서 가져온다

- **영역**: 범위 · **우선순위**: 중간 (CI·pre-commit 게이트) · **확신도**: 높음
- **현재 로직**: 줄 번호는 `diff --cached` 나 `diff <spec>` 에서 옵니다(`scripts/lib/scope.py:87-101`). `text()` 는 항상 워킹 트리를 읽습니다(`scope.py:53-56`). file 앵커, requires, 구조 조건이 이 본문을 씁니다.
- **재현**
  - DET `f6`: 스테이지 뒤 워킹 트리에 4줄을 더하면 `scan --staged` 결과가 0건입니다. 기대는 2건입니다.
  - COL R9: 보고된 줄 번호가 다른 내용을 가리킵니다.
- **제안**
  - (a) 범위에 본문 공급원을 둡니다. staged 는 `:path`, range 는 `<rhs>:path` 를 `git cat-file --batch` **한 프로세스**로 읽습니다 ← **선택**.
  - (b) 워킹 트리가 다른 파일을 감지해 "구조 미확인"으로 표시합니다.
- **선택 이유**: 정답을 주는 유일한 안이고, Stop 훅 경로는 바뀌지 않습니다. `scannable` 은 크기를 blob 에서 확인하게 바꿉니다(`scope.py:32-33`).

### R16. auto-fix 가 UTF-8 이 아닌 파일에서 Stop 전체를 죽이고, 혼합 줄바꿈을 모두 CRLF 로 바꾼다

- **영역**: 자동 수정 · **우선순위**: 중간 (auto-fix 사용자에게는 높음) · **확신도**: 높음
- **현재 로직**: `_read_lines` 는 strict `utf-8` 로 읽습니다(`scripts/lib/autofix.py:30-35`). `plan` 과 `apply` 는 `OSError` 만 잡습니다(`:47-50`). 파일 하나라도 `\r\n` 이 있으면 전부 `\r\n` 으로 합칩니다(`:34`).
- **재현**: CYC `s7_autofix.py` 를 직접 재실행했습니다.
  - cp949 파일: `✖ 건너뜀 — 내부 오류: 'utf-8' codec can't decode…`. touched 가 남아 있어 세션 내내 같은 결과입니다.
  - 혼합 줄바꿈: `b'one\r\ntwo\nthree…'` 가 `b'one\r\ntwo\r\nthree\r\n…'` 가 됩니다.
- **제안**
  - (a) 바이트로 읽어 `splitlines(keepends=True)` 로 나누고, 디코딩에 실패하면 그 파일을 건너뜁니다. 대상 줄의 내용만 바꾸고 그 줄의 줄끝은 유지합니다 ← **선택**.
  - (b) `surrogateescape` 로 왕복합니다.
- **선택 이유**: 읽을 수 없는 인코딩의 파일은 절대 쓰지 않는다는 점이 명시적입니다. `CLAUDE.md` 의 "원본의 줄바꿈을 따른다" 규칙과도 맞습니다.
- **트레이드오프**: 없습니다. `test_hook_cycle.py` 에 회귀 테스트를 추가합니다.

### R17. 린터가 돌지 않으면 열린 lint 키가 fixed 가 되어 "✔ 통과"로 닫힌다

- **영역**: 사이클·린터 · **우선순위**: 중간 · **확신도**: 중간 (**코드 인용만** — 느린 린터가 필요해 재현하지 않았습니다)
- **현재 로직**
  - 타임아웃이나 예산 소진이면 warn 노트만 남기고 실패로 기록하지 않습니다(`scripts/lib/lint.py:218-222`, `:266-282`).
  - `classify` 는 사라진 lint 키를 fixed 로 분류합니다(`scripts/lib/cycle.py:75-81`).
  - 린터 diff 파서는 삽입만 있는 hunk 를 버립니다(`lint.py:186-190`). 그리고 hunk 안의 `--- ` 로 시작하는 삭제 줄을 파일 헤더로 오인합니다(`lint.py:174`). `gitdiff.parse_diff` 는 같은 문제를 `in_hunk` 로 이미 고쳤습니다(`scripts/lib/gitdiff.py:169-197`).
- **제안**
  - (a) `lint.run` 이 끝나지 못한 항목 키 집합도 돌려주고, 거기 속한 opened lint 키는 still(미확인)로 분류하며 닫는 메시지를 warn 으로 합니다 ← **선택**.
  - (b) 린터 미검사 노트가 하나라도 있으면 통과를 "종료(미확인)"로 격하합니다. 더 거칩니다.
  - 린터 diff 파서는 `in_hunk` 추적과 삽입 hunk 의 인접 줄 앵커링을 추가합니다.
- **트레이드오프**: 키 영향은 없습니다.

### R18. 동일한 줄 하나를 기각하면 같은 파일의 같은 줄(미래 것 포함)이 모두 가려진다

- **영역**: 기각 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**: 키에 위치 정보가 없습니다(`scripts/lib/candidate.py:47-50`). 매칭은 `(rule, file, hash)` 입니다(`scripts/lib/dismiss.py:54-55`). 경로는 `strip`·`replace(os.sep)` 만 하고 정규화하지 않습니다(`scripts/lib/dismiss.py:92`).
- **재현**
  - `M/r1`: `dd($user);` 두 줄이 같은 키 `0d9cff6261` 를 받습니다.
  - CYC `s2_dup.py`: 테스트 픽스처 줄을 기각하면 핸들러의 진짜 위반과 새로 추가한 같은 줄까지 사라집니다.
  - DET `f13`: `file: ./a.php` 기각은 적용되지 않는데 `dismissed: 2` 로 셉니다.
- **제안**
  - (a) 키에 순번을 넣습니다. 줄이 삽입되면 불안정해서 기각합니다.
  - (b) 선택 필드 `context`: 가장 가까운 비어 있지 않은 이웃 줄의 해시나 감싸는 블록 헤더입니다. 있을 때만 대조합니다.
  - (c) `dismiss.py` 가 같은 해시의 후보 수를 세어, 2개 이상이면 `--all-identical` 없이는 거부하고 몇 개가 가려지는지 알립니다.
  - **선택**: (c) 를 지금 하고, 경로를 `posixpath.normpath` 로 정규화하며, 모르는 규칙 id 는 경고합니다. (b) 는 opt-in 으로 나중에 합니다.
- **선택 이유**: 엔진, 지문, 골든을 건드리지 않고 사람이 모르고 과잉 기각하는 일을 막습니다.
- **트레이드오프**: (c) 는 기각 **뒤에** 추가되는 같은 줄은 막지 못합니다. 그것은 (b) 만 해결합니다.

### R19. 삭제만 한 변경이 file·paired 앵커에 보이지 않는다

- **영역**: 범위·앵커 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**: 추가된 줄이 없는 파일은 범위에서 빠집니다(`scripts/lib/gitdiff.py:268`). file 앵커는 매치 구간과 추가된 줄의 겹침만 봅니다(`scripts/lib/detect.py:207-209`). paired 는 `scope.paths()` 만 봅니다(`detect.py:159-165`).
- **재현**
  - DET `f14` A: 레거시 catch 본문의 `report($e);` 를 지워 catch 를 비웠습니다 → 후보 0. 기대는 1입니다.
  - DET `f14` B: 본문 줄을 빈 줄로 바꿨습니다 → 후보 0. 빈 줄은 추가된 줄이지만 헤더 매치 구간 밖입니다.
  - DET `f9` A: 라우트를 추가하고 테스트 파일에서 줄만 지웠습니다 → paired 가 발동합니다. 오탐입니다.
- **제안**
  - (a) `parse_diff` 가 삭제 지점(`+N,0` hunk 의 새 쪽 줄)을 "터치 지점"으로 기록하고, 삭제만 한 파일도 범위에 남깁니다. file 앵커는 추가된 줄과 터치 지점 모두와 겹침을 봅니다. paired 는 모든 변경 파일 이름을 봅니다.
  - (b) `block_empty` 규칙에 한해 겹침 창을 감싸는 블록의 줄 범위로 넓힙니다. 구조 데이터는 이미 손에 있습니다.
  - **선택**: (a)+(b). (a) 가 A 와 paired 사례를, (b) 가 B 를 고칩니다.
- **트레이드오프**: 린터가 삭제만 한 파일도 받게 됩니다. 거기서 나온 지적은 참고로만 씁니다.

### R20. 큰 파일은 조용히 건너뛰고, 바이너리는 확장자 목록으로만 거른다 (기준 4)

- **영역**: 범위 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**: `SKIP_EXT` 확장자 목록과 400KB 상한이 있고, 건너뛴 기록은 남기지 않습니다(`scripts/lib/gitdiff.py:20-25`, `:130-137`). `read_lines` 는 줄마다 `text.count('\n')` 을 불러 O(n²) 입니다(`gitdiff.py:151-157`).
- **재현**
  - DET `f10`: 420KB `big.php` 의 `dd(` 는 아무 알림 없이 통과합니다. `data.sqlite` 는 `\x00` 이 들어간 스니펫으로 걸립니다.
  - `read_lines` 는 직접 측정했습니다: 10,000줄 65ms, 40,000줄 977ms.
  - COL R11: 99,000줄짜리 396KB `data.csv` 하나로 Stop 이 8.9초 걸립니다.
- **제안**
  - (a) 앞 8KB 에 NUL 바이트가 있으면 바이너리로 봅니다(git 과 같은 휴리스틱). `SKIP_EXT` 는 생성된 텍스트(`.lock`, `.svg`)를 위한 명시 정책으로만 남깁니다 ← **선택**.
  - (b) `git diff --numstat` 의 `-` 표시를 씁니다. untracked 파일을 못 봅니다.
  - 크기 때문에 건너뛴 파일은 `Result.unchecked` 에 `too_large` 로 기록합니다. "못 읽은 것을 통과로 처리하지 않는다"는 원칙에 맞춥니다.
  - `read_lines` 는 `text.split('\n')` 한 번과 마지막 빈 요소 제거로 바꿉니다. `splitlines()` 는 `\x0b`, `\x0c` 에서도 나눠 git 의 줄 번호와 어긋나므로 쓰지 않습니다.
- **트레이드오프**: 전체 파일을 읽는 경로에서만 8KB 를 더 읽습니다. 키 영향은 없습니다.

### R21. 컨텍스트 팩의 import 탐지와 Python 블록 경계가 키워드 목록과 들여쓰기 휴리스틱에 의존한다 (기준 4)

- **영역**: 의미 판정 팩 · **우선순위**: 중간 · **확신도**: 높음
- **현재 로직**
  - import 는 `IMPORT_RE` 접두 목록으로 찾고, 앞 150줄 원문만 봅니다. 마스킹도, 여러 줄 이어짐도 고려하지 않습니다(`scripts/lib/context.py:44-46`, `:188-194`).
  - Python 블록은 들여쓰기만으로 끝을 정합니다. 문자열·주석을 고려하지 않고 데코레이터도 빠집니다(`scripts/lib/structure/native/scopes.py:277-299`).
  - `PACK_SCOPES={'py':…}` 는 엔진 코드에 박힌 언어 이름입니다(`context.py:139`).
  - JS 콜백은 `function` 콜백이면 팩이 콜백 하나로 좁아지고, 화살표 콜백이면 바깥 함수 전체가 됩니다(`scripts/lib/structure/native/scopes.py:257-266`).
- **재현**
  - SEM `r9_imports.py`: Go `import (` 블록은 첫 줄만 잡힙니다. PHP 클래스 안의 trait `use SoftDeletes;` 는 import 로 잡힙니다. docstring 안의 `import this…` 도 잡힙니다.
  - SEM `r1`, `r5`: Black 스타일 시그니처는 클래스 전체로 잡힙니다. 0열 `# 주석` 이 있으면 None 이 됩니다. `@transaction.atomic` 을 지워도 키가 그대로입니다. JS `function` 콜백 팩에서는 바깥 `.with('items')` 를 지워도 키가 그대로라 캐시가 오래된 채 남습니다.
- **제안**
  - import: (a) `LangDef.import_pattern` 필드를 두고, 괄호가 맞을 때까지 이어 읽으며, 주석·문자열 구간을 뺍니다 ← **선택**. (b) 정규식 하나에 접두를 더 추가합니다.
  - Python: R1 의 `ast` 1차와 들여쓰기 폴백을 그대로 씁니다. 폴백은 괄호 균형 뒤부터 들여쓰기를 세고, skip 구간 안의 줄과 주석만 있는 줄은 건너뛰며, `@` 줄은 헤더에 포함합니다.
  - 콜백 팩: `_function_region` 이 "부모가 같은 Span 의 loop 인 function"(콜백 표지)을 건너뛰고 그다음 바깥 함수를 쓰게 합니다. `in_scope` 는 그대로 둡니다.
  - `PACK_SCOPES` 는 `LangDef` 필드로 옮깁니다.
- **트레이드오프**: 영향받는 팩 해시가 한 번 바뀝니다.

### R22. 글롭 번역기가 일부 문법을 조용히 매치 실패시킨다

- **영역**: 규칙 적용 필터 · **우선순위**: 낮음~중간 · **확신도**: 높음
- **현재 로직**: `{a,b}` 의 각 대안을 `re.escape` 로 넣습니다. 그 밖의 문자도 전부 이스케이프합니다(`scripts/lib/rules/select.py:33-43`). 로드할 때 검증하지 않습니다.
- **재현**: 직접 확인했습니다. 다음은 모두 False 입니다.
  - `**/{*.test.ts,*.spec.ts}` → `src/a.test.ts`
  - `**/[Tt]ests/**` → `src/Tests/a.php`
  - `vendor/` → `vendor/a.php`
  - `**/*.php` → `app/A.PHP` (대소문자 구분)
- **제안**
  - (a) 대안을 재귀 번역하고 `[...]` 를 지원합니다. 앞이나 뒤에 붙은 `/` 는 `RuleError` 로 거부합니다 ← **선택**.
  - (b) 로드할 때 경고만 합니다.
- **선택 이유**: 번들 글롭은 리터럴 대안만 써서 의미가 바뀌지 않습니다. 팀 규칙이 조용히 꺼지는 것을 막습니다.

### R23. 기타 (낮음)

| # | 내용 | 위치 | 재현 | 제안 (선택) |
|---|---|---|---|---|
| a | 판정 대상 언어가 확장자 표에 없으면 구조 조건이 UNKNOWN 이 됩니다. 누락: `.mts`, `.cts`, `.vue`, `.svelte`, `.hpp`, `.kts`, `.pyi` | `scripts/lib/structure/native/langs.py:139`, `:247-257` | DET `f12` | 확장자를 추가하고, 규칙 글롭이 쓰는 모든 언어에 정의가 있는지 테스트로 강제합니다 / 스택 린터 글롭에서 도출(대안) |
| b | 경로 견고성: symlink 경로와 중첩 worktree 는 조용히 누락되고, `..foo` 파일은 거부되며, 따옴표가 든 경로와 lone CR 은 줄 어긋남을 만듭니다 | `scripts/lib/hooks.py:107-114`, `scripts/lib/gitdiff.py:160-166`, `:140-148` | COL R7, R13, R16, R12 | realpath, `rel == '..' or startswith('../')`, `-z`, `newline=''`. 어느 파일에도 속하지 않는 touched 는 "검사되지 않음"으로 표시 / 루트별 스캔(대안) |
| c | 세션 base 가 7일 GC 로 사라집니다(mtime 을 갱신하지 않음) | `scripts/lib/state.py:77-81`, `:157-168` | 코드 인용만 | 이미 있을 때 `os.utime` 으로 갱신 / touched mtime 을 GC 기준으로(대안) |
| d | Pre 스냅샷이 없으면 Bash 변경이 조용히 누락됩니다 | `scripts/lib/hooks.py:93-95` | 코드 인용만 | "Bash 변경 미수집" 플래그를 두고 Stop 에서 알림 / stat 지문으로 Pre 를 가볍게(대안) |
| e | `EDIT_TOOLS` 고정 목록이라 MCP 등 다른 편집 도구는 수집되지 않습니다 | `scripts/lib/hooks.py:30-31`, `hooks/hooks.json:18` | 코드 인용만 | 도구 목록을 설정 가능하게 / `.*` 매처 + Bash 지문 경로(대안, 호출마다 비용) |
| f | 재포맷하거나 이동한 위반이 "고쳐짐 1 · 새로 생김 1"로 기록됩니다. 차단 판단은 맞지만 튜닝 지표가 왜곡됩니다 | `scripts/lib/cycle.py:71-86` | CYC `s4_reformat.py` | 남은 fixed 와 new 를 같은 규칙·같은 파일(또는 같은 해시·다른 파일)로 짝지어 still(변경/이동)로 재분류 / 정규화 강화(기각, 전 지문 변경) |
| g | 버전 제약이 느슨합니다(`>=10 <12` 의 상한 무시, `^10` 은 규칙을 억제) | `scripts/lib/stack.py:120-133` | DET 직접 호출 | `schema.normalize` 에서 엄격한 문법 검증 / 문서화만(대안) |
| h | paired 앵커가 `applies_to.files` 를 무시합니다 | `scripts/lib/detect.py:159-162` | DET `f9` | 그 조합을 `RuleError` 로 / 추가 필터로 적용(대안) |
| i | 경고 우선순위를 메시지 부분 문자열 `'검사되지 않았습니다'` 로 정합니다 | `scripts/lib/hooks.py:194-199`, `scripts/lib/lint.py:218-222` | 코드 인용만 | 노트에 종류 필드를 둡니다 / 공유 상수(대안) |
| j | `verdicts.json` 을 쓸 때 정리하지 않고 잠금도 없습니다 | `scripts/lib/semantic.py:68-78` | 코드 인용만 | 쓸 때 TTL 이나 상한으로 정리 / JSONL 추가 전용(대안) |
| k | 죽은 코드 `FUNCTION_PATTERNS['py']`, `PY_CLASS`, `PY_EXCEPT`. 또 `test_determinism` 이 언어 이름 문자열만 막아서 `scopes.py:36` 의 Python 문법 하드코딩을 통과시킵니다 | `scripts/lib/structure/native/langs.py:46-49`, `scripts/lib/structure/native/scopes.py:36` | 코드 인용만 | 삭제하고, 테스트가 `scopes.py`·`mask.py` 의 `re.compile` 리터럴도 검사하도록 확장 |
| l | 긴 함수 팩이 예산 80줄 중 22줄만 씁니다 | `scripts/lib/context.py:67-88` | SEM `r12_clip.py` | 남은 예산을 가운데 창에 배분 |

---

## 3. 선택적 백엔드

외부 라이브러리로만 풀리는 문제와 폴백 구조를 모았습니다.

- **tree-sitter (구조 계층)**
  - **해결 범위**
    - R1: 노드 타입으로 loop·class·catch 를 판별합니다. `::class`, `.find(` 같은 멤버 접근 오분류가 사라집니다.
    - R2: `method_definition`, `arrow_function`, `func_literal`, `closure_expression`, `lambda_expression` 으로 함수를 판별합니다.
    - R9: JSX, Rust lifetime, raw 문자열, 정규식과 나눗셈 구분을 처리합니다.
    - R21: import 노드로 import 를 찾습니다.
  - **구조**: `backend.register(b, languages=…)` 가 이미 언어별 등록을 지원합니다(`scripts/lib/structure/backend.py`).
    - `import tree_sitter` 와 문법 패키지는 try 로 감쌉니다. 없으면 `supports()` 가 False 를 돌려 native 백엔드로 폴백합니다. PyYAML/miniyaml 과 같은 구조입니다.
    - 노드 타입 → kind 매핑은 문법별 데이터 표로 둡니다.
    - `has_error` 노드가 있으면 `ok=False` 로 답합니다(현재 계약 유지).
  - **주의**
    - 문법 버전이 다르면 판정이 달라집니다. `FileStructure.backend`(`scripts/lib/structure/model.py:117`)에 백엔드 이름과 문법 버전을 넣어 미확인 알림과 로그에 드러내야 합니다.
    - native 와 tree-sitter 의 동등성 테스트는 `tests/unit/test_yaml_parity.py` 처럼 "양쪽 모두 통과"를 릴리스 조건으로 둡니다.
  - **계획상 위치**: 메모상 tree-sitter 는 3.3 목표입니다. R1·R2·R9 의 표준 라이브러리 개선은 그 전에 폴백 품질로서 필요합니다.
- **Python `ast`**: 표준 라이브러리이므로 선택적 백엔드가 아닙니다. R1·R21 의 1차 경로로 바로 쓸 수 있습니다. 3.9 의 `ast` 는 `match` 문과 3.12 f-string 을 파싱하지 못하므로, 폴백은 반드시 남겨야 합니다.
- 그 밖에 외부 라이브러리가 있어야만 풀리는 문제는 찾지 못했습니다. 수집·범위·사이클·캐시 문제는 모두 git CLI 와 표준 라이브러리로 해결됩니다.

---

## 4. 실행 기록

| 명령 (사본 `scratchpad/src`, 또는 git 이 필요하면 `scratchpad/clone`) | 결과 |
|---|---|
| `.venv/bin/python tests/run_all.py` (PyYAML 6.0.3) | **전체 통과, exit 0**, 약 42초. 픽스처 137개, 규칙 36개, 경고 0 |
| `CONVENTION_GUARD_NO_PYYAML=1 .venv/bin/python tests/run_all.py` | **전체 통과, exit 0**, 약 38초 |
| `python3 tests/perf/run.py --corpus both` (structure_only) | 100줄 중앙값 0.239ms / 1,000줄 2.157ms / 10,000줄 23.668ms / 캐시 적중 0.005ms. 목표(0.5 / 5 / 60 / 0.05ms) 모두 OK |
| `python3 tests/perf/run.py --corpus both --stage end_to_end` (clone 에서) | 파일 60개, 후보 0건 Stop 훅 **중앙값 116.0ms** (110.8~153.6). 기준선(master) 125.0ms, 예산 187.5ms 안. 조건 규칙 수(0/5/10/20)에 따른 증가는 잡음과 구분되지 않습니다. `docs/development.md:97` 의 "~60ms" 와 약 2배 차이지만 WSL2 환경 영향일 수 있습니다. 순수 `python3 -c pass` 기동은 6ms 입니다 |
| end_to_end 를 archive 사본에서 실행 | `git worktree add … master` 실패(.git 없음). 로컬 clone 으로 다시 돌렸습니다 |
| `scan.py --cwd M/r1 --rule php-no-debug-output --json` | 8행 미탐(R5), 9·10행이 같은 키 `0d9cff6261`(R18) |
| `scan.py --cwd M/req --rule laravel-controller-needs-validation` | 주석 한 줄로 7행 후보가 사라짐(R6) |
| `M/struct_repro.py` | 구조 분류 20건 중 7건이 기대와 다름(R1, R2, R10), CRLF 로 판정이 뒤집힌 경우 0건 |
| 서브에이전트 재현 | COL 16건, DET 16건, STR 13건, SEM 14건, CYC 10건. 핵심 사례(CYC s1/s5/s7, SEM r2/r4, COL r8c, STR 9건)는 직접 다시 돌려 같은 결과를 확인했습니다 |
| 인용 검증 | 이 보고서의 모든 `경로:줄` 을 스크립트로 HEAD 사본에서 확인했습니다: 파일이 있는지, 줄 범위가 파일 길이 안인지. 서브에이전트가 틀리게 인용한 줄(candidate.py 108행, dismiss.py 219행, conditions.py 163행 등 — 실제 파일 길이 밖)은 직접 연 줄로 바꿨습니다 |

레포 파일은 수정하지 않았습니다. 재현 파일, 사본, clone, 메모(`scratchpad/analysis-notes.md`)는 모두 스크래치패드에 있습니다.
