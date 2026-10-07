# 출력 형식

> **상태: 구현 완료 (2026-09-29).** 결정은 "결정 사항"에 있습니다. "공통 문법"과 "산출물별 적용"은 그 결정으로 쓴 것이고, "결정 항목"은 후보와 근거의 기록입니다.

## 목차
- 목적과 범위
- 현재 출력의 불일치 (수집 결과)
- 공통 문법
- 결정 항목
- 산출물별 적용
- 범위 밖 발견 (제안)
- 결정 사항
- 구현 체크리스트

## 목적과 범위

convention-guard 의 출력은 사람과 에이전트가 모두 읽습니다. 산출물마다 형식이 다르면 읽는 쪽이 매번 형식을 다시 해석해야 합니다.
이 문서는 모든 출력이 따르는 **공통 문법 하나**와, 산출물마다 그 문법을 적용하는 방식을 정합니다. 하위 호환은 고려하지 않습니다. 문구, 기호, `--json` 스키마가 모두 바뀔 수 있습니다.

| 산출물 | 읽는 쪽 | 렌더링 위치 |
|---|---|---|
| Stop 훅 `reason` (차단, 재검증 차단) | 에이전트 | `scripts/lib/report.py` `hook_reason`, `verify_reason`, `review_section`, `autofix_section`, `clip_reason` |
| Stop 훅 `systemMessage` (차단, 재검증, 기록, 오류) | 사용자 | `scripts/lib/stop.py` `render`, `with_notes`, `with_autofix_note`, `scripts/lib/report.py` |
| `scan.py` 텍스트, `--json`, `--fix`, `--review` 안내 | 사람, 에이전트, CI | `scripts/scan.py`, `scripts/lib/report.py` `render_text` |
| `review.py show / record / summary`, 판정 배치·판정 파일 JSON | 리뷰어 에이전트, 메인 에이전트 | `scripts/review.py`, `scripts/lib/semantic.py`, `scripts/lib/context.py` |
| `detect_stack.py` 텍스트, `--json` | 사람, 스킬 | `scripts/detect_stack.py` |
| `log_report.py` 텍스트, `--json` | 사람, `rule-tune` 스킬 | `scripts/log_report.py` |
| `readiness.py` 텍스트, `--json` | 사람, `convention-readiness` 스킬 | `scripts/readiness.py` |
| `dismiss.py` 기록 결과, `--list` | 에이전트, 사람 | `scripts/dismiss.py` |
| `setup.py init` 안내, `emit` 안내와 `.claude/rules/*.md` | 사람, 에이전트(컨텍스트) | `scripts/setup.py` |

`migrate.py` 는 대상 목록에 없어서 이 명세의 범위 밖입니다(결정 D0 참고).

## 현재 출력의 불일치 (수집 결과)

픽스처(next, laravel, go, nest)로 경로 251개를 실제로 실행해 캡처했습니다(Stop 훅 59, scan·판정 85, 리포트류 107). 형식 문제만 추렸습니다.

| 분류 | 현재 | 위치 |
|---|---|---|
| 섹션 머리 | 훅 `■ 제목`, scan 은 기호 없이 색, review show 는 `#`/`##`/`###` Markdown, log_report 는 `이름  (설명)`, readiness 는 머리 한 줄 | report.py, review.py, log_report.py |
| 안내 줄 기호 | scan `→`, 훅 `    > `, readiness `→`(15칸 들여쓰기), 괄호 보충 `(…)` | report.py:50, report.py:222, readiness.py |
| 위치 표기 | `파일:줄  스니펫`(훅, scan), `파일:줄  [규칙]  고친 줄`(자동 수정), `### 후보 N — 파일:줄`(show), `[규칙] 파일:줄 — 이유`(summary), `파일:줄 (지문 x)`(dismiss 기록), `파일:지문`(dismiss --list), `파일:-`(줄 미지정), 줄 없는 후보는 `파일:1  (새 파일에 해당 선언이 없음)` | report.py, review.py, dismiss.py |
| 강도 표기 | scan `%-5s` 줄 머리, 훅은 섹션 제목 `(error)`, show 는 `(warn)` 꼬리, detect_stack `● error`, readiness `[FAIL  ]`, log_report 판정만 있으면 `?` | |
| 요약 줄 | scan `요약  error 8 / warn 5 / info 2   (규칙 23개 중 23개 적용)`, readiness `요약: FAIL 4 · WARN 11 · PASS 12`, 훅 `error 1건 / warn 0건`, 재검증 `고쳐짐 0 / 기각 0 / 그대로 1 / 새로 생김 0` | |
| 같은 뜻, 다른 말 | reason 은 `그대로 N`, systemMessage 는 `남음 N`. 검사 경고는 `검사 경고 N건` / `검사 경고: …` / `검사 경고 — …` 세 가지 | report.py:108, hooks.py |
| 머리말 중복 | 노트 두 개를 이으면 `convention-guard:` 가 가운데에 한 번 더 나옴 | hooks.py:231,241 |
| 구분자 누락 | `린트 실패 2건 error 0건 / warn 0건` | hooks.py:627 |
| 어색한 문장 | `검사 경고: … 검사되지 않았습니다 기록. 차단하지 않았습니다.` | hooks.py:345 |
| 모순된 안내 | `--review` 로 배치를 만들었는데도 `semantic 규칙 후보 N건은 이 명령으로 판정되지 않습니다` | report.py:226 |
| 안내 누락 | 배치가 null 이면(전부 캐시, 전부 미룸) 다음 행동이 없음. 린트만 남은 재검증은 "기각으로 남기세요"라고 하면서 명령이 없음 | scan.py:190, report.py:128 |
| 잘림 표시 | 린터 15줄·5줄 자름은 표시 없음, 3000자 자름은 `... (생략)`, reason 8000자 자름은 `… (이하 생략 — …)`, 컨텍스트 팩은 `… N줄 생략 — 필요하면 Read` | report.py, lint.py, context.py |
| 빈 결과 | scan `  지적 사항 없음` 뒤에 빈 줄 없음. log_report 는 `--json` 이어도 로그가 없으면 텍스트 | report.py:205, log_report.py:234 |
| 다음 행동 명령 | 훅은 두 칸 들여 쓴 전체 명령, scan 은 `  python3 "…"`, setup·dismiss 는 한국어 문장 속 옵션 이름(`--write 를 붙이세요`) | |
| stderr | scan `[error] …`, `검사 불가: …`, dismiss 는 접두사 없는 문장, argparse 는 영어 | |
| JSON | 모두 snake_case. 버전 필드 없음, 봉투(최상위 구조)가 스크립트마다 다름(`head/counts/findings`, `root/version/items`, `events/rules/linters`), 위치는 `file`+`line`, 구조 미확인 정보는 `--json` 에 없음 | scan.py:156, readiness.py, log_report.py |
| 표 정렬 | 한글 헤더가 두 칸을 차지해 log_report 열이 어긋남, detect_stack 긴 린터 명령이 정렬을 밈 | log_report.py, detect_stack.py |
| 줄 번호 폭 | 컨텍스트 팩 `import`·`changed_hunks` 절은 줄마다 따로 번호를 매겨 폭이 들쭉날쭉 | context.py |

## 공통 문법

확정된 결정(D0~D19, "결정 사항" 절)을 규칙으로 옮긴 것입니다. 형식 검증 테스트(`tests/integration/test_output_format.py`)는 이 절의 규칙 번호(F1~F16)를 검사합니다.

한 출력은 다음 요소로만 이루어집니다.

```
<머리말>                      한 줄. 무엇을, 어디에 대해, 결과가 어떤지
                              (빈 줄)
■ <섹션 제목>                 블록마다 하나
<항목 머리>                   ✖ error[규칙]: 제목 / 점검 항목 / 기록 한 건
  <위치 줄>                   파일:줄  스니펫
  = <라벨>: <내용>            보조 줄 — 안내, 참고, 이유, 조치
                              (빈 줄)
■ 다음                        - 문장
  $ <명령>                    그대로 복사해 실행할 명령
                              (빈 줄)
<요약 줄>                     ✖ 15건 (error 8 · warn 5 · info 2) / ✔ 지적 없음
```

### 규칙

| 번호 | 요소 | 규칙 | 결정 |
|---|---|---|---|
| F1 | 머리말 | 첫 줄. `convention-guard <명령>[ <옵션>] — <속성> · <속성> …`. 훅은 명령 자리에 상태가 온다: `convention-guard <아이콘> <상태> — <속성> · …` | D1, D11 |
| F2 | 섹션 제목 | `■ <제목>` 또는 `■ <제목> — <설명>`. 섹션 앞에는 빈 줄 하나. 빈 섹션은 쓰지 않는다 | D2 |
| F3 | 항목 머리 (지적) | `<아이콘> <강도>[<규칙 id>]: <제목>`. 아이콘은 `✖ error`, `⚠ warn`, `ℹ info` 로 강도와 짝이다 | D4, D5, D17 |
| F4 | 위치 줄 | 두 칸 들여 `<파일>:<줄>  <스니펫>`. 줄이 없는 후보(파일, 변경 집합 단위)는 `<파일>  <스니펫>`. 스니펫이 없으면 위치만. 줄은 1부터. 지문은 위치에 쓰지 않는다 | D3 |
| F5 | 보조 줄 | 항목보다 두 칸 더 들여 `= <라벨>: <내용>`. 라벨은 `안내`, `참고`, `이유`, `조치` 넷뿐. 여러 줄이면 둘째 줄부터 내용 시작 칸에 맞춰 들여 쓴다 | D6 |
| F6 | 다음 | 다음 행동은 `■ 다음` 섹션에만 둔다. 줄마다 `- <문장>`, 실행할 명령은 그 아래 `  $ <명령>`. 명령은 인터프리터부터 인자까지 전부 쓴다. 본문에 명령을 흩뜨리지 않는다(린터 섹션의 `$ <실행한 명령>` 은 기록이지 안내가 아니다) | D7 |
| F7 | 요약 줄 | 지적을 세는 CLI 출력(scan)의 마지막 줄. `<아이콘> <N>건 (error <n> · warn <n> · info <n>)`, 0 도 쓴다. 아이콘은 가장 높은 강도의 것. 지적이 없으면 `✔ 지적 없음`. 나머지 출력은 머리말이 개수를 싣는다 | D8 |
| F8 | 점검 상태 | 줄 머리 `<아이콘> <상태>` — `✖ fail`, `⚠ warn`, `? manual`, `○ skip`, `✔ pass`. 적용 여부는 `✔ on`, `○ off` | D9, D17 |
| F9 | 잘림 | 자른 자리에 `… <N>줄 더` 또는 `… <N>건 더`. 전체를 볼 명령이 있으면 ` — 전체: <명령>`. 인라인 목록 접기는 `a, b 외 <N>개` | D10 |
| F10 | 표 | 머리행, `─` 구분선, 행. 열 사이 두 칸. 폭은 표시 폭(동아시아 전각 = 2칸)으로 맞춘다. 표는 detect_stack 규칙, log_report, dismiss --list, readiness 요약에만 쓴다 | D19 |
| F11 | 용어 | 아래 용어 표만 쓴다 | D13 |
| F12 | stderr | 진단은 stderr 에 `convention-guard: error: <문장>` / `convention-guard: warn: <문장>`. stdout 에는 결과만. argparse 의 `usage:` 오류는 그대로 | D14 |
| F13 | 색 | stdout 이 TTY 이고 `--no-color`, `NO_COLOR`(비어 있지 않음), `TERM=dumb` 가 모두 없을 때만 ANSI 색. 훅 출력과 `--json` 에는 절대 넣지 않는다. 색 배정은 아래 표 | D18 |
| F14 | 문자 집합 | 기호는 `■ ✖ ⚠ ℹ ✔ ○ ? — · … ⏎ ─` 만. `→ ← ● > [PASS` 같은 옛 기호는 쓰지 않는다. `TERM=dumb` 이면 `# x ! i v - ? - . ... / -` 로 바꾼다 | D17 |
| F15 | JSON | `--json` 은 stdout 에 JSON 하나. 봉투 `{"schema": "convention-guard/<명령>@1", "tool": {"name": "convention-guard", "version": "<X.Y.Z>"}, "summary": {…}, …, "notes": [{"level", "text"}], "next": [{"text", "command"}]}`. 이름은 snake_case. 위치는 `{"file", "line"}`, 줄이 없으면 `"line": null`. 후보 위치에는 `key`. 빈 결과도 같은 봉투 | D12 |
| F16 | 종료 코드 | 0 통과·할 일 없음 / 1 지적 있음·조치 필요 / 2 검사 불가·입력 오류. 훅과 log_report 는 항상 0 | D16 |

F14 의 ASCII 대체는 `TERM=dumb` 에서만 합니다. D17 에 적었던 "UTF-8 이 아닌 로케일"은 본문이 한국어라 그 환경에서는 아이콘과 상관없이 출력 자체가 인코딩되지 않으므로 조건에서 뺐습니다.

### 아이콘과 색

| 뜻 | 아이콘 | ASCII | 색 (F13) |
|---|---|---|---|
| error, fail, 남음, 차단 | `✖` | `x` | 빨강 |
| warn, 새로 생김, 기록(warn 이하) | `⚠` | `!` | 노랑 |
| info | `ℹ` | `i` | 청록 |
| pass, on, 고쳐짐, 통과, 기록함 | `✔` | `v` | 초록 |
| skip, off | `○` | `-` | 흐리게 |
| manual | `?` | `?` | 노랑 |
| 섹션 | `■` | `#` | 굵게 |

그 밖의 색: 규칙 제목 굵게, 규칙 id·스니펫·보조 줄 라벨(`= 안내:`)·머리말 속성 흐리게, `$ <명령>` 줄 청록, 요약 줄 굵게.

### 용어

| 개념 | 쓸 말 | 쓰지 않을 말 |
|---|---|---|
| 재검증 때 여전히 있는 후보 | 남음 | 그대로 |
| 수정하면서 생긴 후보 | 새로 생김 | 신규 |
| 오탐으로 넘긴 기록 | 기각 | dismiss(본문) |
| 파이프라인이 낸 경고 노트 | 검사 경고 | |
| 리뷰어 판정을 기다리는 후보 | 판정 대기 | 심층 판정 필요, 판정 대기 후보 |
| 차단 없이 기록만 | 기록 | |
| 후보의 식별자 `규칙:파일:지문` | 키 | |
| 코드 지문 10자리 | 지문 | hash(본문) |

### 개수 세는 법

`error N` 은 지금처럼 **규칙 수**입니다(위치 수가 아님). 세는 법은 형식이 아니라 동작이라 바꾸지 않습니다.

## 결정 항목

항목마다 후보 2~3개, 장단점, 근거 사례를 둡니다. 근거의 출처는 "근거 출처" 목록의 번호입니다.

### D0. 범위 — `migrate.py` 포함 여부

| 후보 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A** | 넣지 않는다 (요청 목록 그대로) | diff 가 작고 검토가 쉽다 | migrate 만 옛 문법이 남는다 |
| B | 넣는다 | 모든 스크립트가 같은 문법 | 요청 범위 밖이고 migrate 테스트·문서도 함께 바뀐다 |

### D1. 머리말

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `convention-guard <명령> — <대상> · <속성> · …` 한 줄 | 출처와 대상이 첫 줄에 있다. 훅 systemMessage 와 같은 모양을 쓸 수 있다 | 속성이 많으면 줄이 길어진다 |
| B | 산출물별 현행 유지(scan 두 줄, readiness 한 줄, 나머지 없음) | 변경이 적다 | 불일치가 그대로다 |
| C | 머리말 없음, 요약 줄만 (ruff concise 식) | 가장 짧다 | 여러 출력을 이어 붙이면 어느 도구의 출력인지 모른다 |

근거: GNU 표준은 파일이 없는 메시지를 `program: message` 로 씁니다 [1]. RuboCop 은 `Inspecting 26 files` 로 시작합니다 [12]. readiness 의 현행 `convention-guard 도입 점검 — <root> · 플러그인 3.1.1` 이 이미 A 모양입니다. ruff concise, ESLint 는 머리말이 없습니다(C) [3][4].

### D2. 섹션 제목

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `## 제목` (Markdown 2단계). 설명이 필요하면 `## 제목 — 설명` | 에이전트가 Markdown 구조로 바로 읽는다. review show 와 emit 파일이 이미 Markdown 이다 | 터미널에서 `##` 가 조금 거슬린다 |
| B | `■ 제목` (현행 훅 방식을 전체로) | 눈에 잘 띈다 | 비 ASCII 기호. Markdown 문서(show, emit)와는 따로 논다 |
| C | `제목:` 한 줄 + 빈 줄 | 가장 평범하다 | 항목 줄과 구분이 약하다 |

근거: RuboCop 은 `Offenses:` 제목을 씁니다 [12](C). npm audit 은 `# npm audit report` 를 씁니다 [13](A). clig.dev 는 "같은 종류의 오류가 여럿이면 설명 제목 하나 아래로 묶으라"고 권합니다 [2]. Anthropic 도구 설계 글은 에이전트 응답 형식으로 "XML, JSON, Markdown" 을 들되 정답은 없다고 합니다 [16].

### D3. 위치 표기

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 줄이 있으면 `파일:줄`(1부터), 파일·변경 집합 단위면 `파일` 만. 지문은 위치에 넣지 않고 키로만 쓴다 | GNU·SARIF 와 같다. `파일:지문` 혼용이 사라진다 | 줄 없는 후보가 줄 있는 후보와 모양이 다르다 |
| B | 항상 `파일:줄`. 파일 단위는 `파일:1` (현행) | 모든 줄이 같은 모양 | 1번 줄에 문제가 있다는 오해를 준다(ESLint 의 `0:0` 과 같은 문제) |
| C | `파일:줄:열` | 에디터 점프가 정확하다 | 열 정보가 없다. 만들려면 탐지 로직을 바꿔야 한다 |

근거: GNU `sourcefile:lineno:column`, 파일이 없으면 `program: message` [1]. SARIF 는 "region 이 없으면 파일 전체"입니다 [8]. ESLint 는 줄이 없으면 `0:0` 을 찍습니다 [4](B 와 같은 문제). golangci-lint 는 열을 모르면 생략합니다 [6]. 1부터 세는 것은 GNU, GCC, GitHub Actions, SARIF 가 같습니다 [1][5][7][8]. 사례끼리 갈리는 점: Pyright JSON 은 0부터 셉니다 [10].

### D4. 강도 어휘와 위치

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 소문자 `error` / `warn` / `info`. 항목 줄 맨 앞 | 규칙 스키마·config 값과 같다(`severity: warn`) | 표준 어휘(`warning`, `note`)와 다르다 |
| B | `error` / `warning` / `note` (SARIF·rustc) | 외부 도구와 같다 | 설정에는 `warn` 이라 쓰고 출력에는 `warning` 이 나와 한 단어가 두 모양이 된다 |

근거: rustc·clippy `error[E0277]:`, `warning:`, `note:` [3]. mypy `error:`/`note:` [5]. SARIF `error/warning/note/none` [8]. shellcheck `error, warning, info, style` [9]. Pyright `information` [10]. 사례끼리 어휘가 갈립니다(note/notice/info/information). 줄 맨 앞(rustc)과 위치 뒤(GCC, mypy)로도 갈립니다.

### D5. 지적 한 건의 배치

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 규칙으로 묶는다(rustc 식). `error[core/x]: 제목` 다음에 들여 쓴 위치 줄들, 그 뒤에 보조 줄 | 안내문이 규칙마다 한 번만 나와 토큰이 적다. 규칙 id 가 강도 옆에 붙어 grep 이 쉽다 | 위치가 줄 머리에 오지 않아 에디터 점프 정규식은 들여쓰기를 감안해야 한다 |
| B | 위치마다 한 줄(GNU 식). `파일:줄: error core/x: 제목` 다음 줄에 스니펫. 안내는 규칙의 마지막 위치 뒤에 한 번 | 에디터·grep 친화 | 규칙 제목이 위치마다 반복된다 |
| C | 현행 scan (`error 제목  core/x` / 위치 / `→ 안내`) | 변경이 적다 | 규칙 id 가 줄 끝이라 스캔하기 어렵다 |

근거: rustc 는 `level[code]: msg` 뒤에 ` --> 위치`, 스니펫, `= help:` 를 씁니다 [3]. ruff full 도 같습니다 [3]. ESLint stylish 는 파일로 묶고 규칙 id 를 끝에 둡니다 [4]. GNU·shellcheck·mypy 는 위치로 시작하는 한 줄입니다(B) [1][5][9]. 규칙 id 위치는 앞(ruff, rustc, RuboCop)과 끝(ESLint, mypy, golangci)으로 갈립니다.

### D6. 보조 줄 (안내·참고·이유·조치)

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `  = 라벨: 내용` — 라벨은 `안내`, `참고`, `이유`, `조치` 네 가지 | 줄의 성격이 첫 단어로 드러난다. rustc 의 `= help:`, `= note:` 와 같은 모양 | 여러 줄 안내는 줄마다 라벨을 붙이지 않고 이어지는 줄을 같은 폭으로 들여 써야 한다 |
| B | `  → 내용` (현행 scan·readiness) | 짧다 | 안내와 조치와 참고를 구분하지 못한다 |
| C | `  > 내용` (현행 훅) | Markdown 인용과 같다 | B 와 같은 문제 |

근거: rustc `= help:`, `= note:` [3]. git status 는 두 칸 들여 쓴 괄호 안내 `(use "git add <file>..." to …)` 를 씁니다 [11]. flutter doctor 는 하위 항목을 `•`, `!`, `✗` 로 씁니다 [14].

### D7. 다음 행동 명령

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `## 다음` 섹션. 줄마다 `- 문장` 이고, 명령은 그 아래 `  $ 명령` 으로 그대로 복사할 수 있게 쓴다 | 에이전트가 "무엇을 하라"를 한 곳에서 찾는다. `$` 줄은 복사해 바로 실행할 수 있다 | 짧은 출력(setup init)도 섹션이 하나 생긴다 |
| B | git 식 괄호 안내 `  (오탐이면: python3 …)` 를 해당 항목 바로 아래에 | 맥락 옆에 있다 | 명령이 흩어진다 |
| C | 문장 안의 백틱 `` `--write` 를 붙이세요 `` (ruff·ESLint 식) | 짧다 | 전체 명령이 아니어서 에이전트가 조립해야 한다 |

근거: clig.dev "Suggest commands the user should run" [2]. git status 괄호 안내 [11](B). ruff `[*] 1 fixable with the \`--fix\` option.`, ESLint `potentially fixable with the \`--fix\` option.` [3][4](C). cargo `(run \`cargo fix …\` to apply N suggestions)` [15]. Anthropic 도구 설계 글은 오류 응답에 "구체적이고 실행 가능한 개선"을 담으라고 합니다 [16].

### D8. 요약 줄

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 마지막 줄 `요약: error 8 · warn 5 · info 2`. 0 도 쓴다. 빈 결과면 `요약: 지적 없음` | 모양이 고정이라 읽고 파싱하기 쉽다. readiness 가 이미 `·` 를 쓴다 | 0건이 눈에 띄는 잡음일 수 있다 |
| B | ESLint 식 `✖ 15건 (error 8, warn 5, info 2)` | 익숙하다 | 비 ASCII 기호. 빈 결과면 침묵한다(ESLint) |
| C | A 와 같되 0 인 항목은 뺀다 | 짧다 | 줄 모양이 매번 달라진다 |

근거: ESLint `✖ 9 problems (5 errors, 4 warnings)`, 빈 결과면 출력 없음 [4]. ruff `Found 3 errors.` / `All checks passed!` [3]. mypy `Found N errors in M files` / `Success: no issues found` [5]. RuboCop `… no offenses detected` [12]. 빈 결과를 한 줄로 알리는 쪽(ruff, mypy, RuboCop)이 다수입니다. clig.dev 도 "성공해도 짧게 출력하라"고 합니다 [2].

### D9. 점검·적용 상태 표시 (readiness, detect_stack)

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 줄 머리에 소문자 단어를 폭 6으로: `fail  `, `warn  `, `manual`, `skip  `, `pass  `. detect_stack 은 `on `/`off` | 지적 줄의 강도와 같은 자리, 같은 모양이다. ASCII | 대괄호가 없어 눈에 덜 띈다 |
| B | flutter 식 `[✓]` `[!]` `[✗]` `[-]` `[?]` | 한눈에 보인다 | 비 ASCII. 기계로 읽을 때 기호표가 필요하다 |
| C | 현행 `[PASS  ]` `[MANUAL]`, `●`/`○` | 변경이 적다 | 두 스크립트가 서로 다른 모양을 쓴다 |

근거: flutter doctor `[✓] [!] [✗]` [14]. brew doctor 는 문제마다 `Warning: …` 를 씁니다 [14]. `[PASS  ]` 식 고정 폭 괄호는 1차 출처를 찾지 못했습니다(미확인).

### D10. 잘림 표시

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 잘린 자리에 `  … N줄 더` (또는 `N건 더`), 전체를 볼 방법이 있으면 `— 전체: <명령>`. 모든 자름에 붙인다 | 잘린 것을 통과로 오인하지 않는다 | 줄이 하나 늘어난다 |
| B | 현행처럼 자르는 곳마다 따로 | 변경이 적다 | 린터 자름에는 표시가 없다 |

근거: Anthropic 도구 설계 글은 응답을 자를 때 에이전트에게 도움이 되는 안내를 붙이라고 합니다 [16]. Claude Code 훅 출력은 10,000자가 넘으면 파일로 옮겨지고 앞 2,000자만 전달됩니다 [17]. 그래서 8,000자 자름 표시가 필요합니다. ruff 는 `(M hidden fixes can be enabled …)` 로 숨긴 개수를 알립니다 [3].

### D11. Stop 훅의 `reason` 과 `systemMessage`

`systemMessage` 는 사용자에게만 보이고 `reason` 은 에이전트에게 갑니다 [17].

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `systemMessage` 는 `reason` 의 머리말과 **같은 한 줄**이다: `convention-guard 차단 — error 1 · warn 0`. 노트는 ` · ` 로 잇고 접두사는 한 번만 쓴다. `reason` 은 머리말 → 섹션 → `## 다음` 순서이고 요약 줄은 없다(머리말이 요약) | 사용자와 에이전트가 같은 숫자를 같은 말로 본다 | 사용자에게는 머리말보다 긴 설명이 없다 |
| B | `systemMessage` 는 현행 짧은 요약, `reason` 끝에 요약 줄을 따로 | 에이전트가 끝에서 요약을 본다 | 같은 숫자가 두 곳에 다른 모양으로 나온다 |

근거: Claude Code hooks 원문: `reason` "Tells Claude why it should continue", `systemMessage` "Warning message shown to the user", 상한 10,000자 [17]. Anthropic: "필요한 신호만 돌려주라" [16].

### D12. JSON

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 모든 `--json` 에 같은 봉투를 씌운다: `{"schema": "convention-guard/<명령>@1", "tool": {"name", "version"}, "summary": {…}, …본문…, "notes": [{"level","text"}], "next": [{"text","command"}]}`. 이름은 snake_case. 위치는 `{"file","line"}`(줄 없으면 `line: null`), 후보마다 `key`. 텍스트에만 있던 정보(구조 미확인, 다음 행동)도 넣는다 | 스크립트가 달라도 파싱 코드가 같다. 버전 필드로 스키마 변경을 알 수 있다. `key` 가 SARIF `partialFingerprints`, GitLab `fingerprint` 자리에 들어맞는다 | 현행 JSON 을 쓰는 스킬 문서를 모두 고쳐야 한다 |
| B | `scan --json` 은 SARIF 2.1.0 으로, 나머지는 A | GitHub code scanning 에 바로 올릴 수 있다 | camelCase 와 snake_case 가 섞이고 SARIF 는 장황하다 |
| C | 현행 스키마 유지, 빈 결과 JSON 누락 같은 결함만 고침 | 변경이 적다 | 봉투 불일치가 그대로다 |

근거: Pyright `{version, time, generalDiagnostics, summary}` [10]. RuboCop `{metadata, files, summary}` [12]. SARIF `{version, $schema, runs}` 와 `partialFingerprints` [8]. GitLab Code Quality 는 `fingerprint` 가 필수입니다 [18]. 사례끼리 갈리는 점: ESLint·ruff 는 봉투 없는 배열이고, 이름 규칙도 camelCase(ESLint, SARIF, Pyright)와 snake_case(ruff, RuboCop, GitLab)로 갈립니다 [4][3].

### D13. 용어 통일

| 후보 | 내용 |
|---|---|
| **A** | "공통 문법"의 용어 표대로 (`남음`, `새로 생김`, `판정 대기`, `검사 경고`, `기각`, `키`, `지문`) |
| B | `남음` 대신 `그대로`를 쓰고, 나머지는 A |

근거: SARIF 는 `level` 어휘를 명세로 고정합니다 [8]. ESLint 는 모든 formatter 가 같은 `problems` 개수 어휘를 씁니다 [4].

### D14. stderr 진단 줄

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | `convention-guard: error: 문장` / `convention-guard: warn: 문장` | GNU `program: message` 와 같다. 파이프를 여러 개 이어도 출처가 보인다 | 길다 |
| B | `error: 문장` (rustc·cargo 식) | 짧다 | 출처가 없다 |
| C | 현행 `[error] 문장` | 변경이 적다 | 대괄호 표기가 D9 A 와 겹친다 |

근거: GNU [1], mypy `error:` [5], rustc `error:` [3], brew `Warning:` [14]. argparse 의 영어 `usage:` 오류는 표준 라이브러리 출력이라 모든 후보에서 그대로 둡니다.

### D15. 색과 문자 집합

| 후보 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A** | 색은 stdout 이 TTY 이고 `--no-color`, `NO_COLOR`, `TERM=dumb` 가 모두 없을 때만 켠다. 기호는 ASCII 와 `—` `·` `…` `⏎`(여러 줄 스니펫의 줄 경계) 네 문자만 쓰고 `■ ● ○ → ←` 는 뺀다. 강도 변경은 `error->warn` 으로 쓴다 | 에이전트 토큰이 줄고 로케일에 덜 민감하다. NO_COLOR 표준을 따른다 | 사람이 볼 때 조금 밋밋하다 |
| B | 색 규칙은 A, 기호는 현행 유지 | 변경이 적다 | 기호 불일치가 남는다 |

근거: NO_COLOR 표준 [19]. clig.dev 는 TTY 가 아니거나, `NO_COLOR`, `TERM=dumb`, `--no-color` 가 있으면 색을 끄라고 합니다 [2]. GCC 는 `LANG=C` 이면 ASCII 로 바꿉니다 [5]. stylelint 는 유니코드를 지원하지 않으면 대체 문자를 씁니다 [4].

### D16. 종료 코드

| 후보 | 내용 |
|---|---|
| **A** | 현행 규약을 문서로만 고정한다: 0 통과·할 일 없음 / 1 지적 있음·조치 필요(scan 지적, readiness FAIL, dismiss 위치 없음, setup init 이미 있음, migrate 남은 변경) / 2 검사 불가·입력 오류. Stop 훅과 log_report 는 항상 0 |
| B | A 에 더해 setup init 이미 있음을 0 으로 바꾼다(ruff·ESLint 식으로 1 은 "지적"에만 쓴다) |

근거: ESLint, ruff, shellcheck, mypy 가 0/1/2 입니다 [3][4][5][9]. golangci-lint 는 3 이상을 세분화합니다 [6].

### 사람이 보는 출력의 가독성 (D17~D19)

사람이 보는 출력은 CLI 텍스트(scan, readiness, detect_stack, log_report, dismiss, setup)와 훅 `systemMessage` 입니다.
에이전트가 읽는 출력은 훅 `reason`, `review.py show`, `--json` 입니다. 두 쪽은 같은 문법을 쓰고, **색은 사람 쪽 TTY 에서만** 켭니다.

### D17. 아이콘

| 후보 | 모양 | 장점 | 단점 |
|---|---|---|---|
| **A** | 단색 유니코드 기호(폭 1) + 단어: `✖ error` `⚠ warn` `ℹ info` `✔ pass` `○ skip` `? manual`, 섹션 `■`. UTF-8 이 아닌 로케일이나 `TERM=dumb` 에서는 ASCII(`x ! i v - ?`, `#`)로 바꾼다 | 색이 없어도 모양으로 구분된다. 단어가 남아 grep 과 색약에도 안전하다 | `⚠` `ℹ` 는 일부 터미널에서 두 칸으로 그려져 정렬이 한 칸 밀릴 수 있다 |
| B | 이모지 `🔴` `🟡` `🔵` `✅` `⏭️` | 색이 없는 곳(systemMessage)에서도 색이 보인다 | 폭 2, 글꼴에 따라 깨진다. 에이전트 토큰이 늘어난다 |
| C | 기호는 확정된 `■`(D2)와 `✖`(D8)만, 나머지는 색으로만 | 가장 조용하다 | 색이 없는 곳(systemMessage, 파이프)에서는 구분이 약하다 |

근거: ESLint·stylelint 는 `✖ ⚠ ℹ` 를 쓰고, 유니코드를 지원하지 않으면 `× ‼ i` 로 바꿉니다 [4]. flutter doctor `[✓] [!] [✗]` [14]. GCC 는 `LANG=C` 에서 ASCII 로 바꿉니다 [5]. clig.dev 는 기호를 쓰되 남용하지 말라고 합니다 [2].

### D18. 색 (TTY 에서만, `NO_COLOR`·`TERM=dumb`·`--no-color` 면 끔)

| 후보 | 칠하는 곳 | 장점 | 단점 |
|---|---|---|---|
| **A** | 의미색: error·fail·남음 빨강, warn·새로 생김 노랑, info 청록, pass·고쳐짐 초록. 섹션 제목과 규칙 제목 굵게, 규칙 id·스니펫·보조 줄 라벨 흐리게, `$ 명령` 줄 청록 | 훑어볼 때 중요한 줄만 눈에 들어온다 | 색 코드가 늘어 테스트는 `--no-color` 로 비교해야 한다 |
| B | 강도 단어와 아이콘만 칠하고 나머지는 기본색 (현행 scan 과 비슷) | 조용하다 | 섹션 구분이 약하다 |

훅 `reason`·`systemMessage`·`--json` 에는 두 후보 모두 색을 넣지 않습니다. `systemMessage` 가 ANSI 를 그리는지는 공식 문서에서 확인하지 못했습니다(미확인) [17].
근거: NO_COLOR [19], clig.dev 색 조건 [2], ESLint stylish 는 규칙 id 를 흐리게 칠합니다 [4].

### D19. 표

| 후보 | 쓰는 곳 | 모양 | 장점 | 단점 |
|---|---|---|---|---|
| **A** | 열이 짧고 고정된 목록만: detect_stack 규칙, log_report, dismiss --list, 재검증 개수, readiness 요약 | 머리행 + `─` 구분선 + 한글 폭 보정 정렬. 지적(스니펫이 긴 것)은 D5 목록 그대로 | 터미널 폭 안에 들어간다. 긴 스니펫이 표를 깨지 않는다 | 표와 목록이 섞인다 |
| B | A 와 같은 곳 | 박스 표 `┌─┬─┐ │ └─┴─┘` | 가장 표처럼 보인다 | 선 문자가 토큰과 폭을 먹는다. 좁은 터미널에서 줄바꿈되면 깨진다 |
| C | A 와 같은 곳 + review show·emit 파일 | Markdown 표 `\| a \| b \|` | 에이전트가 사용자에게 옮길 때 Claude Code 화면에서 표로 그려진다 | 터미널에서는 `\|` 가 보인다 |

근거: RuboCop·ESLint stylish 는 정렬 열을 씁니다 [4][12]. log_report 는 이미 정렬 표를 쓰지만 한글 폭 때문에 어긋납니다(수집 결과). Pyright·golangci 텍스트 출력은 표를 쓰지 않습니다 [6][10].

## 산출물별 적용

경로는 `…` 로 줄였습니다. 색은 표시하지 않았습니다(F13).

### 1. Stop 훅 — 차단 (`reason`, `systemMessage`)

```
convention-guard ✖ 차단 — error 1 · warn 1

■ 지적 — 고치거나 기각하세요
✖ error[core/php-no-debug-output]: 디버그 출력 잔여물
  app/Svc/A.php:4  class A { public function f() { dd(1); } }
  = 안내: 디버그 출력이 남아 있습니다. 제거하고, 필요하면 Log 파사드로 남기세요.
  = 참고: 지난 턴에도 지적했습니다

■ 참고 — 차단하지 않습니다
⚠ warn[core/php-no-empty-catch]: 빈 catch 블록 금지
  app/Svc/A.php:9  catch (\Throwable $e) {}
  = 안내: 예외를 삼키지 마세요. 최소한 로그를 남기거나, 의도적으로 무시한다면
          이유를 주석으로 남기세요.

■ 다음
- 후보는 정규식으로 좁힌 것이라 오탐이 있을 수 있습니다. 코드를 보고 위반이면 고치세요.
- 오탐이면 고치지 말고 기각으로 남기세요. 코드가 그대로인 동안 다시 지적하지 않습니다.
  $ python3 "…/scripts/dismiss.py" --key core/php-no-debug-output:app/Svc/A.php:f8a8cfe07d --by agent --reason "<한 줄 이유>"
  = 참고: 다른 위치는 --key 대신 --rule <규칙id> --file <파일> --line <줄>
- 끝내면 같은 범위를 다시 검사해 남은 것과 새로 생긴 것만 알립니다.
```

- `systemMessage` 는 `reason` 의 첫 줄과 같습니다(D11). 노트는 ` · ` 로 뒤에 붙고 `convention-guard` 는 한 번만 나옵니다. 노트: 자동 수정, 구조 미확인 또는 `구조 엔진 없음 (사유) — 구조 미확인 N개 파일`, 큰 파일 미검사, 그리고 수집 훅의 관찰 누락(4.0) — `관찰 누락 N개 파일 — 실행 후 기록 없음 (…, 에이전트 변경으로 보고 검사)`, `관찰 누락 N개 파일 — 실행 전 기록 없음 (…)`, `출처 미확인 변경 N개 파일 — 에이전트 도구 밖에서 바뀜, 검사 안 함 (…)`, `작업 트리 관찰 실패 N회`, `검사되지 않음 N개 파일 (레포 밖: …)`, `git 레포가 아니라 검사하지 않음`, `수집 훅 오류 N회 (…)`.
- 머리말 속성 순서: `린터 실패 N` → `error N` → `warn N` → `info N`(있을 때) → `판정 대기 N`(있을 때) → `검사 경고 N`(있을 때).
- 섹션 순서: `■ 자동 수정` → `■ 린터 실패` → `■ 지적` → `■ 참고` → `■ 판정 대기` → `■ 린터 참고` → `■ 검사 경고` → `■ 다음`.
- 리뷰어가 VIOLATION 으로 판정한 규칙은 `= 참고: 리뷰어 판정 VIOLATION` 을 붙입니다.
- `reason` 에는 요약 줄이 없습니다. 8,000자를 넘으면 `… 이하 생략 — 위 항목부터 처리하세요` 로 끝냅니다(F9).

섹션별 모양:

```
■ 자동 수정 — 2건, 이 파일들은 편집 전에 다시 읽으세요
✔ core/php-cast-spacing
  app/Svc/A.php:11  $n = (int)$v;

■ 린터 실패 — 확정 위반입니다. 먼저 고치세요
  $ ./vendor/bin/phpstan analyse --no-progress …
    app/Svc/A.php:3  Undefined variable $x
    … 12줄 더
  = 참고: 같은 파일의 기존 코드에 3건 더 있지만 이번 변경이 아니라 차단하지 않았습니다

■ 판정 대기 — 후보 1건 (core/laravel-n-plus-one 1)
  정규식만으로는 위반인지 알 수 없는 후보입니다.
  (판정 단위 후보만 있으면 이 줄은 "규칙이 정한 파일에 추가한 코드입니다. 함수·파일 머리 단위로 판정합니다.")
  = 참고: 지난번 판정 요청이 실행되지 않았습니다. 이번에는 꼭 판정을 맡기세요.

■ 검사 경고
⚠ 린터 ./vendor/bin/phpstan 를 돌리지 못했습니다 (시간 초과) — 이번 변경은 이 린터로 검사되지 않았습니다

■ 다음
- convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 전달해 판정을 맡기세요. 돌려준 VIOLATION 만 고치세요.
  $ python3 "…/scripts/review.py" show "…/convention-guard.db#3f2a9c…"
  = 참고: 나머지 2건은 예산 때문에 다음 판정으로 미뤘습니다
```

### 2. Stop 훅 — 재검증

```
convention-guard ✖ 재검증 차단 — 고쳐짐 0 · 기각 0 · 남음 2 · 새로 생김 0

■ 남음
✖ error[core/php-no-debug-output]: 디버그 출력 잔여물
  app/Svc/A.php:4  class A { public function f() { dd(1); } }

■ 새로 생김
✖ 린터 실패
  $ ./vendor/bin/pint --test -v app/Svc/A.php
    app/Svc/A.php:5  …

■ 참고 — 차단하지 않습니다
⚠ warn[core/php-no-empty-catch]: 빈 catch 블록 금지
  app/Svc/A.php:6  try { $x = 1; } catch (\Exception $e) { }

■ 다음
- 위반이면 고치고, 오탐이면 고치지 말고 기각으로 남기세요.
  $ python3 "…/scripts/dismiss.py" --key core/php-no-debug-output:app/Svc/A.php:f8a8cfe07d --by agent --reason "<한 줄 이유>"
- 린터 실패는 기각할 수 없습니다. 고치세요.
- 이번이 마지막 재검증입니다. 다음에 끝낼 때는 남은 항목을 기록만 하고 차단하지 않습니다.
```

머리말의 남음·새로 생김 수는 본문 항목 수와 같습니다. 차단 대상은 `■ 남음`·`■ 새로 생김`, 차단하지 않는 것은 `■ 참고` 에 나옵니다. `검사에서 빠짐 N` 은 후보가 결과에서 사라졌지만 코드가 에이전트 줄에 그대로 있을 때(사이클 도중 엔진 설치, 규칙 끄기·exclude — 의미 판정 규칙 제외)만 `기각` 뒤에 붙습니다.

`when_code_added` 규칙의 새 지적은 `■ 보고만 — 고치지 않아도 이번 요청은 끝납니다` 에 나오고 머리말에 `보고만 N` 이 붙습니다. 판정을 다시 맡길 후보가 있으면 `■ 판정 대기` 섹션과 `판정 대기 N`, 이번 사이클 밖 판정 단위는 `재검증 범위 밖 판정 보류 N`, 검사 경고가 있으면 `검사 경고 N` 이 붙습니다.

기각 문장은 규칙 후보가 남았을 때만, 린터 문장은 린터가 남았을 때만 씁니다.

### 3. Stop 훅 — 차단하지 않는 알림 (`systemMessage` 만)

```
convention-guard ✔ 재검증 통과 — 고쳐짐 2 · 기각 1
convention-guard ✔ 재검증 통과 — 고쳐짐 0 · 기각 0 · 검사에서 빠짐 2
convention-guard ⚠ 재검증 종료 — 고쳐짐 0 · 기각 0 · 남음 1 · 새로 생김 0 · 이후 기록만
convention-guard ⚠ 재검증 종료 — 고쳐짐 1 · 기각 0 · 남음 0 · 새로 생김 0 · 보고만 1 · 이후 기록만
convention-guard ⚠ 재검증 종료 — 고쳐짐 1 · 기각 0 · 미표시 1 · 다음 요청에서 다시 알림
convention-guard ⚠ 재검증 종료 — 고쳐짐 0 · 기각 0 · 남음 0 · 새로 생김 0 · 린터 미확인 1 · 이후 기록만
convention-guard ⚠ 기록 — warn 1 (core/php-no-empty-catch)
convention-guard ℹ 기록 — info 1
convention-guard ✖ 기록 — error 1 · 차단 안 함: mode=report
convention-guard ✖ 기록 — error 2 · 차단 안 함: 연속 차단 3회 상한
convention-guard ⚠ 기록 — 판정 대기 1 · 차단 안 함: mode=report
convention-guard ⚠ 기록 — 검사 경고 1: 린터 ./vendor/bin/phpstan 를 돌리지 못했습니다 (시간 초과) — 이번 변경은 이 린터로 검사되지 않았습니다
convention-guard ⚠ 기록 — warn 1 (core/x) · 자동 수정 2 (app/Svc/A.php) — 편집 전에 다시 읽으세요 · 구조 미확인 1개 파일 (app/Svc/B.php)
convention-guard ✖ 건너뜀 — 설정 오류: 레포 config.yaml: mode 는 report / fix / auto-fix 중 하나입니다 (지금: nope)
convention-guard ✖ 건너뜀 — 내부 오류: <예외 한 줄>
```

- 아이콘은 가장 높은 강도의 것(F7 과 같은 규칙), 통과는 `✔` 입니다.
- `재검증 통과` 는 사용자가 사이클이 닫힌 것을 보도록 알림으로 냅니다.
- 보여 준 것은 고쳤지만 표시 예산 밖 error 가 남았으면 `재검증 통과` 가 아니라 `⚠ 재검증 종료 — … 미표시 N` 입니다. 그 후보는 다음 요청에서 "지난 턴에도 지적했습니다"로 다시 올라오고, 그 규칙은 세션 동안 조용해지지 않습니다.
- 차단 사유는 예산 밖을 숫자로 남깁니다: 규칙의 위치 아래 `… N곳 더`, 섹션 끝에 `… N개 규칙 더`.
- 여러 줄 오류(YAML 파싱)는 첫 줄만 쓰고 ` … — 전체: python3 "…/scripts/detect_stack.py"` 를 붙입니다.

### 4. scan.py 텍스트

```
convention-guard scan — 워킹 트리 · 파일 5개 · 스택 laravel, php · 규칙 23/23

■ 린터 실패 — 이번 변경 줄에서 확정 위반
  $ ./vendor/bin/phpstan analyse --no-progress …
    app/Svc/A.php:3  Undefined variable $x
    … 12줄 더
  = 참고: 기존 코드에 3건 더 — 차단 대상 아님

■ 지적
✖ error[core/php-no-debug-output]: 디버그 출력 잔여물
  app/Http/Controllers/UserController.php:22  dd($result);
  app/Legacy/OldController.php:7  var_dump($request->ip());
  = 안내: 디버그 출력이 남아 있습니다. 제거하고, 필요하면 Log 파사드로 남기세요.

✖ error[core/php-namespace-required]: 새 클래스 파일에 namespace 선언
  app/Http/Controllers/UserController.php  (새 파일에 해당 선언이 없음)
  = 안내: namespace 선언이 없습니다. PSR-4 오토로딩이 동작하려면 디렉터리 구조와 맞는
          namespace 가 있어야 합니다. 예) app/Services/Foo.php -> namespace App\Services;

■ 린터 참고 — 이번 변경 밖에서 찾은 것 (차단하지 않음)
  $ …

■ 자동 수정 — 3건 미리보기
  app/Svc/A.php:11  core/php-cast-spacing
    - $n = ( int )$v;
    + $n = (int)$v;

■ 검사 경고
⚠ 구조 미확인 2개 파일 — app/Svc/B.php, app/Svc/C.php (구조 조건을 적용하지 못해 후보를 그대로 올렸습니다)
⚠ 큰 파일 미검사 1개 파일 — app/Svc/Big.php (400KB 를 넘어 규칙을 적용하지 않았습니다)

■ 다음
- 자동 수정을 적용하려면:
  $ python3 "…/scripts/scan.py" --fix --write
- semantic 규칙 후보 1건은 판정하지 않았습니다. 판정하려면:
  $ python3 "…/scripts/scan.py" --review

✖ 15건 (error 8 · warn 5 · info 2)
```

- 지적이 없으면 `■ 지적` 없이 마지막 줄이 `✔ 지적 없음` 입니다.
- 린터 실패만 있으면 요약 줄 뒤에 ` · 린터 실패 1` 을 붙입니다: `✖ 0건 (error 0 · warn 0 · info 0) · 린터 실패 1`.
- `--fix --write` 는 `■ 자동 수정 — 3건 적용함 (아래 결과는 적용 후 남은 것)` 입니다.
- `--review` 에서 배치를 만들었으면 `■ 다음` 에 리뷰어 위임과 `$ … review.py show "<batch>"` 를 둡니다. 배치가 없는데 미룬 것이 있으면 `- 판정 대기 N건은 예산 때문에 미뤘습니다. 다시 실행하세요:` + `$ … scan.py --review` 입니다. `--review` 일 때는 "판정하지 않았습니다" 문장을 쓰지 않습니다.
- `■ 다음` 의 명령은 사용자가 준 범위 인자(`--range` 등)를 그대로 이어 받습니다.
- 설정·파이프라인 노트(config, 기각 파일, 스택, 린터 미실행)는 stderr `convention-guard: warn: …` 입니다(F12). 구조 엔진 없음·구조 미확인·큰 파일 미검사는 stdout 의 `■ 검사 경고` 에 나옵니다. 검사 불가는 `convention-guard: error: git 레포가 아닙니다: …` 입니다.

### 5. scan.py `--json`

```json
{
  "schema": "convention-guard/scan@1",
  "tool": {"name": "convention-guard", "version": "3.1.1"},
  "summary": {"total": 15, "error": 8, "warn": 5, "info": 2, "lint_failures": 0,
              "review_pending": 1, "exit_code": 1},
  "scope": {"root": "…", "label": "워킹 트리", "file_count": 5, "stacks": ["laravel", "php"],
            "rules_total": 23, "rules_applicable": 23, "semantic": 1},
  "findings": [{"rule_id": "core/php-no-debug-output", "severity": "error", "title": "…",
                "source": "core", "guidance": "…",
                "locations": [{"file": "app/…", "line": 22, "snippet": "dd($result);",
                               "key": "core/php-no-debug-output:app/…:5701b0e807"}]}],
  "lint": {"failures": [], "notes": []},
  "review": null,
  "fixes": [], "fixes_applied": false,
  "dismissed": 0,
  "unchecked": [],
  "too_large": [],
  "notes": [],
  "next": [{"text": "semantic 규칙 후보 1건 판정", "command": "python3 \"…/scripts/scan.py\" --review"}]
}
```

- 줄이 없는 후보(파일·변경 집합 단위)는 `"line": null` 입니다.
- `hash`, `context_hash` 필드는 `key` 로 대신합니다(지문은 키에 들어 있음).

### 6. 의미 판정

`review.py show` 는 리뷰어 에이전트에게 넘기는 **Markdown 문서**라서 Markdown 제목을 유지합니다(D2 B 의 단점으로 적었던 "Markdown 문서와 따로 논다"를 받아들인 결정). 대신 요소 모양은 공통 문법을 따릅니다.

```
# convention-guard review show — 후보 4건 · repo …

## ✖ error[core/layer-boundary]: 계층 경계 위반

#### 판정 기준
이번 변경이 추가한 import 가 계층 경계를 거스르는지 판단합니다.
…

### 후보 1 — app/Http/Controllers/OrderController.php:7
    use App\Models\User;

#### 후보 주변 (2-12줄)
 2| 
 …
12|     public function index()

#### import / use
 7| use App\Models\User;
 8| use App\Repositories\OrderRepository;

## 다음
판정을 모두 적어 한 번에 기록하세요:

(```bash 펜스) python3 "…/scripts/review.py" record "…/convention-guard.db#3f2a9c…" <<'JSON'
[{"id": 1, "verdict": "…", "reason": "…"}, …]
JSON
```

- 기록 명령은 들여 쓰지 않고 ` ```bash ` 펜스로 감쌉니다. 들여 쓴 `JSON` 줄은 heredoc 을 끝내지 못해 그대로 붙여 넣으면 명령이 깨지기 때문입니다(구현 중 결정, 2026-09-28).
- 같은 규칙의 VIOLATION 이 여럿이면 머리 하나 아래 위치 줄과 `= 이유:` 를 후보마다 둡니다(D5).

- 컨텍스트 절 줄 번호 폭은 절 안에서 같게 맞춥니다.
- 잘린 컨텍스트는 `… N줄 더 — 필요하면 Read` 입니다(F9).

`record`, `summary`:

```
convention-guard review record — 판정 4건 기록 · VIOLATION 2 · VALID 1 · FALSE_POSITIVE 1

■ 메인 에이전트에게 돌려줄 것 — VIOLATION 만
✖ error[core/layer-boundary]: 계층 경계 위반
  app/Http/Controllers/OrderController.php:7
  = 이유: 근거 1

⚠ warn[core/laravel-n-plus-one]: 반복문 안에서 관계 접근 (N+1)
  app/Http/Controllers/UserController.php:11
  = 이유: 근거 4
```

- VIOLATION 이 없으면 `■ 메인 에이전트에게 돌려줄 것` 아래 `✔ 위반 없음` 한 줄입니다.
- 기록 거부는 stderr `convention-guard: error: 기록하지 않았습니다 — 고친 뒤 전체를 다시 기록하세요` 다음 줄부터 `  - 판정이 빠진 후보: 2, 3, 4` 입니다.
- `show --json` 은 F15 봉투(`convention-guard/review-show@1`)입니다. 판정 배치·판정 캐시(상태 저장소 안)와 `firings.jsonl` 은 내부 형식이라 이 명세의 범위 밖입니다.

### 7. detect_stack.py

```
convention-guard detect_stack — … · mode fix · 스택 laravel, php

■ 설정
  config    .claude/convention-guard/config.yaml
  태그      laravel, php
  버전      laravel 11
  기각      0건 (.claude/convention-guard/dismissed.yaml)
  프리셋    ✔ architecture, common, laravel, php, psr12, security · ○ js, nest, next, performance, python, react

■ 린터
✔ ./vendor/bin/pint --test -v {files}
  = 참고: parse diff — 변경 줄만 차단
○ ./vendor/bin/phpstan analyse --no-progress --error-format=raw {files}
  = 참고: 설치 안 됨 — 건너뜀

■ 규칙 — 34개 중 15개 적용
  상태  강도   규칙                                      출처         사유
  ────  ─────  ────────────────────────────────────────  ───────────  ───────────────────────
  ✔ on  error  core/laravel-controller-needs-validation  core
  ✔ on  warn   core/php-no-debug-output                  core<-local  override, error->warn
  ○ off error  core/php-no-closing-tag                   core         superseded by pint.json
```

- 설정이 없으면 `config    (없음 — 기본값)`, 스택이 없으면 머리말 `스택 감지 실패`.
- 설정 노트는 stderr 로 옮깁니다(F12). 종료 코드는 지금처럼 error 노트가 있으면 2 입니다.
- `--json` 은 `convention-guard/detect-stack@1` 봉투, 본문 필드는 지금 이름을 유지하고 `severity_changed` 는 `"error->warn"` 입니다.

### 8. log_report.py

```
convention-guard log_report — 이벤트 7 · 로그 …/firings.jsonl

■ 규칙 건강도
  규칙                       강도   후보  고침  남음  기각  새로 생김  수정률  정밀도  판정
  ─────────────────────────  ─────  ────  ────  ────  ────  ─────────  ──────  ──────  ──────────
  core/php-no-debug-output   error     2     1     1     0          0     50%       -  데이터 부족
  = 참고: * = 의미 판정 규칙. 정밀도 = 리뷰어가 VIOLATION 으로 판정한 비율

■ 의미 판정
  (같은 표 모양: 규칙 · 판정 · VIOLATION · VALID · FALSE_POSITIVE · 게이트 오탐률)
  = 참고: VALID = 게이트는 적절했고 코드가 정상 / FALSE_POSITIVE = 게이트가 잘못 잡음

■ 손볼 규칙 — 2개
⚠ core/no-orphan-todo — 오탐 확정 — 팀이 기각함, 조건을 좁히세요
  = 참고: 자주 걸린 파일 app/Svc/A.php, app/Svc/B.php
  = 이유: 기각 사유 — 테스트 픽스처

■ 린터
  (표: 명령 · 실패 · 그중 차단 · 출력 파싱 성공)
  = 참고: 파싱 성공이 실패보다 적은 린터는 변경 줄로 좁혀지지 않아 출력 전체로 차단합니다 — stacks/*.yaml 의 parse 를 확인하세요.
```

- 로그가 없으면 머리말 `convention-guard log_report — 이벤트 0 · 로그 …` 다음 `ℹ 읽을 이벤트가 없습니다 — 훅이 아직 돌지 않았거나 CLAUDE_PLUGIN_DATA / userConfig log_dir 경로가 다릅니다`. `--json` 이면 빈 봉투입니다.
- 머리말에 `0.x 이벤트 N 제외` 를 속성으로 붙입니다.
- `--json` 은 `convention-guard/log-report@1` 봉투, 본문 필드 이름은 유지합니다.

### 9. readiness.py

```
convention-guard readiness — … · 플러그인 3.1.1 · 0초

✖ fail    B5  semantic_review='maybe' 는 참/거짓으로 읽히지 않아 기본값이 쓰입니다
              = 조치: /plugin 설정에서 true 또는 false 로
⚠ warn    B1  convention-guard@team-market — 이 레포에 적용되는 설치 user:3.0.1 (마켓플레이스 최신 3.1.1)
              = 조치: /plugin 에서 업데이트하세요 — 설치본이 최신이 아닙니다
✔ pass    A1  python3 = 3.12.3

  fail  warn  manual  skip  pass
  ────  ────  ──────  ────  ────
     4    11       0     0    12
```

- 항목 줄: `<아이콘> <상태 6칸>  <id 3칸> <내용>`. 보조 줄은 내용 시작 칸에 맞춥니다.
- 여러 줄 내용(YAML 오류)은 첫 줄만 쓰고 `… N줄 더` 를 붙입니다.
- `--json` 은 `convention-guard/readiness@1` 봉투, `summary` 에 상태별 개수, `items` 는 유지합니다.

### 10. dismiss.py

```
convention-guard dismiss — 1건 기록 · .claude/convention-guard/dismissed.yaml

✔ core/php-no-debug-output
  app/Svc/A.php:8  public function f() { dd(1); }
  = 참고: 키 core/php-no-debug-output:app/Svc/A.php:5701b0e807

■ 다음
- 이 코드가 바뀌면 다시 지적됩니다. dismissed.yaml 을 커밋해 팀과 공유하세요.
```

- 이미 기록됨: 머리말 `— 이미 기록됨 · …`, 항목 아이콘 `ℹ`.
- 파일 전체: 위치 줄 `app/Svc/B.php  (파일 전체)`. `--key` 로 기록해 줄을 모르면 위치 줄은 `app/Svc/A.php` 입니다.
- 한 파일에 여러 곳, 위치 없음, 잘못된 키 같은 입력 오류는 stderr `convention-guard: error: …` 입니다. 후보 목록이 필요하면 그 아래 위치 줄(F4)로 씁니다.
- 같은 코드가 파일에 여러 곳 있으면 지문 하나가 모두 가리므로 `--all-identical` 없이는 같은 오류 형식으로 거부하고 그 위치들을 나열합니다. `--all-identical` 로 기록하면 `= 참고: 같은 코드 N곳이 함께 가려집니다` 가 붙습니다.

`--list`:

```
convention-guard dismiss --list — .claude/convention-guard/dismissed.yaml · 3건

  규칙                      파일           지문        누가   날짜        이유
  ────────────────────────  ─────────────  ──────────  ─────  ──────────  ─────────────
  core/php-no-debug-output  app/Svc/A.php  5701b0e807  agent  2026-09-28  디버그 도구
  core/php-no-debug-output  app/Svc/B.php  파일 전체   human  2026-09-28  시드 스크립트
```

기록이 없으면 `· 0건` 머리말 다음 `ℹ 기각 기록이 없습니다`.

### 11. setup.py

```
convention-guard setup init — .claude/convention-guard/config.yaml 씀

■ 다음
- 적용 규칙을 확인하세요:
  $ python3 "…/scripts/detect_stack.py"
- 최근 변경분을 측정하세요:
  $ python3 "…/scripts/scan.py" --range HEAD~20..HEAD
```

```
convention-guard setup emit — 규칙 24개 · 파일 4개

■ 쓴 파일
  .claude/rules/convention-common.md
  .claude/rules/convention-php.md

■ 다음
- paths: 프론트매터가 붙은 파일은 그 경로의 파일을 읽을 때 컨텍스트에 들어갑니다. 커밋해 팀과 공유하세요.
```

- `init` 이미 있음: stderr `convention-guard: error: 이미 있습니다: … (덮어쓰려면 --force, 미리보기는 --stdout)`, 종료 1.
- `init --stdout` 은 파일 내용 그대로, `emit --stdout` 은 파일마다 `===== <경로> =====` 머리 줄 뒤에 내용입니다.
- `emit` 이 쓰는 `.claude/rules/*.md` 는 에이전트 컨텍스트에 들어가는 Markdown 파일입니다. 규칙 줄을 `- **error** \`core/x\` 제목 — 안내` 로 바꿔 강도와 id 를 드러냅니다. 제목·관리 블록 주석은 유지합니다. `init` 이 쓰는 `config.yaml` 주석은 범위 밖입니다.

## 범위 밖 발견 (제안)

형식이 아니라 동작 문제입니다. 이번 작업에서는 고치지 않고 끝에 제안 목록으로 남깁니다.
4.0 기준: 1·3 은 migrate 삭제로, 5 는 readiness 의 옛 디렉터리 점검 삭제로 없어졌고, 6 은 4.0 에서 고쳤습니다 (훅의 `검사 경고`).

1. migrate: 흐름 스타일(`no_match: ['…']`) 규칙에 블록 항목을 덧붙여 YAML 이 깨짐 (`lib/migrate.py:564`)
2. dismiss: 워킹 트리의 다른 파일에 후보가 있으면 파일 전체 폴백을 건너뜀 (`dismiss.py:59`)
3. migrate `--rules-dir`: 0.x 규칙에 `변환`과 `실패`를 함께 출력하고, 쓰지 않는다고 한 뒤 씀
4. setup emit·init 개수에 superseded 규칙이 포함됨 (detect_stack 은 제외)
5. readiness: C1 FAIL 뒤에도 C4·D2 점검이 계속됨. 옛 디렉터리와 새 디렉터리가 같이 있으면 legacy FAIL 이 없음
6. Stop 훅: config `warn` 노트(알 수 없는 키)가 훅 출력에 전혀 나오지 않음 (hooks.py:252)
7. Stop 훅: report 모드에서 판정 대기만 있을 때 `error 0건` 으로 셈
8. 차단이 아닌 알림이 에이전트에게는 보이지 않음 — `hookSpecificOutput.additionalContext` 를 쓰면 전달할 수 있음 [17]

## 근거 출처

1. GNU Coding Standards, Errors — https://www.gnu.org/prep/standards/html_node/Errors.html
2. Command Line Interface Guidelines — https://clig.dev/
3. ruff 스냅샷 테스트(`crates/ruff/tests/cli/snapshots/`), `crates/ruff/src/printer.rs`; rustc dev guide — https://rustc-dev-guide.rust-lang.org/diagnostics.html
4. ESLint formatters 문서와 `lib/cli-engine/formatters/stylish.js`; stylelint `lib/formatters/stringFormatter.mjs`
5. mypy 명령행 문서 — https://mypy.readthedocs.io/en/stable/command_line.html, `mypy/errors.py`, `mypy/util.py`; GCC Diagnostic Message Formatting Options
6. golangci-lint `pkg/printers/text.go`, `pkg/exitcodes/exitcodes.go`
7. GitHub Actions workflow commands — https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands
8. SARIF 2.1.0 — https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/sarif-v2.1.0-errata01-os-complete.html
9. shellcheck man page
10. Pyright `--outputjson` 문서
11. git `wt-status.c` (status 안내)
12. RuboCop formatters (`simple_text_formatter.rb`, JSON formatter)
13. npm audit 문서
14. flutter `doctor_validator.dart`, `doctor.dart`; Homebrew `cmd/doctor.rb`, `utils/output.rb`
15. cargo `src/compiler/job_queue/mod.rs`
16. Anthropic, Writing effective tools for agents — https://www.anthropic.com/engineering/writing-tools-for-agents
17. Claude Code hooks reference — https://code.claude.com/docs/en/hooks.md
18. GitLab Code Quality report format 문서
19. NO_COLOR — https://no-color.org/

## 결정 사항

| 항목 | 결정 | 날짜 |
|---|---|---|
| D0 | A — migrate.py 는 범위 밖 | 2026-09-28 |
| D1 | A — `convention-guard <명령> — 대상 · 속성` 한 줄 | 2026-09-28 |
| D2 | **B** — 섹션 제목은 `■ 제목`. Markdown 문서인 review show 와 emit 파일은 Markdown 제목 유지 | 2026-09-28 |
| D3 | A — `파일:줄`, 파일 단위는 `파일`, 지문은 키로만 | 2026-09-28 |
| D4 | A — `error` / `warn` / `info`, 줄 맨 앞 | 2026-09-28 |
| D5 | A — 규칙으로 묶음 `error[규칙]: 제목` + 위치 줄 | 2026-09-28 |
| D6 | A — `= 안내:` / `= 참고:` / `= 이유:` / `= 조치:` | 2026-09-28 |
| D7 | A — `■ 다음` 섹션 + `$ 명령` 줄 | 2026-09-28 |
| D8 | **B** — ESLint 식 `✖ 15건 (error 8 · warn 5 · info 2)` | 2026-09-28 |
| D9 | A — 상태 단어 (아이콘은 D17 결정에 따름) | 2026-09-28 |
| D10 | A — 자르는 곳마다 `… N줄 더` | 2026-09-28 |
| D11 | A — systemMessage = reason 머리말 한 줄 | 2026-09-28 |
| D12 | A — 공통 JSON 봉투 | 2026-09-28 |
| D13 | A — 용어 표대로 | 2026-09-28 |
| D14 | A — `convention-guard: error: 문장` | 2026-09-28 |
| D15 | 보류 — 사용자 요청(아이콘·색·표로 가독성 향상)으로 D17~D19 로 다시 설계 | 2026-09-28 |
| D16 | A — 현행 0/1/2 를 문서로 고정 | 2026-09-28 |
| D17 | A — 단색 유니코드 기호 + 단어, `TERM=dumb` 면 ASCII | 2026-09-28 |
| D18 | A — 의미색, TTY 에서만 | 2026-09-28 |
| D19 | A — 짧은 열의 목록만 정렬 표, 한글 폭 보정 | 2026-09-28 |
| 빈 결과 | `✔ 지적 없음` (D8 B 의 ESLint 원형은 침묵) | 2026-09-28 |

사용자 요청 (2026-09-28, D17~D19 는 "전부 A"): "사용자에게 보이는 텍스트의 경우 좀 더 가독성 좋게 바꿀 수 없어? 아이콘이나 색을 넣는다던가 표로 표현하던가 하는 방식으로"

## 구현 체크리스트

- [x] 명세 확정 (2026-09-28)
- [x] 형식 검증 테스트 작성 — `tests/helpers/outfmt.py`(F1~F16 검사), `tests/integration/test_output_format.py`(17개 시나리오). 현재 코드에서 97건 실패 확인 (2026-09-28)
- [x] 코드 수정 계획 승인 (2026-09-28)
- [x] 1. `scripts/lib/fmt.py` — 공통 문법 렌더러 (아이콘·색·ASCII 대체, 머리말, 섹션, 항목, 보조 줄, 다음, 요약, 표, 잘림, stderr, JSON 봉투)
- [x] 2. Stop 훅 — `lib/report.py`(hook_reason, verify_reason, review_section, autofix_section, clip_reason), `lib/hooks.py`(systemMessage, 재검증 통과 알림)
- [x] 3. scan.py — 텍스트, `--json` 봉투, `--fix`, `--review`, stderr (`lib/report.py` render_text, `lib/autofix.py` diff)
- [x] 4. 의미 판정 — `review.py` show/record/summary, `lib/context.py`(절 제목·줄 번호 폭·잘림), show `--json`
- [x] 5. detect_stack.py
- [x] 6. log_report.py
- [x] 7. readiness.py
- [x] 8. dismiss.py
- [x] 9. setup.py (init, emit 안내, `.claude/rules/*.md` 규칙 줄)
- [x] 10. 옛 형식을 기대하는 기존 테스트 수정
- [x] 11. 패리티 골든 갱신 — 파일 단위 후보 9건의 `:1` 이 빠짐, 지적 결과는 같음 (계획 때 센 11건 중 blade 2건은 실제 1번 줄 지적이라 그대로)
- [x] 12. docs/, skills/, README 의 출력 예시와 JSON 필드 설명 수정
- [x] 13. 전체 테스트 두 번 (PyYAML 있음/없음) 통과 — 33개 스위트 (2026-09-28)
- [x] 산출물별 before/after 최종 승인 (2026-09-29)
- [ ] 커밋
