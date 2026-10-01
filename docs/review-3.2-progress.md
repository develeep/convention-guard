# review-3.2 수정 진행

- 보고서: `docs/review-3.2.md` (기준 커밋 `889c2f9`, 3.2.0)
- 브랜치: `fix/review-3.2` (master `889c2f9` 에서 분기)
- 보관: `stash@{0}` "pre-review-3.2 작업 트리" (foreign 기준선 미커밋 작업 + docs/design-review.md, skills-lock.json)
- 커밋하지 않는다. 골든 변화 설명은 이슈 항목에 적는다.
- 재개 절차: 이 파일, `git status`, `git stash list` 를 읽고 체크되지 않은 첫 이슈부터 진행한다.

## 재개 안내 (2026-09-30 세션 중단 시점)

- **완료**: A 구조 계층 전부(R1, R2, R10, R9, R23k, R23a), R5, R6, R11, R18, R19, R23h(+R9 보완), R22, R23g, R13, R20, R14, R15, R23b, R12, R23c·d·e, R4, R3, R17, R23f, R23i, R16, R7, R8, R21, R23l, R23j. R21 의 콜백 팩 항목은 R2 에서 앞당겨 끝냄
- **상태**: 32개 항목과 마무리 모두 완료(2026-10-01). 커밋은 사용자가 한다. 릴리스 때 `docs/migration-*.md` 에 R11 지문 변경·R8 판정 캐시 1회 만료·R22/R23g/R23h 로드 오류 가능성을 적는다. 성능 하네스(스크래치패드 출력) 목표 모두 OK
- **작업 트리 상태** (중단 시점, 커밋 없음): 이 브랜치의 미커밋 변경이 곧 지금까지의 작업이다. `git diff --stat` 으로 확인. 새 파일: `scripts/lib/structure/native/pyast.py`, 이 파일, `docs/review-3.2.md`
- **stash**: `stash@{0}` 는 손대지 않았다(pop/drop 안 함). R12 에서 그 안의 foreign 기준선 구현을 이 브랜치로 옮겼다. 남은 stash 고유 내용은 README 의 design-review 행, `docs/design-review.md`, `skills-lock.json`(untracked). stash 를 pop 하면 옮긴 부분과 충돌하므로, 정리는 사용자가 정한다
- **CLAUDE.md**: 작업 트리의 수정본(foreign 기준선 설명 포함)이 그대로 있다. R12 이후 그 설명은 이 브랜치 코드와 맞다
- **확정 의도** (리뷰 때 사용자가 정함): R6 주석 안 매치 제외·문자열 제외는 규칙별 opt-in / R4 연속 차단 상한은 요청 안의 루프 가드 / R10 in_scope 는 본문만(완료) / R7 의미 판정은 함수 단위 유지, 배치에 함수 안 후보 전부
- **AIDLC 워크플로 미적용**: 이 작업은 리뷰 보고서 이슈 수정이라 /root/CLAUDE.md 의 AIDLC(aidlc-docs/, audit.md)는 쓰지 않는다
- **주의**
  - `tests/perf/run.py` 는 `--json` 을 주지 않으면 추적 파일 `tests/perf/results/u1-structure-only.json` 을 덮어쓴다. 이미 한 번 덮어썼고 사용자가 그대로 두기로 했다. 이후에는 `--json <스크래치패드>/perf.json` 으로 돌린다. `tests/perf/fp_reduction.py` 도 `--json` 으로
  - 되돌리는 git 작업(stash pop/drop, reset, checkout -- 파일, clean)은 실행 전에 확인받는다
  - 새 언어 행(`kotlin`, `ts`, `swift`, `csharp`, `dart`, `vue`, `svelte`)을 더할 때는 `scripts/lib/migrate.py` `FIXTURE_COMMENT` 도 본다(vue·svelte 는 조각이 템플릿 텍스트가 되므로 넣지 않았다)
  - 보고서 재현 파일: `/tmp/claude-0/-root-convention-guard/e544610c-456f-4d16-b4d5-624f824704c9/scratchpad/` (`repro-*`, `analysis-notes.md`, HEAD 사본 `src/`). 없어졌으면 보고서의 재현 설명으로 다시 만든다

## 기준선

- 2026-09-30 `fix/review-3.2` 분기 직후 `.venv/bin/python tests/run_all.py --quiet`: 전체 통과 (약 35초)

## 처리 순서

승인: 2026-09-30. 층별로 묶고, 다른 이슈가 재사용하는 기반을 먼저 한다.

**A. 구조 계층**
- [x] 1. R1 헤더 토크나이저 + langs 데이터 필드 + Python ast — R2(c)·R9(b)·R21·R23k 가 재사용하는 기반
- [x] 2. R2 함수 판별 — (c) lambda_heads 가 R1 필드를 쓴다
- [x] 3. R10 in_scope 본문 Span + laravel-n-plus-one — 분류가 안정된 뒤라 골든 diff 를 이 변경 하나로 설명
- [x] 4. R9 마스킹 데이터·JSX — (b) 가 R1 토크나이저의 제어문 `)` 표시를 쓴다
- [x] 5. R23k 죽은 Python 패턴 삭제·결정성 테스트 확장 — R1 이 scopes.py:36 을 데이터로 옮긴 뒤
- [x] 6. R23a 확장자 누락 — R9 가 Kotlin/Swift/C#/Dart 행을 분리한 뒤

**B. 탐지·앵커·후보 키**
- [x] 7. R5 line 앵커 finditer (detect.py + fixtures.py)
- [x] 8. R6 requires/absent 주석 제외·BOM — detect.py 를 R5 다음에
- [x] 9. R11 전체 줄 지문 + 이중 매칭 — 키에 의존하는 R18·R19 보다 먼저 (R6 이월 BOM 1행 변형 포함)
- [x] 10. R18 기각 중복 수 확인·normpath — R11 의 새 해시 기준
- [x] 11. R19 삭제 터치 지점·block_empty 창 — R11 의 file 앵커 공백 절단 뒤
- [x] 12. R23h paired 의 applies_to.files — R19 가 paired 를 고친 뒤 (+ R9 보완: JSX 텍스트 경계)
- [x] 13. R22 글롭 번역기 (독립)
- [x] 14. R23g 버전 제약 검증 (독립)

**C. 수집·범위**
- [x] 15. R13 diff 플래그 고정 — 이후 범위 변경의 기준 diff 를 먼저 확정
- [x] 16. R20 NUL 바이너리·too_large 기록·read_lines O(n)
- [x] 17. R14 rename·새 파일 diff-filter=A·빈 레포 base
- [x] 18. R15 staged/range 본문을 blob 에서 — R20 의 scannable 크기 검사를 blob 으로 옮기므로
- [x] 19. R23b 경로 견고성
- [x] 20. R12 줄 기준선 + Pre/Post 기준 불일치 — stash 의 (a) 구현을 손으로 옮김
- [x] 21. R23c·d·e base mtime·Pre 스냅샷 누락·EDIT_TOOLS — R12 가 바꾼 Pre/Post 경로 위에서

**D. Stop 정책·사이클**
- [x] 22. R4 streak 요청 경계 초기화
- [x] 23. R3 (+C6·C9) 미표시 error
- [x] 24. R17 린터 미완료 키 still — R3 이 닫는 메시지 종류를 정한 뒤
- [x] 25. R23f fixed/new 짝짓기 — cycle.py 를 R3·R17 다음에
- [x] 26. R23i 노트 종류 필드 — R17 이 lint 노트를 고친 뒤
- [x] 27. R16 autofix 바이트 처리 (독립)

**E. 의미 판정**
- [x] 28. R7 배치에 함수 안 후보 전부
- [x] 29. R8 related_hash 전체 파일·블록 순서·imports 해시
- [x] 30. R21 import_pattern·Python 블록·콜백 팩·PACK_SCOPES — R1·R8 다음 (콜백 팩은 R2 에서 앞당겨 완료)
- [x] 31. R23l 가운데 창 예산 배분 — R8·R21 다음
- [x] 32. R23j verdicts.json 정리·잠금

**마무리**
- [x] `CONVENTION_GUARD_NO_PYYAML=1 .venv/bin/python tests/run_all.py` — 2026-10-01 전체 통과(PyYAML 있음 `--quiet` 도 전체 통과)
- [x] 전체 요약 (세션 응답으로 전달)

## 이슈별 기록

### R1 — 블록 종류를 헤더 토큰으로 판별 ✅

- 선택: (b)+(c) 헤더 토크나이저 + 괄호 수준 / Python 은 `ast` 1차 + 들여쓰기 폴백 / Kotlin 행을 R1 에서 분리
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: `ITERATION_CALLS` 정규식 → `ITERATION_METHODS`·`ITERATION_FUNCTIONS` 이름 목록. `LangDef` 에 `iteration_methods`, `iteration_functions`, `lambda_heads`, `member_ops`, `trailing_lambdas`, `newline_ends_statement`, `indent_headers`, `parser` 추가, `iteration_call` 제거. `kotlin` 행 신설(`.kt`, 마스킹은 java 와 동일)
  - `scripts/lib/structure/native/scopes.py`: `_classify` 를 토큰 방식으로 교체(`_tokenizer`, `_brace_level`, `_iterates`, `_iteration_name`). `_statement_start` 가 줄바꿈 종결 언어에서 `;` 대신 줄바꿈(Go 세미콜론 삽입 규칙 + `.`/`?.`/`&&`/`||`/`?:` 이어짐)을 경계로 씀. `_PY_HEADER` 하드코딩 → `langdef.indent_headers`
  - `scripts/lib/structure/native/pyast.py` (신규): `ast` 로 def/class/except/for/while/컴프리헨션 노드. 블록 끝은 1.x 와 같게 `end_lineno` 뒤를 들여쓰기 규칙으로 늘림. 파싱 실패나 lone CR 이면 None → 들여쓰기 폴백
  - `scripts/lib/migrate.py`: `FIXTURE_COMMENT` 에 `kotlin` 추가
  - `docs/rules.md`(블록 종류 판정 설명, 지원 언어에 Kotlin), `docs/semantic-review.md`(Python 경계)
- 추가한 테스트: `tests/structure/test_scopes.py` `case_header_tokens`(Go 3절 for·if-init·`chan struct{}` 뒤 for, `repo.find({`, `if (xs.some(..))`, `n.class`, `.catch/.finally(cb)`, 세미콜론 없는 JS, PHP `::class` foreach, Kotlin forEach·repeat·fold·줄 이어진 체인, Python for/while/async for/컴프리헨션), `case_python_fallback`(SyntaxError → 들여쓰기)
- 바꾼 기존 테스트 (이 수정의 직접 결과)
  - `test_scopes.py` `case_python`: Python 노드에 loop 추가 → `['class', 'function', 'loop', 'catch']`
  - `test_langs.py`: `.kt` → `kotlin`, 언어 9개, Python 은 `indent_headers`·`parser` 로 확인
- 테스트 결과: RED 11건 확인 → GREEN. `run_all.py --quiet` 전체 통과. 보고서 `struct_repro.py` 20건 중 R1 대상 전부 기대와 일치(남은 D·H 는 R10·R2 대상)
- 골든: `tests/integration/golden/parity.json` 변화 없음(갱신 안 함)
- 지문·캐시: 필터 계층이라 후보 지문·기각 영향 없음. Python 함수 노드 끝 줄은 1.x 와 같게 유지해서 컨텍스트 팩 해시도 보통은 그대로
- 트레이드오프·한계
  - 보고서의 `modifiers` 필드는 넣지 않았다. "첫 토큰"이 아니라 "블록 수준의 자유 키워드"로 판정해서 수식어를 건너뛸 필요가 없다
  - JS 반복 호출은 이제 멤버 호출(`.map(`)만 인정한다. 맨 이름 `map(xs, x => {` 는 loop 가 아니다(PHP `array_map` 류와 Kotlin `repeat` 만 맨 이름 목록)
  - 줄바꿈 종결 언어(Go, Kotlin)에서 한 줄에 `a := 1; for {` 처럼 쓴 문장은 앞 문장과 한 헤더로 읽는다
  - Python `ast` 는 훅을 실행하는 인터프리터 문법을 따른다. 3.9 에서 못 읽는 파일은 폴백으로 가므로 팀원 사이에 Python 버전이 다르면 구조 판정이 다를 수 있다(보고서 3장이 예고한 사항)
- 성능: `tests/perf/run.py --corpus both` 합성 코퍼스 목표 모두 OK(10,000줄 중앙값 26.5ms). cache-hit MISS 는 레포 밖 `.claude/skills/archify/` 파일 때문(추가 발견 참고)
- 주의: 성능 하네스가 추적 파일 `tests/perf/results/u1-structure-only.json` 을 덮어썼다. 사용자 결정으로 그대로 둔다(커밋할 때 사용자가 정한다). 이후 성능 확인은 `--json` 을 스크래치패드로 돌린다

### R2 — 함수 판별 구멍 ✅

- 선택: (a)+(b)+(c)+C `NOT_A_NAME`. (c) 때문에 깨진 기존 팩 테스트를 지키려고 R21 의 콜백 팩 수정을 앞당김(사용자 결정)
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: JS 메서드 대안 `\{\s*$` → `\{?\s*$`. C 패턴 이름 앞에 `NOT_A_NAME`. `lambda_heads`: go `func`, rust `|`·`||`, java 계열 `->`·`=>`·`func`. java 계열 `branch_keywords` 에 `case`·`default`(switch 화살표 arm 이 람다로 잡히지 않게). `optional_semicolons` 필드(JS)
  - `scripts/lib/structure/native/scopes.py`: `_signature`(줄마다 → 안 되면 한 줄로 합친 시그니처, optional_semicolons 언어는 마지막 문장만 `_last_statement`), `_lambda_body`(화살표는 키워드가 없는 수준에서만, 키워드 머리는 블록 수준 자유 토큰). `_iterates` 가 `_lambda_body` 를 공유
  - `scripts/lib/context.py` `_function_region`: 같은 body 의 loop 를 부모로 둔 function(반복 콜백)은 건너뛰고 바깥 함수를 팩 단위로 씀 (R21 의 콜백 팩 항목)
  - `docs/rules.md`(function 범위), `docs/semantic-review.md`(콜백은 판정 단위가 아님)
- 추가한 테스트
  - `tests/structure/test_scopes.py` `case_functions` 14건: JS 메서드·여러 줄 메서드·화살표 콜백·클래스 필드 화살표, 세미콜론 없는 JS 의 호출 줄 뒤 if, PHP 익명 function, Go defer func, Rust 클로저, Java 람다, Java switch 화살표 arm, Java 여러 줄 시그니처·다음 줄 throws, Swift `-> Int`, C else-if
  - `tests/semantic/test_context_pack.py` `case_js_methods_and_callbacks`: JS 메서드 팩, 반복 화살표 콜백의 팩이 바깥 메서드
- 바꾼 기존 테스트 (이 수정의 직접 결과): `test_scopes.py` 콜백 반복 3건(화살표·Laravel each·array_map)과 R1 의 화살표 사례가 `['loop', 'function']`
- 테스트 결과: RED 15건(+팩 1건) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 지문·캐시: 후보 지문 영향 없음. 의미 판정 팩은 JS 메서드·비반복 콜백 안의 후보에서 ±30줄 창 → 감싸는 함수로 바뀌어 `context_hash` 가 한 번 바뀐다(재판정 1회). 반복 콜백 안의 후보는 전과 같이 바깥 함수가 단위라 PHP·JS 모두 그대로(JS `function` 콜백은 콜백 → 바깥 함수로 바뀌어 한 번 재판정)

### R10 — in_scope 는 본문만 ✅

- 선택: (a) 본문 Span 포함 + laravel-n-plus-one 에서 `in_scope: loop` 제거
- 바꾼 파일
  - `scripts/lib/structure/model.py`: `FileStructure.scopes_around(offset)` — body 가 오프셋을 품는 스코프 사슬
  - `scripts/lib/structure/conditions.py` `_in_scope`: `scopes_at(line_of(start))` → `scopes_around(span.start)`
  - `rules/php/laravel/laravel-n-plus-one.yaml`: `in_scope: loop` 제거(`not_in` 유지), match 픽스처에 중괄호 없는 한 줄 반복 `->map(fn ($u) => …)` 추가
  - `docs/rules.md`: `in_scope` 는 본문만, 헤더 줄 트리거 규칙에는 붙이지 말 것
- 추가한 테스트: `tests/structure/test_conditions.py` `case_in_scope` 8건(헤더의 iterable, 같은 줄 `}` 뒤 문장, foreach 키워드 자체, Python for 헤더, 각 본문 대조), 규칙 match 픽스처 1건
- 테스트 결과: RED(구조 4 + 픽스처 1) → 엔진 수정 뒤 보고서가 예고한 기존 match 픽스처 2건 실패 → 규칙 수정 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(골든에 이 규칙 사례가 없다)
- 지문·캐시: 지문 영향 없음. laravel-n-plus-one 의 detect 가 바뀌어 이 규칙의 의미 판정 캐시가 한 번 만료된다. 한 줄 `->map(fn …)`·`->each($callable)` 처럼 중괄호 블록이 없는 반복도 이제 리뷰어에게 가서 호출이 늘 수 있다
- `tests/perf/fp_reduction.py`(스크래치패드로 출력): laravel-n-plus-one 조건 없음 3 → 조건 적용 1, 제거 2건으로 기록값(`u3-fp-reduction.json`)과 같다

### R9 — 마스킹 실패 하나가 파일 전체를 끈다 ✅

- 선택: (a)+(b)+(c) 전부, JSX 자식 텍스트는 문자열로 기록
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: `Delim.guard`(여는 따옴표 뒤 lookahead), `CHAR_LITERAL`/`CHAR_QUOTES`(Rust·C 의 `'` 는 문자 리터럴 모양일 때만 문자열), C 에 `R"(…)"`, `LangDef.jsx`. 행 분리: `ts`(`.ts`, JSX 없음), `swift`(`#"…"#`·`#"""`, `'` 는 구분자 아님, 중첩 블록 주석, 줄바꿈 종결), `csharp`(`@"…"` 에 `""` 이스케이프, `foreach` loop), `dart`(`${}` 보간, 중첩 블록 주석). java 행은 `.java`·`.scala` 만
  - `scripts/lib/structure/native/mask.py`: 정규식 문맥을 여집합으로(`_VALUE_END`, `_closes_control_header`). 한 글자 이스케이프만 다음 글자를 먹음(`""` 은 그 자체로 끝). heredoc 패턴 = 종료자|esc|interp(nowdoc 은 종료자만). JSX 프레임 `jsx_tag`/`jsx_text`(`_jsx_can_start`, `_step_jsx`), 닫히지 않으면 `unterminated_jsx:N`
  - `scripts/lib/migrate.py`: `FIXTURE_COMMENT` 에 새 언어 키
  - `docs/rules.md`: 지원 언어, JSX 텍스트는 문자열
- 추가한 테스트: `tests/structure/test_mask.py` `case_r9_regex_context`(`=>`·`+`·`if (x)`·`while (x)` 뒤 정규식, `a++`·`)`·문자열 뒤 나눗셈), `case_r9_char_literals`(Rust lifetime·문자 리터럴 4종, C++ `1'000'000`), `case_r9_raw_strings`(C# 축자 2건, Swift raw, C++ raw, Swift·Dart 중첩 주석, Dart 보간), `case_r9_heredoc_interpolation`, `case_r9_jsx`(아포스트로피, 중첩 컴포넌트·속성·프래그먼트·map 안 JSX, 비교 연산자, `.ts` 제네릭, 닫히지 않은 JSX)
- 바꾼 기존 테스트: `test_langs.py` 확장자 표(`.ts`→ts, `.cs`→csharp, `.swift`→swift, `.dart`→dart)와 언어 13개
- 테스트 결과: RED 6건(+새 언어 없음 오류) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 지문·캐시: 필터 계층이라 지문 영향 없음. 지금까지 ok=False 이던 파일(화살표 뒤 정규식, JSX 아포스트로피, Rust lifetime 등)이 판정되기 시작해 "구조 미확인" 알림이 줄고, `not_in` 규칙의 후보가 줄거나(주석·문자열 안 매치 제외) 달라질 수 있다
- 성능: `run.py --corpus synthetic`(스크래치패드 출력) 목표 모두 OK. 10,000줄 중앙값 29.9ms / worst 42.9ms (HEAD 22.2 / 28.3, R1 뒤 26.5 / 34.8). JSX 가 빽빽한 2,000줄 21.9ms(마스킹 5.5ms + 스코프 16.8ms)
- 한계
  - 정규식 문맥에서 `}` 뒤는 지금처럼 정규식으로 읽는다(블록 뒤인지 객체 리터럴 뒤인지 모른다)
  - 제어문 `)` 판정은 R1 토크나이저가 아니라 64자 lookbehind 안의 괄호 짝으로 한다(마스킹이 스코프보다 먼저 돌기 때문). 더 긴 헤더 뒤 `/` 는 나눗셈
  - `.tsx` 의 제네릭 화살표 `<T,>(x) =>` 는 JSX 로 열려 `unterminated_jsx` 로 끝난다(조용한 통과가 아니라 구조 미확인)
  - C# `$"…{x}…"` 보간과 Dart raw 문자열 `r'…'` 은 다루지 않는다

### R23k — 죽은 Python 패턴 · 문법 하드코딩 검사 ✅

- 선택: 보고서안 + mask.py 의 단어 집합도 데이터로
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: `FUNCTION_PATTERNS['py']`, `PY_CLASS`, `PY_EXCEPT` 삭제(py 행 `function_pattern` 없음). `LangDef` 에 `regex_after_words`, `control_heads`, `jsx_after_words`, 상수 `JS_REGEX_AFTER`·`JS_CONTROL_HEADS`·`JS_JSX_AFTER`(js·ts 행)
  - `scripts/lib/structure/native/mask.py`: `_REGEX_AFTER_WORD`(HEAD 부터 있던 것)와 R9 에서 넣은 `_CONTROL_WORDS`·`_JSX_AFTER_WORD` 를 langdef 필드로 교체
  - (`scopes.py:36` `_PY_HEADER` 는 R1 에서 이미 `indent_headers` 로 옮김)
- 추가한 테스트: `tests/structure/test_determinism.py` `case_grammar_lives_in_langs` — 엔진 파일의 `re.compile` 인자와 `frozenset(...)` 문자열에서 정규식 문법(그룹 이름·이스케이프·문자 클래스)을 걷어낸 뒤 두 글자 이상 영단어가 남으면 실패. HEAD 의 `_PY_HEADER` 같은 패턴을 잡는다
- 바꾼 기존 테스트: `test_langs.py` `case_patterns` — py 는 함수 패턴이 없음을 확인
- 테스트 결과: RED(mask.py 단어 집합 14개 단어) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 판정 변화 없음(같은 단어를 옮기기만 함)

### R23a — 확장자 누락 ✅

- 선택: 보고서안 + `.vue`·`.svelte` 는 템플릿 행
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: `.mts`·`.cts`→ts, `.kts`→kotlin, `.pyi`→py, `.cxx`·`.hpp`·`.hh`·`.hxx`→c. `vue`·`svelte` 행 = js 행에서 `tag_boundaries=(('<script', '</script>'),)`, `starts_in_code=False`, JSX 끔(Blade 처럼 템플릿은 텍스트, `<script>` 섬만 코드)
  - `docs/rules.md`: Vue·Svelte 지원 범위
- 추가한 테스트: `tests/structure/test_langs.py` `case_added_extensions`(10개 확장자), `case_template_islands`(vue·svelte 템플릿 아포스트로피 + 스크립트의 문자열·주석), `case_globs_have_languages`(번들 `rules/`·`stacks/` 의 `files:` 글롭이 쓰는 코드 확장자는 모두 언어가 있어야 함. json·jsonc·css·scss·md·yaml·yml 제외)
- 바꾼 기존 테스트: `case_table` 언어 15개
- 테스트 결과: RED 10건(+새 행 없음 오류) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 지문 영향 없음. 지금까지 `unsupported_language`(구조 미확인)이던 파일이 판정되기 시작한다

### R5 — line 앵커가 줄당 첫 매치만 본다 ✅

- 선택: (a) 조건 있는 규칙만 finditer, REJECT 아닌 매치가 하나라도 있으면 후보. 사용자 결정으로 requires 트리거(`detect.py` requires 분기, `fixtures.matcher` 의 requires 경로)도 같이
- 바꾼 파일
  - `scripts/lib/detect.py`: `_line_spans`(줄의 매치를 지연 생성하는 span 함수들). `add` 가 `span` 하나 대신 `spans` 를 받아 모두 REJECT 일 때만 거름(`all` 이라 첫 통과에서 멈춤). 예외 처리는 내부 `judge` 로. line·requires 는 `_line_spans`, file 은 `[Span]`
  - `scripts/lib/rules/fixtures.py` `matcher`: `pattern.finditer` 중 하나라도 `passes_conditions` 면 매치. `migrate.py` 가 같은 matcher 를 써서 이관 판정도 같이 맞춰짐
  - `rules/php/_base/php-no-debug-output.yaml`, `rules/js/_base/js-no-console.yaml`: 보고서 재현을 match 픽스처로
  - `docs/rules.md`: line·requires 앵커는 줄의 모든 매치를 본다
- 추가한 테스트: `tests/structure/test_detect_conditions.py` `case_every_match_on_the_line`(PHP `"dd("; dd($user)`, JS `"console.log("; console.log(x)`, 매치가 전부 걸러지는 줄은 조용함, requires `/* run( */ run();`, 픽스처 실행기의 line·requires 일치) + 규칙 match 픽스처 2건
- 테스트 결과: RED(탐지기 3 + 픽스처 실행기 2 + 규칙 픽스처 2) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 지문·캐시: 스니펫·줄·지문이 줄 단위 그대로라 기각·사이클 영향 없음. 앞에 걸러지는 매치가 있던 줄이 새로 후보가 될 수 있다(사이클에서 new). 조건 없는 규칙은 1.x 경로 그대로. 성능: 매치가 하나인 보통 줄은 판정 1회로 같다

### R6 — 필수 요소가 주석·문자열 안에서도 충족된다 ✅

- 선택: (a)+(b)+BOM. 주석은 기본 제외, `must_not_in` 이 기본값 `[comment]` 를 **대체**(`[comment, string]` 은 문자열도 제외, `[]` 는 원문 매칭 — 라이선스 헤더 주석 같은 규칙용). BOM 1행 지문 전환은 R11 이중 매칭에 넣기로 함(사용자 결정)
- 바꾼 파일
  - `scripts/lib/structure/conditions.py`: `DEFAULT_MUST_NOT_IN`, `requirement_present(rule, text, analyse)` → (found, 미확인 사유). 원문 매치가 없으면 분석하지 않음. 분석 실패·예외는 원문 답 + 사유
  - `scripts/lib/detect.py`: `_has_requirement`(사유를 Unchecked 에 기록). requires(파일 본문)·absent(added_body) 가 사용. DR-18 주석 갱신
  - `scripts/lib/rules/fixtures.py`: `has_requirement` — requires·absent 픽스처도 같은 판정(`migrate.py` 공유)
  - `scripts/lib/rules/schema.py`: `must_not_in` 키(`CONDITIONS`), `must_contain_in_file` 없으면 오류, 값 검증은 `_values` 로 추출해 not_in·in_scope 와 공유. 모듈 docstring 예시
  - `scripts/lib/gitdiff.py`: `read_text` 를 `utf-8-sig` 로, `parse_diff` 가 1행의 U+FEFF 를 벗김
  - `scripts/lib/autofix.py` `plan`: 1행은 BOM 을 뺀 줄로 스니펫과 비교(쓰기는 BOM 유지). BOM 제거로 생기는 1행 자동 수정 회귀를 막는 최소 수정
  - `rules/php/laravel/laravel-controller-needs-validation.yaml`: `must_not_in: [comment, string]`(보고서 재현 f4), match 픽스처 2건
  - `rules/js/next/next-client-hook-needs-directive.yaml`, `rules/php/psr12/php-strict-types-required.yaml`: 주석으로 막아 둔 선언 match 픽스처
  - `docs/rules.md`(예시, 필수 요소 판정·must_not_in·BOM), `skills/rule-add/references/schema.md`
- 추가한 테스트
  - `tests/structure/test_detect_conditions.py` `case_requirement_outside_comments`(조건 없는 규칙에서도 주석 제외, 주석 뒤 진짜 매치, `must_not_in: []`, 문자열 기본 포함·opt-in 제외, absent 주석 선언, 파싱 실패 → 원문 답 + 미확인, 원문 매치 없으면 미기록, 픽스처 실행기 requires·absent·opt-in, 스키마 오류 2건)
  - `tests/rules/scenarios/php/laravel-controller-needs-validation.yaml`(주석에만 FormRequest, 문자열에만 validated()), `php-strict-types-required.yaml`(주석에만 선언)
  - `tests/integration/test_diff_anchor.py` `case_bom_first_line`(read_text, 새 파일 줄, next 규칙 오탐 없음, 1행 diff)
  - `tests/integration/test_autofix.py` `case_bom_first_line`(BOM 파일 1행 자동 수정 + BOM 유지)
- 바꾼 기존 테스트 (보고서가 예고한 DR-18 뒤집기): `case_requires_trigger_only`("주석 안 guard() 도 충족")를 `case_requirement_outside_comments` 로 대체
- 테스트 결과: RED(탐지기 2 + 스키마 미지원, 픽스처 4, 시나리오 3, BOM 4) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(골든 사례에 주석·문자열 안 필수 요소나 BOM 이 없다)
- 지문·캐시
  - requires/absent 후보 지문은 그대로(스니펫이 트리거 줄 또는 고정 문구)
  - **BOM 파일 1행 후보**의 스니펫에서 U+FEFF 가 빠져 지문이 바뀐다(`fingerprint` 는 U+FEFF 를 공백으로 보지 않음). 전환 경로는 R11 이중 매칭에서 넣는다
  - `laravel-controller-needs-validation` 의 `detect` 가 바뀌어 이 규칙의 판정 캐시 정체성이 바뀐다(semantic_review 없는 규칙이라 실제 영향 없음)
  - 지금까지 조용하던 파일(주석·문자열에만 필수 요소)에서 후보가 새로 나온다
- 성능: 조건 없는 requires/absent 규칙도 이제 원문에 필수 요소가 보이는 파일은 구조 분석을 한다(분석은 텍스트별 캐시). 조건 없는 **line** 규칙의 1.x 경로(NR-U2-13)는 그대로
- 한계: 필수 요소 범위를 함수로 좁히는 문제(`update()` 가 같은 파일 `store()` 의 FormRequest 로 통과)는 보고서대로 별개 결정으로 남김

### R11 — 후보 지문이 120자 스니펫에서 계산된다 ✅

- 선택: (a) 전체 줄(file 앵커는 앞뒤 공백을 뺀 전체 매치)을 공백 정규화해 해시, 스니펫은 표시용. 이중 매칭: 기각과 검증 사이클(+ once_per_session 반복 판정)이 3.2 지문도 인정. migrate 경로는 넣지 않음(사용자 결정)
- 바꾼 파일
  - `scripts/lib/candidate.py`: `Candidate(..., code=None, legacy=())` — `code_hash` 는 `code`(없으면 스니펫)에서, `legacy_hashes` 는 3.2 가 해시했을 텍스트에서(같은 값은 뺌). `legacy_keys`, `legacy_snippets(text, lineno)`(자른 스니펫 + 1행은 U+FEFF 변형 — R6 이월). 모듈 docstring
  - `scripts/lib/detect.py`: line·requires 는 `code=text`, file 은 `_trimmed(match)` 로 앞뒤 공백을 뺀 구간에서 줄 범위·변경 줄 겹침·`code` 를 계산하고 스니펫에 끝 `⏎` 없음. 구조 조건 Span 은 원래 매치 그대로(필터 동작 불변). `add` 의 기각 검사가 `code_hash` + `legacy_hashes`
  - `scripts/lib/cycle.py`: `entry` 에 `aliases`(legacy 키, 있을 때만). `classify` 가 별칭으로 still 을 찾고(현재 키로 기록), 별칭이 seen·opened 에 있으면 new 로 보지 않음
  - `scripts/lib/hooks.py` `is_repeat`: `legacy_keys` 도 unresolved 와 비교
  - `docs/architecture.md`: 지문 범위와 3.2 기록 인정
- 추가한 테스트
  - `tests/integration/test_dismiss_and_report.py` `case_whole_line_fingerprint`(보고서 재현: 앞 120자가 같은 두 줄 → 다른 키, 하나 기각 후 꼬리 변경 → 다시 걸림, 3.2 지문 기록 인정), `case_bom_line_one_record`(R6 이월: BOM 파일 1행의 3.2 기록 인정), `case_file_match_trims_whitespace`(앞 공백을 먹은 매치는 `{` 줄에서 보고, 뒤 빈 줄 수가 바뀌어도 키 동일, 끝 ⏎ 없음)
  - `tests/integration/test_hook_cycle.py` `case_key_change_mid_cycle`(세션 상태를 3.2 키로 바꿔 쓴 뒤 재검증 → still 1건, fixed+new 아님)
- 테스트 결과: RED(재현 4, BOM 1, file 3, 사이클 1) → GREEN. `run_all.py --quiet` 전체 통과
- 테스트 기대값 정정(내가 쓴 새 테스트): 3.2 기록 인정 사례에서 처음엔 "기록한 줄만 가려짐"을 기대했으나, 3.2 기록은 앞 120자 지문이라 같은 접두의 다른 줄도 가린다. 이것이 이중 매칭의 본질적 한계라 기대값을 "둘 다 가려짐"으로 고치고 주석으로 고정
- 골든: 변화 없음(골든은 `규칙 파일:줄` 만 담고, 골든 사례의 file 매치는 공백으로 시작·끝나지 않는다)
- 지문·캐시 영향
  - 지문이 바뀌는 후보: 120자 넘는 줄, file 앵커(⏎ 와 앞뒤 공백), BOM 파일 1행. 나머지는 그대로
  - 3.2 기각 기록은 이중 매칭으로 계속 적용된다. **한계**: 그 기록은 3.2 의미 그대로라 앞 120자가 같은 줄(꼬리만 바꾼 줄)도 계속 가린다. 다시 기각하면 새 지문으로 정확해진다. migrate 경로가 없으므로 이중 매칭은 사실상 영구 유지
  - 새로 쓰는 기각은 새 지문. `dismiss.py --key` 는 받은 지문 그대로 기록
  - file 앵커 후보 줄이 앞 공백(`\s*` 로 시작하는 패턴)을 먹던 경우 한 줄 아래(코드가 있는 줄)로 바뀐다. 변경 줄 겹침도 공백 줄을 빼고 판단해서, 매치 뒤 빈 줄만 고친 변경은 더 이상 그 매치를 걸지 않는다
  - 의미 판정 캐시(`review_key`)는 컨텍스트 해시 기준이라 영향 없음
- 릴리스 메모: 다음 릴리스의 `docs/migration-*.md` 에 "지문 범위가 줄 전체로 바뀜, 3.2 기록은 계속 인정"을 적어야 한다(릴리스 절차 항목)

### R18 — 같은 줄 하나를 기각하면 같은 파일의 같은 줄이 모두 가려진다 ✅

- 선택: (c) 중복 수 확인 + `posixpath.normpath`. 확인은 `--line`·`--key` 둘 다(훅이 안내하는 명령이 `--key` 라서). dismissed.yaml 의 모르는 규칙 id 경고는 넣지 않음(CLI 기록은 이미 거부) — 사용자 결정. (b) context 필드는 보고서대로 나중
- 바꾼 파일
  - `scripts/lib/dismiss.py`: `normalize(relpath)`(load 와 CLI 공용), `covered(cands, relpath, digest)`(그 지문이 가리는 후보, legacy 지문 포함)
  - `scripts/dismiss.py`: `--all-identical`, `file_candidates`(파일 전체 후보), `refuse_identical`(2곳 이상이면 종료 2 + 위치 나열), `print_locations` 추출, `record(..., covers=N)` 이 `= 참고: 같은 코드 N곳이 함께 가려집니다`. `--file` 경로 정규화. 모듈 docstring
  - `skills/convention-check/references/dismiss.md`(거부 메시지와 할 일), `docs/output-format.md`(dismiss 절)
- 추가한 테스트: `tests/integration/test_dismiss_and_report.py` `case_identical_lines`(같은 `dd($user);` 두 줄: `--line`·`--key` 거부, 기록 없음, `--all-identical` 기록 + 2곳 안내 + 둘 다 사라짐), `case_path_is_normalised`(손으로 쓴 `./` 경로 적용, CLI `./` 허용·정규형 기록)
- 바꾼 테스트(이 수정의 직접 결과): R11 의 `case_whole_line_fingerprint` 마지막 단계가 3.2 기록을 `dismiss.py --key` 로 만들었는데, 그 옛 지문이 두 줄을 가려 새 확인이 거부했다(의도한 동작). 실제처럼 dismissed.yaml 에 직접 쓰도록 바꿈
- 테스트 결과: RED 10건 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 엔진·지문 불변
- 영향: `dismiss.py --key` 가 이제 파일 하나를 스캔한다(파일을 못 읽거나 후보가 없으면 지금처럼 그대로 기록). 같은 코드가 여러 곳인 기각은 `--all-identical` 이 필요하다. 기각 뒤에 새로 추가되는 같은 줄은 여전히 가려진다((b) 의 몫)

### R19 — 삭제만 한 변경이 file·paired 앵커에 보이지 않는다 ✅

- 선택: (a)+(b). 린터에는 추가된 줄이 있는 파일만 넘김, paired 는 검사 대상(scannable) 파일만 봄 — 사용자 결정
- 바꾼 파일
  - `scripts/lib/gitdiff.py`: `parse_diff(text, seams=None)` — 순수 삭제 hunk(`+n,0`)마다 이음매 n(n 행과 n+1 행 사이)을 모으고 그 파일을 줄 없이 결과에 넣음. `diff_lines`·`added_lines` 가 `seams` 를 넘김. 수집기를 안 주면 예전과 같음(삭제만 한 파일 없음)
  - `scripts/lib/scope.py`: `ChangeScope(..., seams=None)`, `seams_of(rel)`, `lint_paths()`(추가된 줄이 있는 파일만). from_touched·working_tree·staged·git_range 가 이음매를 모음(git 호출 수 불변)
  - `scripts/lib/detect.py` file 분기: 겹침 = 추가된 줄이 창 안에 있거나, 이음매가 창 **안쪽**(first ≤ n < last)에 있음. `_window`: block_empty 규칙은 판정 블록의 줄 범위로 넓힘(분석 실패·예외면 매치 줄). 모듈 docstring 표
  - `scripts/lib/structure/conditions.py`: `judged_block(structure, span)` 추출(`_block_empty` 와 detect 가 같은 블록을 봄)
  - `scripts/lib/pipeline.py`: 린터에 `scope.lint_paths()`
  - `docs/rules.md`(앵커 표, block_empty 창)
- 추가한 테스트
  - `tests/rules/scenarios/php/php-no-empty-catch.yaml`: 레거시 catch 본문을 지움(f14 A), 본문을 빈 줄로(f14 B), 레거시 빈 catch 바로 아래 줄만 지움(조용함 — 이음매가 블록 밖)
  - `tests/rules/scenarios/php/laravel-route-needs-test.yaml`: 테스트 파일에서 줄만 지워도 짝 변경(f9 A)
  - `tests/integration/test_diff_anchor.py` `case_deletion_only`(줄 없는 항목 + 이음매, 수집기 없는 옛 호출 불변, scope.paths·seams_of, lint_paths 제외)
  - `tests/integration/test_hook_cycle.py` `case_deletion_only_turn`(삭제만 한 턴에서 비워진 레거시 catch 가 warn 으로 보고됨)
- 바꾼 기존 테스트: 가짜 스코프 4곳(`test_detect_conditions`, `test_determinism`, `test_properties`, `perf/fp_reduction`)에 `seams_of` 추가(인터페이스 확장)
- 테스트 결과: RED(시나리오 3, gitdiff API, 턴 1) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 영향
  - 삭제만 한 턴도 이제 Stop 훅이 검사한다(전에는 범위가 비어 아무것도 안 함). 후보는 file·paired 앵커에서만 나온다
  - paired 의 when_changed 쪽도 삭제만 한 파일을 본다: 라우트 줄을 지우기만 해도 laravel-route-needs-test(info)가 테스트 변경을 요구한다
  - block_empty 규칙은 레거시 블록 안의 아무 변경(본문 수정 포함)이든 그 블록을 이번 변경의 책임으로 본다. 비어 있지 않으면 조건이 REJECT 하므로 실제 후보는 "비게 만든 변경"뿐
  - 지문 영향 없음
- 한계: 이음매는 매치 창 **안쪽**만 본다. 헤더만 잡는 일반 file 패턴(block_empty 아님) 바로 다음 줄을 지운 변경은 여전히 보이지 않는다

### R23h — paired 앵커가 applies_to.files 를 무시한다 ✅

- 선택: 보고서안 — 그 조합을 `RuleError` 로
- 바꾼 파일: `scripts/lib/rules/schema.py`(when_changed 분기), `skills/rule-add/references/schema.md`(오류 표에 이 오류와 R6 의 must_not_in 오류)
- 추가한 테스트: `tests/unit/test_config_and_rules.py` `case_schema` — paired + files 는 오류, paired + exclude 는 허용
- 바꾼 기존 테스트(이 수정의 직접 결과): `tests/unit/test_migrate_judge.py` 헬퍼가 모든 규칙에 `files` 를 넣어서 paired 사례가 막힌 조합이 됨. `glob=None` 이면 files 줄을 빼고 paired 사례가 그것을 씀(그 사례가 보는 것은 migrate 의 anchor_rejects)
- 테스트 결과: RED 1 → GREEN
- 골든: 변화 없음. 번들 paired 규칙에는 files 가 없다. 이 조합을 쓴 로컬 규칙은 이제 로드 오류가 된다

### R9 보완 — JSX 텍스트 경계 (R23h 전체 실행 중 발견, 사용자 결정으로 지금 고침)

- 발견: R23h 의 `run_all.py` 에서 `tests/structure/test_properties.py` P-15(마스킹 멱등성)가 실패. 반례 JS `<p>It's</p>`. 무작위 속성 테스트라 R9 때는 나오지 않았다
- 원인: R9 의 JSX 텍스트 구간이 (1) 식의 `{`·`}` 를 포함해(`<p>a{x}b</p>` → 'a{', '}b') 텍스트를 지우면 `x` 가 텍스트가 됐고, (2) 태그 사이 공백만 있는 텍스트도 문자열로 기록했다
- 바꾼 파일: `scripts/lib/structure/native/mask.py` — `_step_jsx` 의 `{` 앞에서 텍스트를 끊음, 코드 프레임이 `}` 로 닫힐 때 부모가 jsx_text 면 `}` 뒤에서 텍스트 재개(템플릿 문자열은 그대로 `}` 를 소유), `_text` 가 공백뿐인 구간은 기록하지 않음
- 추가한 테스트: `tests/structure/test_mask.py` `case_r9_jsx_text_bounds`(괄호는 식의 것, 태그 사이 공백은 문자열 아님, 두 반례의 멱등성)
- 테스트 결과: RED 4 → GREEN. `run_all.py --quiet` 전체 통과, 예시 3000개 속성 실행(스크래치패드 `prop2.py`)에서도 반례 없음
- 골든: 변화 없음. 지문 영향 없음(필터). `{`·`}` 나 공백 자체를 찾는 `not_in: string` 규칙의 판정만 달라진다

### R22 — 글롭 번역기가 일부 문법을 조용히 매치 실패시킨다 ✅

- 선택: (a) 대안 재귀 번역 + `[...]` + 규칙 글롭의 앞·뒤 `/` 는 RuleError. 대소문자 구분 유지·문서화, 설정 글롭은 번역기에서 `dir/` = `dir/**`·앞 `/` = 레포 루트 — 사용자 결정
- 바꾼 파일
  - `scripts/lib/rules/select.py`: `glob_re` → `_translate`(재귀), `_close`(중첩 괄호), `_alternatives`(최상위 쉼표만), `_class_end`·`_char_class`(`[!x]`/`[^x]`, `[]]`, 범위, `/` 는 절대 매치 안 함, 빈 클래스 처리). 닫히지 않은 `{`·`[` 는 문자 그대로. `./`·앞 `/` 제거, 뒤 `/` 는 `/**`
  - `scripts/lib/rules/schema.py`: `_globs(value, field)` — applies_to.files·exclude, when_changed·require_changed 의 앞·뒤 `/` 거부
  - `skills/rule-add/references/schema.md`(글롭 문법), `docs/configuration.md`(exclude 의 관대한 읽기)
- 추가한 테스트: `tests/unit/test_config_and_rules.py` `case_globs` — 보고서 재현 4건(대안 안 글롭, `[Tt]ests`, `vendor/`, `.PHP` 는 구분 유지) + 중첩 대안, `[!_]`, 범위, 닫히지 않은 괄호, 앞 `/`, `./`, 기존 형태 회귀, 규칙 필드 4종의 슬래시 거부
- 테스트 결과: RED 11 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(번들 글롭은 리터럴 대안만 쓴다)
- 영향: 지금까지 아무것도 매치하지 않던 팀 글롭이 매치하기 시작한다(의도). `/` 로 시작·끝나는 로컬 규칙 글롭은 로드 오류가 된다. 설정 exclude 의 `legacy/` 는 이제 실제로 제외한다. 지문 영향 없음

### R23g — 버전 제약이 느슨하다 ✅

- 선택: 엄격 검증 + 공백으로 나눈 절은 AND(`>=10 <12`) — 사용자 결정. `^`·`~`·`||`·숫자 아닌 값은 RuleError
- 바꾼 파일
  - `scripts/lib/stack.py`: `parse_constraint`(절 정규식 `OP? 숫자(.숫자){0,2}`, 연산자 뒤 공백 허용), `version_ok` 가 모든 절을 확인. 못 읽는 제약은 런타임에서는 억제하지 않음(스키마가 거부하므로 로컬 경로 밖에서만)
  - `scripts/lib/rules/schema.py`: `_version` — 문자열·dict 값 모두 검증
  - `skills/rule-add/references/schema.md`(version 주석)
- 추가한 테스트: `tests/unit/test_config_and_rules.py` `case_version_constraints`(범위 상한·하한, 연산자 뒤 공백, 맨 숫자, dict, 버전 모름은 억제 안 함, 범위 로드, `^10`·`~10`·`||`·`latest`·dict 안 `^10` 거부)
- 테스트 결과: RED 6 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(번들 규칙·스택에 version 제약 없음)
- 영향: `^`·`~` 를 쓴 로컬 규칙은 로드 오류가 된다(전에는 조용히 꺼져 있었음). `>=10 <12` 는 이제 상한까지 맞게 동작

### R13 — diff 결과가 사용자 git 설정에 따라 달라진다 ✅

- 선택: (b) `--diff-algorithm=histogram` 고정. 구버전 git 대응은 하지 않음(이 플래그는 오래된 git 도 지원). `--no-textconv`·`--ignore-cr-at-eol`·`--indent-heuristic` 은 (a) 의 항목이라 넣지 않음 — 사용자 결정
- 바꾼 파일: `scripts/lib/gitdiff.py` `DIFF_FLAGS`(+ 주석), `docs/rules.md`(추가된 줄의 기준)
- 추가한 테스트: `tests/integration/test_diff_anchor.py` `case_diff_algorithm_is_fixed` — 무작위 탐색으로 찾은 반례(myers 6·7·8·10·11·12행 / histogram 6·7·9·10·11·12행)에서 `diff.algorithm` 을 myers·patience·histogram 으로 바꿔도 histogram 결과
- 테스트 결과: RED(myers 설정에서 다른 줄) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(골든 사례들은 myers 와 histogram 이 같은 줄을 낸다). 보고서는 (b) 가 골든을 바꿀 수 있다고 했으나 현재 코퍼스에서는 바뀌지 않았다
- 영향: 기본 설정(myers) 사용자도 괄호·반복 줄이 많은 변경에서 추가된 줄로 보는 범위가 달라질 수 있다(보통 더 코드 단위에 가깝게). 남은 문제: CRLF 로 다시 쓴 파일(COL R6), textconv 설정, 재들여쓰기(COL R15)는 여전히 추가된 줄로 잡힌다
- 지문 영향 없음

### R20 — 큰 파일은 조용히 건너뛰고 바이너리는 확장자로만 거른다 ✅

- 선택: (a) 앞 8KB(8000자) NUL 휴리스틱. too_large 는 "구조 미확인"과 **별도 알림** "큰 파일 미검사" — 사용자 결정. read_lines 는 split 한 번
- 바꾼 파일
  - `scripts/lib/gitdiff.py`: `BINARY_PROBE`, `read_text` 가 NUL 이 있으면 ''(전체를 읽는 경로에서만, 추가 읽기 없음), `too_large(root, rel)`, `read_lines` O(n)(`split('\n')` + 마지막 빈 요소 제거, splitlines 미사용), `added_lines(..., oversized=None)` 수집기
  - `scripts/lib/scope.py`: `ChangeScope.too_large`(added_lines 수집분 + 필터에서 빠진 큰 파일 + files/everything 의 `_oversized`)
  - `scripts/lib/pipeline.py`: `Result.too_large`
  - `scripts/lib/hooks.py`: `too_large_note`, `_with_unchecked_note` 가 두 노트를 ` · ` 로 붙임, `_run_scan` 은 범위가 비어도 큰 파일이 있으면 파이프라인을 돌림(알림을 위해)
  - `scripts/scan.py`: JSON `too_large`, 텍스트 `■ 검사 경고` 에 알림. `scripts/lib/report.py` `render_text` 가 경고 목록을 받음
  - `docs/output-format.md`, `docs/configuration.md`
- 추가한 테스트: `tests/integration/test_diff_anchor.py` `case_unreadable_files`(NUL 파일은 바이너리, 둘 다 범위 밖, 큰 파일은 working_tree·from_touched 의 too_large, scan JSON·텍스트, read_lines 경계 4건(\x0c 는 줄바꿈 아님), 10만 줄 1초 미만), `tests/integration/test_hook_cycle.py` `case_too_large_is_said`
- 바꾼 기존 테스트: `test_detect_conditions.py` 의 `_FakeScan` 결과에 `too_large=()`(Result 속성 확장)
- 테스트 결과: RED → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 지문 영향 없음
- 영향: 확장자와 무관하게 NUL 이 든 파일(sqlite 등)은 검사하지 않는다. 400KB 넘는 파일만 바뀐 턴도 이제 알림을 낸다. SKIP_EXT 는 그대로(생성 텍스트 정책)

### R14 — 이동이 전체 추가가 되고, 세션 중 커밋·빈 레포에서 새 파일 판정이 꺼진다 ✅

- 선택: 이동 (a) `-M70%` + untracked blob 짝짓기 / 새 파일은 ref 마다 A / 빈 레포는 빈 트리 base — 모두 권장안
- 바꾼 파일
  - `scripts/lib/gitdiff.py`: `RENAMES='-M70%'` 로 `--no-renames` 대체(DIFF_FLAGS). `name_status(root, args, strict)` → (새 쪽 경로, A, rename 원본, D). `moved_untracked`(HEAD ls-tree blob id 와 내용 `blob N\0` 해시 비교, SHA-256 레포는 id 길이로 판별). `diff_lines(..., companions=)` — rename 원본을 모든 청크 pathspec 에 붙임(pathspec 이 양쪽을 제한하므로 원본이 없으면 rename 을 못 찾는다). `added_lines(..., new=, with_untracked=)` — ref 마다 name_status 한 번, 새 파일 = (untracked − 이동) ∪ 각 ref 의 A(HEAD 없으면 staged_added), 이동한 untracked 는 읽지 않음. `session_base`(HEAD, 없으면 `git hash-object -t tree --stdin` 의 빈 트리)
  - `scripts/lib/scope.py`: from_touched·working_tree 가 `new` 수집기 사용(untracked 호출 1회로 통합, `new_files` 미사용), staged·git_range 는 `_status` 하나로 경로·새 파일·rename 원본
  - `scripts/lib/hooks.py`: Pre/Post 가 `session_base` 로 base 기록
  - `docs/rules.md`(이동·새 파일 정의)
- 추가한 테스트: `tests/integration/test_diff_anchor.py` `case_moves`(git mv: from_touched·working_tree·staged 모두 추가 줄 없음·새 파일 아님, 옮기고 고친 줄만, 그냥 mv 도 같음), `case_committed_new_file`(세션 중 커밋한 새 파일: 훅과 --range 가 같은 답), `case_empty_repo_base`; `tests/integration/test_hook_cycle.py` `case_empty_repo_commit`(COL R14: 빈 레포에서 커밋 뒤 Stop 이 차단)
- 테스트 결과: RED 11 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음(골든 사례에 rename 없음)
- 성능: Stop 훅 git 호출이 하나 줄었다(untracked 2회 + staged_added → untracked 1회 + name_status). base ref 마다 name_status 1회, 지운 추적 파일과 untracked 후보가 둘 다 있을 때만 ls-tree 1회
- 한계: 옮기면서 고친 untracked 파일(blob 이 다름), autocrlf 로 내용이 달라진 이동은 새 파일로 읽힌다. 유사도 70% 미만의 git mv 는 삭제+추가

### R15 — --staged·--range 가 줄 번호와 본문을 다른 곳에서 가져온다 ✅

- 선택: (a) blob 에서 본문
- 바꾼 파일
  - `scripts/lib/gitdiff.py`: `read_blobs(root, prefix, relpaths)` — `git cat-file --batch` 한 프로세스, 바이트 스트림 파싱, missing·비 blob 건너뜀, 크기·NUL·SKIP_EXT 판정을 blob 기준으로(R20 과 같은 규칙)
  - `scripts/lib/scope.py`: `ChangeScope(..., blob=None)` — `':'`(staged)·`'REV:'`(range 의 오른쪽)이면 생성 시 본문을 한 번에 읽어 `_text` 를 채우고 그 결과로 scannable·too_large 판정. `_right_side(spec)`(A..B·A...B → B, A.. → HEAD, 맨 A → 워킹 트리). 변경 집합 밖 파일(리뷰어용 관련 파일)은 워킹 트리에서
  - `skills/convention-check/references/cli.md`
- 추가한 테스트: `tests/integration/test_diff_anchor.py` `case_gates_read_what_they_gate`(DET f6: index 에 빈 catch 두 개, 워킹 트리에 4줄 추가 → --staged 가 4·6행, --range 도 같음, 큰 파일 판정은 blob 크기)
- 테스트 결과: RED(8·10행) → GREEN. 중간에 테스트 버그 하나(`commit()` 이 `add -A` 해서 워킹 트리 내용이 커밋됨)를 고침. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 영향: Stop 훅·워킹 트리 scan 은 그대로. --staged/--range 는 git 호출 1회 추가. `--staged --fix --write` 는 여전히 워킹 트리 파일을 고치며, 스니펫이 다르면 건너뛴다(기존 안전장치)
- 한계: blob 은 크기와 무관하게 전부 읽는다(스트림 동기화를 위해, ponytail 주석). 린터는 여전히 워킹 트리 파일을 검사한다(추가 발견에 기록)

### R23b — 경로 견고성 ✅

- 선택: 보고서안 + git 경로 unquote 함수(-z 대신), 어느 파일에도 속하지 않는 touched 는 "검사되지 않음"으로 표시 — 사용자 결정
- 바꾼 파일
  - `scripts/lib/paths.py`: `repo_relative(path, root)` — 그대로, 안 되면 realpath 로 다시. `..` 자체만 밖(`..foo.php` 는 파일)
  - `scripts/lib/hooks.py`: touched 기록이 `repo_relative` 사용, `unknown_note`, 목록 접기 `_listed` 를 too_large 와 공유, 범위가 비어도 unknown 이 있으면 알림까지
  - `scripts/lib/gitdiff.py`: `unquote`(C 따옴표·이스케이프·8진 바이트), `git_lines`·`untracked`·`ignored`·`name_status`·`_header_path` 에 적용. `read_text` 는 `newline=''` + CRLF→LF 만(홀로 있는 CR 은 문자), `read_blobs` 도 같게. `added_lines(..., unknown=)` — 줄이 안 나온 diffable touched 중 디스크에 있는 것만 `ls-files` 1회로 확인
  - `scripts/lib/scope.py`: `ChangeScope.unknown`(from_touched), `files()` 의 `..` 판정
  - `scripts/lib/pipeline.py`: `Result.unknown`
  - `docs/output-format.md`
- 추가한 테스트: `tests/integration/test_diff_anchor.py` `case_path_robustness`(따옴표 경로의 추가 줄, untracked 따옴표 경로, `..foo.php`, `..`, symlink 경유 경로, lone CR·CRLF, 중첩 레포 파일이 unknown), `tests/integration/test_hook_cycle.py` `case_unknown_file_is_said`
- 바꾼 기존 테스트: `test_detect_conditions.py` `_FakeScan` 결과에 `unknown=()`
- 테스트 결과: RED → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 지문 영향 없음(CRLF 는 전처럼 LF 로 읽힘)
- 성능: Stop 훅은 줄이 안 나온 touched(되돌린 파일 등)가 있을 때만 git 1회 추가
- 한계: 줄바꿈이 든 경로는 여전히 다루지 않는다(cat-file 요청에서도 제외)

### R12 — 사람·다른 사람의 줄과 다른 터미널의 커밋이 에이전트 책임으로 잡힌다 ✅

- 선택: stash 의 (a) 구현을 손으로 옮김 — 사용자 결정. stash 는 그대로 둠
- 옮긴 방식: 이 브랜치에서 바뀌지 않은 `scripts/lib/state.py`, `scripts/collect.py`, `hooks/hooks.json`, `docs/architecture.md` 는 `git diff stash@{0}^1 stash@{0}` 를 `git apply`(stash 는 읽기만). 바뀐 파일은 손으로 합침
- 바꾼 파일
  - `hooks/hooks.json`: PreToolUse 매처 `Write|Edit|MultiEdit|NotebookEdit|Bash`
  - `scripts/collect.py`(docstring), `scripts/lib/state.py`: `foreign-<session>.jsonl`(baseline·arrived, 덧붙이기만), `read_foreign`, Bash 스냅샷에 head·started, GC 접두
  - `scripts/lib/gitdiff.py`: `arrived_lines`(old..new 중 호출 시작 전 커밋, 머지 제외)
  - `scripts/lib/scope.py`: `line_key`·`line_counts`·`without_lines`(개수만큼 빼기), `from_touched(..., foreign)` — R19 의 이음매만 있는 파일은 유지, 남의 줄이 있던 파일은 새 파일 아님
  - `scripts/lib/hooks.py`: `on_pre_tool_use` 가 모든 감시 도구에서 기준선(`_record_baseline`), Bash 는 **세션 base** 로 `changed_paths`(Pre/Post 기준 불일치 수정), `_claim`, `_record_arrived`, `_repo_paths`(R23b 의 `repo_relative` 사용), `_run_scan` 이 foreign 전달. `session_base`(R14) 유지
  - `docs/architecture.md`(검사 범위의 한계, foreign 파일)
- 추가한 테스트: stash 의 `tests/integration/test_hook_cycle.py` 5건(사람 줄, 같은 줄 두 번, Bash 의 사람 줄, pull 한 동료 커밋, Bash 안 에이전트 커밋)과 `tests/helpers` 의 `Session.pre/edit`, `tests/plugin/test_manifest.py` Pre 매처 검사 + 보고서 재현 R2 `case_other_terminal_commit`(stash 에 없던 테스트)
- 테스트 결과: RED 7(훅 6 + manifest 1) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 후보 키 불변
- 한계: 사람 줄과 글자까지 같은 줄을 에이전트가 쓰면 개수만큼은 놓친다(안전한 쪽). 세션 전 사람이 지운 자리(R19 이음매)는 기준선이 없어 에이전트 것으로 본다. Pre 가 첫 접촉 파일마다 added_lines 를 한 번 돈다(PreToolUse 10초 예산 안)

### R23c·d·e — base mtime · Pre 스냅샷 누락 · EDIT_TOOLS ✅

- 선택: c 이미 있을 때 `os.utime` / d 미수집 플래그 + Stop 알림 / e 도구 목록 설정 — 모두 권장안
- 바꾼 파일
  - `scripts/lib/state.py`: `record_base` 가 이미 있으면 base·foreign 파일 mtime 갱신(c). `bashmiss-<session>.txt` 덧붙이기·`take_bash_misses`(읽고 지움), GC 접두(d)
  - `scripts/lib/hooks.py`: `MCP_MATCHER`, `_watched_root`(내장 도구는 바로, `mcp__` 는 config `collect.edit_tools` 에 있을 때만 — 설정은 MCP 호출에서만 읽음)(e). Bash Post 가 스냅샷 없으면 미수집 기록(d). `_with_unchecked_note` 가 스캔이 없어도 "Bash 변경 미수집 N회" 를 붙임
  - `hooks/hooks.json`: Pre/Post 매처에 `mcp__.*`, `scripts/lib/config.py`·`config.yaml`: `collect.edit_tools`
  - `docs/configuration.md`, `docs/architecture.md`
- 추가한 테스트: `tests/integration/test_hook_cycle.py` `case_base_outlives_a_week`, `case_bash_without_pre_is_said`(한 번만 알림), `case_configured_edit_tool`(설정한 MCP 도구는 차단, 다른 MCP 도구는 무시). `tests/plugin/test_manifest.py` 매처 = WATCHED_TOOLS + `mcp__.*`
- 테스트 결과: RED 3(+manifest) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 영향·비용: 모든 MCP 도구 호출이 collect.py 를 한 번 띄운다(설정 읽기 후 대부분 즉시 종료). 내장 도구 경로 비용은 그대로

### R4 — 연속 차단 상한이 요청을 넘어 누적된다 ✅

- 선택: (a) 요청 경계에서 초기화(확정 의도: 요청 안의 루프 가드)
- 바꾼 파일: `scripts/lib/hooks.py` `_stop` — continuation 이 아닌 Stop, 또는 열린 사이클이 다른 요청 것이면 `consecutive_blocks=0`. `config.yaml`, `docs/configuration.md`, `docs/architecture.md`
- 추가한 테스트: `tests/integration/test_hook_cycle.py` `case_cap_does_not_cross_requests`(CYC s5: p1 무시, p2 같은 error, p3 새 파일 새 규칙 error 가 차단되고 streak 1)
- 바꾼 기존 테스트
  - `test_hook_cycle.py` `case_consecutive_cap`(보고서 예고): 서로 다른 prompt 누적 → 한 요청 안 continuation 3회(max_verify_attempts 5)로 `[T,T,T,F]`. 상한에 걸린 재검증 경로의 요약은 "재검증 종료 … 남음 1"이라 기대 문구를 '상한' → '남음 1' 로
  - `test_cli_contract.py` `case_cap_holds`(**보고서 미예고**, 사용자 확인 후): 같은 이유로 한 요청 안 continuation 시나리오로 바꿈(cap 2, `['block','block',None,None,None]` 유지)
- 테스트 결과: RED(p3 미차단, streak 3) → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 영향: 매 요청이 상한을 새로 가진다. 요청을 넘어 반복되는 지적은 "지난 턴에도 지적" 표시로 구분

### R3 (+C6·C9) — 표시 예산 밖 error 가 남았는데 통과로 닫고 이후 침묵한다 ✅

- 선택: (b) 차단은 그대로, 통과라고 속이지 않기 + C6. C9(once_per_session 으로 빠진 error 만 남은 턴)는 그대로 침묵 — 사용자 결정
- 바꾼 파일
  - `scripts/lib/hooks.py`: `_hidden(outcome, current)`(보여 주지 않은 채 남은 blocking 후보). `_close(..., current)` — current 에 후보가 하나라도 있는 규칙은 `fired_rules` 로 정리하지 않음, `unresolved` = 남은 것 ∪ 미표시. `_verify` 가 current 를 한 번만 계산, VERIFY_CAP 에 걸린 규칙의 new 는 버림(C6, 미표시로 집계), 닫는 메시지에 `미표시 N`(남은 것이 없으면 `⚠ 재검증 종료 … 다음 요청에서 다시 알림`). 버려진 사이클 경로도 current 전달. `_open` 이 규칙별 숨긴 위치 수와 숨긴 규칙 수를 계산
  - `scripts/lib/report.py`: `hook_reason(..., more, hidden_rules)`, `_finding(..., more)` — `… N곳 더`, `… N개 규칙 더`
  - `docs/output-format.md`, `docs/architecture.md`
- 추가한 테스트: `tests/integration/test_hook_cycle.py` `case_hidden_finding_is_not_a_pass`(CYC s1c: `… 1곳 더`, 보여 준 것만 고치면 통과 아님·미표시 1, 규칙이 fired_rules 에 안 들어감, 다음 요청에 "지난 턴에도"로 다시 차단), `case_hidden_rules_are_counted`(CYC s1: `… 1개 규칙 더`), `case_verify_cap_is_not_new`(C6 / CYC s8: 55건 중 3건 고치면 new 0)
- 테스트 결과: RED 6 → GREEN. `run_all.py --quiet` 전체 통과(출력 형식 테스트는 갱신할 필요 없었다)
- 골든: 변화 없음. 지문 불변
- 영향: 기존 의도(보여 준 것만 고치면 그 턴은 통과, `case_over_budget_is_not_new`)는 유지. 요약 문구에 `미표시 N` 이 생기고 `fired_rules` 에 남은 후보가 있는 규칙이 빠진다

### R17 — 린터가 돌지 않으면 열린 lint 키가 fixed 가 되어 통과로 닫힌다 ✅

- 선택: (a) 미완료 키는 still(미확인) + 린터 diff 파서 in_hunk·삽입 앵커링
- 바꾼 파일
  - `scripts/lib/lint.py`: `run(..., unfinished=)` — 타임아웃·예산 소진·실행 실패한 항목의 `entry_key` 수집(`_unfinished`). `_parse_diff` — hunk 밖에서만 `---`/`+++` 를 헤더로, 지운 줄 없이 이어진 추가 줄은 바로 위 줄에 앵커
  - `scripts/lib/pipeline.py`: `Result.lint_unfinished`
  - `scripts/lib/cycle.py`: `classify(..., unconfirmed)` — 미완료 린터의 opened lint 키는 `still(unconfirmed=True)`. `Outcome.blocking()` 은 unconfirmed 를 빼고(다시 차단해도 또 타임아웃일 뿐), `unconfirmed()` 추가
  - `scripts/lib/hooks.py` `_classify`·`_verify`: 미완료 키 전달, 닫는 메시지 `⚠ 재검증 종료 … 린터 미확인 N`
  - `docs/output-format.md`
- 추가한 테스트: `tests/integration/test_lint_anchor.py` — `case_parsers` 에 `--- ` 로 시작하는 삭제 줄·순수 삽입 hunk, `case_lint_budget` 에 unfinished 수집, `case_unfinished_linter_is_not_fixed`(실제 Stop: 첫 턴 린터 실패로 차단 → 재검증에서 린터 타임아웃 → 통과 아님·`린터 미확인 1`·재차단 없음)
- 테스트 결과: RED → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 키 영향 없음
- 영향: 포맷터 diff 의 순수 삽입(빈 줄 추가 등)이 이제 위치로 잡혀 변경 줄에 걸리면 차단된다

### R23f — 재포맷·이동한 위반이 "고쳐짐 1 · 새로 생김 1"로 기록된다 ✅

- 선택: 짝지어 still 로 재분류. 단 보고서 기준(같은 규칙·같은 파일)이 기존 `case_new_violation_from_fix`(dd(1)→var_dump(1) 은 fixed+new)와 충돌해서, 사용자 결정으로 **기준을 좁힘**: 같은 파일은 공백을 모두 뺀 스니펫이 같을 때(재포맷), 다른 파일은 같은 지문일 때(이동)
- 바꾼 파일: `scripts/lib/cycle.py` `_pair_moves`·`_squeezed`(classify 끝에서 남은 fixed 와 new 를 1:1 로 묶어 still, `was` 에 옛 키), 모듈 docstring
- 추가한 테스트: `tests/integration/test_hook_cycle.py` `case_reformat_and_move_are_still`(CYC s4: 제자리 재포맷 → still 이고 계속 차단, 다른 파일로 이동 → still)
- 테스트 결과: RED 2 → (보고서 기준) 기존 테스트 2건 실패 → 기준을 좁혀 GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 차단 판단 불변(still 도 차단). 바뀌는 것은 verify 로그와 요약 숫자
- 한계: 줄바꿈까지 바뀐 재포맷(한 줄 → 여러 줄)은 짝짓지 못한다

### R23i — 경고 우선순위를 문구 부분 일치로 정한다 ✅

- 선택: 노트에 종류 필드. `(level, text)` 를 쓰는 곳이 많아 튜플은 그대로 두고, 텍스트를 `kind` 속성을 가진 str 하위 클래스로
- 바꾼 파일: `scripts/lib/lint.py`(`UNCHECKED`, `Note`, `_unchecked` 가 Note 로), `scripts/lib/hooks.py` `_scan_warnings`(kind 로 정렬, lint import)
- 추가한 테스트: `tests/integration/test_lint_anchor.py` `case_lint_budget` — 노트의 kind, 문구에 '검사되지 않았습니다'가 없어도 kind 로 맨 앞
- 테스트 결과: RED → GREEN. `run_all.py --quiet` 전체 통과. 골든 변화 없음

### R16 — auto-fix 가 UTF-8 이 아닌 파일에서 Stop 을 죽이고 혼합 줄바꿈을 CRLF 로 바꾼다 ✅

- 선택: (a) 바이트로 읽고 줄끝 유지. 보고서의 `splitlines(keepends=True)` 는 홀로 있는 `\r` 에서도 나눠 git 줄 번호(R23b)와 어긋나므로 `\n` 기준 분할로 구현
- 바꾼 파일: `scripts/lib/autofix.py` — `_read_lines` 가 `(줄, 줄끝)` 또는 디코딩 실패 시 None, `plan`·`apply` 가 None 이면 그 파일을 건너뜀(절대 쓰지 않음), 쓰기는 바이트로 줄마다 원래 줄끝. `docs/rules.md`
- 추가한 테스트: `tests/integration/test_autofix.py` `case_bytes_are_respected`(CYC s7: cp949 파일이 있어도 Stop 에 내부 오류 없음·파일 바이트 불변, 앞 3줄만 CRLF 인 파일을 고쳐도 고친 부분 외 바이트 동일). 실제 Stop 경로는 `Session` 으로 탄다
- 테스트 결과: RED 2 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 지문 영향 없음

### R7 — 한 함수의 후보들이 한 질문으로 묶이는데 리뷰어는 첫 후보만 본다 ✅

- 선택: (a) 배치 항목에 `lines` 목록(확정 의도: 함수 단위 유지, 배치에 함수 안 후보 전부)
- 바꾼 파일
  - `scripts/lib/semantic.py`: `BATCH_VERSION = 2`, `READABLE_VERSIONS = (1, 2)`(업그레이드 전 v1 배치도 읽음), `build_batch` 가 review_key 별로 모아 항목에 `lines`(줄 순)
  - `scripts/review.py` `show`: 줄이 여럿이면 `줄: 스니펫` 으로 모두, `## 다음` 에 "하나라도 위반이면 VIOLATION, reason 에 그 줄"
  - `scripts/lib/hooks.py` `_request_review`: `by_key` 를 setdefault 로(첫 후보 = 배치 항목)
  - `agents/convention-reviewer.md`(판정 규칙 한 줄), `docs/semantic-review.md`
- 추가한 테스트: `tests/integration/test_semantic_review.py` `case_one_question_shows_every_candidate`(SEM r4: 두 루프 → 항목 1개·lines 2개, show 에 둘 다, 지시문, 사이클이 첫 후보를 추적, v1 배치 show 성공)
- 테스트 결과: RED 2 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 판정 캐시 키·호출 수 불변

### R8 — 관련 파일 지문이 보여 준 앞 60줄만 덮는다 ✅

- 선택: (a) 관련 파일 전체 지문 + 부수 항목(related_files 블록을 changed_hunks 앞으로, imports 는 정렬한 줄 텍스트 집합)
- 바꾼 파일: `scripts/lib/context.py` — `Pack.add(..., depends=)` 와 내부 `_depends`, `related_hash` 가 `_depends` 로(관련 파일은 `_fingerprint(파일 전체)`, imports 는 번호 없는 정렬 텍스트), 블록 순서 변경. `docs/semantic-review.md`
- 추가한 테스트: `tests/semantic/test_review_key.py` `case_related_context_is_whole`(SEM r2: 60줄 밖 `$with` 를 줄 수 그대로 비워도 키가 바뀜, r2 b1: 같은 파일 다른 곳의 추가 줄이 관련 파일 예산을 먹지 않음, r3: 맨 위 주석으로 import 줄 번호만 밀리면 키 그대로). FakeScope 에 추가 줄 주입
- 테스트 설계 정정(내가 쓴 새 테스트): 처음엔 `$with` 줄을 **삭제**했는데 잘림 표시의 남은 줄 수가 바뀌어 우연히 통과했다 → 보고서처럼 줄 수가 같은 수정으로. b1 은 규칙 컨텍스트에 `changed_hunks` 를 넣어야 재현됨
- 테스트 결과: RED 3 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음
- 지문·캐시: 후보 지문 불변. **의미 판정 캐시는 전환 때 related 섹션이 있는 모든 판정이 한 번 만료**(review_hash 변경 → 재판정 1회). 이후 Model 을 고치면 그 Model 을 쓰는 곳이 재판정된다(보고서 예고)
- 한계: 리뷰어가 팩 밖에서 따로 Read 한 파일은 여전히 해시에 없다(보고서가 다음 단계로 남김)

### R21 — 팩의 import 탐지와 Python 블록 경계가 휴리스틱에 의존한다 ✅

- 선택: import (a) `LangDef.import_pattern` + 이어 읽기 + 주석·문자열 제외 / Python: ast 경로에 데코레이터 + 들여쓰기 폴백 보강 / `PACK_SCOPES` → `LangDef.pack_scopes`. 콜백 팩은 R2 에서 완료
- 바꾼 파일
  - `scripts/lib/structure/native/langs.py`: `LangDef.import_pattern`·`pack_scopes`·`decorator_prefix`, `IMPORT_PATTERNS`(php·js(ts/vue/svelte)·go·java·kotlin·swift·csharp·dart·rust·c·py)
  - `scripts/lib/context.py`: `_imports`(패턴이 있고 구조를 읽었으면 코드·최상위에서 시작한 문장만, 열린 괄호가 닫힐 때까지), `_depth`, 폴백은 기존 `IMPORT_RE`. `PACK_SCOPES` 삭제 → langdef
  - `scripts/lib/structure/native/pyast.py`: 함수·클래스 노드 시작 줄 = 첫 데코레이터
  - `scripts/lib/structure/native/scopes.py` `_indent_blocks`: 헤더 괄호가 닫힌 줄부터 본문, skip 구간(문자열) 안의 줄은 끊지 않고 포함, 주석만 있는 줄은 끊지 않음, 같은 들여쓰기의 데코레이터 줄부터 노드 시작(주석 기호·데코레이터는 langdef 데이터 — R23k 원칙)
  - `docs/semantic-review.md`
- 추가한 테스트: `tests/semantic/test_context_pack.py` `case_imports_are_imports`(SEM r9: Go `import (` 블록, PHP trait 제외, docstring 안 `import` 제외, 여러 줄 JS import), `case_python_blocks`(SEM r1·r5: 데코레이터 포함, Black 시그니처, 데코레이터 제거 시 context_hash 변경, 파싱 실패 파일의 폴백이 데코레이터 포함·0열 주석 뒤까지)
- 테스트 결과: RED 7 → GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 후보 지문 불변
- 캐시: 데코레이터가 붙은 Python 함수, import 섹션이 바뀐 팩(Go 블록·trait·docstring·여러 줄 import)은 context/related 해시가 한 번 바뀐다(재판정 1회). 구조 계층: Python 함수 노드 start_line 이 데코레이터로 당겨져 in_scope 판정에는 영향 없음(본문 기준, R10)

### R23l — 긴 함수 팩이 예산 80줄 중 일부만 쓴다 ✅

- 선택: 남은 예산을 가운데 창에
- 바꾼 파일: `scripts/lib/context.py` `_clip_region` — 가운데 창 = 예산 − 머리 − 꼬리(3) − 생략 표시(2), 최소 FUNCTION_AROUND, 후보 중심이고 경계에 닿으면 반대쪽으로 밀어 채움
- 추가한 테스트: `tests/semantic/test_context_pack.py` `case_long_function_is_elided` 에 SEM r12 — 400줄 함수 팩이 FUNCTION_MAX_LINES−5 이상 사용, 후보 앞뒤가 함께 보임
- 테스트 결과: RED(39줄) → GREEN. `run_all.py --quiet` 전체 통과
- 골든·캐시: 변화 없음(context_hash 는 함수 전체 텍스트 기준이라 표시만 바뀜)

### R23j — verdicts.json 을 쓸 때 정리하지 않고 잠금도 없다 ✅

- 선택: 쓸 때 TTL 정리 + 잠금 파일
- 바꾼 파일
  - `scripts/lib/semantic.py`: `store(..., ttl_days)` — 그 레포 버킷만 TTL 로 정리(다른 레포는 자기 TTL 로 쓸 때), `_locked`(O_EXCL `verdicts.json.lock`, 5초 대기, 30초 지난 잠금은 인계, 못 얻으면 판정을 잃지 않도록 그냥 기록), 배치에 `verdict_ttl_days`
  - `scripts/review.py` `record`: 배치의 TTL 을 넘김
  - `docs/semantic-review.md`
- 추가한 테스트: `tests/semantic/test_review_key.py` `case_cache_writes`(이 레포의 만료 항목은 지워지고 다른 레포 항목은 유지, 스레드 둘이 동시에 기록해도 둘 다 남음 — 첫 기록자가 읽은 뒤 멈추게 해 경합을 결정적으로 재현)
- 테스트 결과: RED(API) → TTL 구현 뒤 경합 RED(`b` 유실) → 잠금 구현 GREEN. `run_all.py --quiet` 전체 통과
- 골든: 변화 없음. 캐시 형식 불변

## 추가 발견

- `scripts/lib/structure/native/langs.py` rust 행: `fn f() -> impl Iterator {` 가 class 로 분류된다. class 키워드 판정이 function 보다 먼저라서다. R1 전부터 있던 동작이다 (R1 중 발견)
- `tests/perf/run.py`: `real_rows()` 가 레포 루트 전체를 걸어서 git 이 추적하지 않는 `.claude/skills/` 아래 파일까지 잰다. 이 환경에서는 그 때문에 cache-hit 이 MISS 로 나온다. 또 실행할 때마다 추적 파일 `tests/perf/results/u1-structure-only.json` 을 덮어쓴다 (R1 중 발견)
- `scripts/lib/pipeline.py` 린터: `--staged`·`--range` 에서도 린터는 워킹 트리 파일을 검사한다. 본문을 blob 에서 읽게 된 R15 뒤에도 린터 결과는 index/리비전과 다를 수 있다 (R15 중 발견)
- `scripts/lib/hooks.py` `_verify`: 연속 차단 상한 때문에 재검증 차단을 멈춘 경우에도 요약이 "재검증 종료 … 이후 기록만"이라 상한 때문인지 시도 횟수 때문인지 구분되지 않는다(`_open` 은 '연속 차단 N회 상한'을 표시) (R4 중 발견)
