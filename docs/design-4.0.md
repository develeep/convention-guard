# convention-guard 4.0.0 설계

상태: **구현 완료** (2026-10-02, 단계 1~5) · 기준 커밋 `dcf6511` (3.3.0) · 진행 기록: [4.0-progress.md](4.0-progress.md) · 구현 중 바뀐 것: §11

> 2026-10-01 사용자 결정으로 핵심 4 에서 "Stop 60ms" 예산을 뺐다. 성능은 §7 의 목표다.

## 0. 지키는 것과 바뀌는 것

### 핵심 (모든 설계·구현의 조건)

1. Claude Code 플러그인이다. 훅이 에이전트의 작업을 지켜보다가 팀 컨벤션 위반을 차단하고, 수정 → 재검증 사이클을 돌린다.
2. 이번 변경분만 검사한다. 에이전트가 쓴 줄에만 반응하고, 원래 있던 레거시 위반에는 반응하지 않는다.
3. 훅은 자기 버그가 나도 에이전트를 깨뜨리지 않는다. 다만 읽지 못한 것을 통과로 처리하지 않는다.
4. 판정할 것이 없으면 AI 호출은 0이다 (판정할 것은 정규식 게이트를 통과한 후보와, `when_code_added` 규칙의 글롭에 든 파일에서 에이전트가 의미 있는 줄을 추가한 판정 단위뿐이다. 캐시에 판정이 있는 것은 다시 묻지 않는다).

> 3.x 의 "Stop 60ms(파일 60개, 후보 0건)" 예산은 4.0 에서 핵심이 아니다(2026-10-01 사용자 결정). 성능은 §7 의 **목표**로만 둔다.

### 3.x 에서 그대로 가져가는 결정

| 결정 | 이유 |
|---|---|
| 범위 객체(ChangeScope) 하나 + `pipeline.run` 하나를 훅·CLI·CI 가 공유 | 수동 실행과 훅 실행이 다르게 판단할 수 없다 |
| 앵커 (`when_line_added` 등) | "이번 변경의 책임"을 규칙이 선언한다 — 핵심 2 의 규칙 수준 표현 |
| 후보 ≠ 위반, 구조 조건은 **필터** | 구조가 후보·스니펫·지문을 바꾸지 않는다 |
| 후보 키 `규칙:파일:코드지문` (줄 번호 없음, 줄 전체 공백 정규화 sha1 10자리) | 기각과 사이클이 줄 이동을 견딘다 |
| 조건부 의미 판정 + `review_hash` 캐시 + 메인 에이전트를 통한 서브에이전트 위임 | 핵심 4 를 지키는 가장 단순한 방법 |
| 진입점은 인자·입출력만, 결정은 `scripts/lib/` | 제약 사항 |

### 끊는 것 (하위 호환 없음)

- 이전 버전의 기록을 읽지 않는다: `dismissed.yaml`(버전 표시 없는 파일), `verdicts.json`, 세션 상태 파일 여섯 종류, 1.x·3.2 형식. 이관 도구·이관 문서를 만들지 않는다.
- 제거: Go 규칙·프리셋·스택, `scripts/migrate.py`·`lib/migrate.py`, 3.2 지문 별칭(`legacy_hashes`·`aliases`), 판정 배치 v1, `docs/migration-*.md`, 14개 언어 중 지원 대상이 아닌 언어 정의, 내장 블록 트리(`structure/native/`), `scope.base_ref` 설정(§1.7), `collect.edit_tools` 설정(§1.4).
- 3.x 데이터 디렉터리의 옛 파일(`session-*`, `touched-*`, `base-*`, `bash-*`, `foreign-*`, `bashmiss-*`, `verdicts.json*`, `cache-yaml.json`, `reviews/`)은 4.0 이 처음 돌 때 한 번 지운다. 플러그인 내부 상태이고 4.0 이 읽지 않으므로 남겨 둘 이유가 없다.

---

## 1. 편집 사건 원장 (범위 1)

### 1.1 무엇이 바뀌나

3.x 는 Stop 시점에 `git diff` 로 추가된 줄 전체를 구하고, 에이전트가 쓰지 않은 줄(foreign)을 **공백 무시 텍스트 지문별 개수**만큼 뺐다. 4.0 은 줄의 출처를 **편집 사건마다** 기록하고, Stop 은 기록된 출처를 읽기만 한다. foreign 줄, 개수 차감(`without_lines`), baseline 기록, 세션 base 대비 diff 가 모두 사라진다.

### 1.2 모델

원장은 세션 × 레포 루트 × 파일마다 **마지막으로 아는 내용 K** 와 **줄마다의 출처**를 가진다.

| 출처 | 기호 | 뜻 | 검사 |
|---|---|---|---|
| pre | `p` | 원장이 그 파일을 처음 볼 때 이미 있던 줄 (커밋됐든 사람이 미리 써 둔 미커밋 줄이든) | 안 함 |
| agent | `a` | 에이전트 도구 호출의 관찰 구간(Pre → Post) 안에서 생긴 줄 | **함** |
| other | `o` | Bash 호출이 HEAD 를 옮기며 남의 커밋이 들여온 줄 | 안 함 |
| unknown | `u` | 관찰 구간 **밖**에서 바뀐 줄 (사람의 에디터, 포매터 저장, 백그라운드 프로세스, 관찰되지 않은 도구) | 안 함 (§2 에서 이름 붙여 알림) — **결정 D1** |

그 밖에 줄마다 "이 줄 뒤에서 에이전트가 줄을 지웠다"는 **이음매(seam) 표시**를 둔다(대문자 `P/A/U/O`, 첫 줄 앞은 파일 플래그). 3.x 의 seams 와 같은 역할(빈 블록 만들기, 테스트 줄이기 같은 삭제만의 변경)을 하지만, 에이전트가 지운 것만 표시한다.

파일 단위로는 `created_by_agent`(원장이 처음 볼 때 없던 파일을 에이전트가 만들었다 — `absent` 앵커의 "새 파일"), `too_large`, `binary` 를 둔다.

### 1.3 출처를 잇는 연산

`apply(K, C, label)`: 이전 내용 K 와 새 내용 C 를 줄 단위로 정렬해 출처를 잇는다.

1. 공통 접두·접미를 먼저 잘라 낸다 (편집은 대개 국소적이라 대부분 여기서 끝난다).
2. 가운데만 `difflib.SequenceMatcher(autojunk=False)` 로 정렬한다.
3. `equal` 은 출처를 그대로 옮긴다. `insert`·`replace` 의 새 줄은 `label` 이다. 단, **같은 사건 안에서 지워진 줄과 텍스트가 똑같은(끝 공백·CRLF 제외) 새 줄은 지워진 줄의 출처를 이어받는다** — 파일 안에서 줄을 옮긴 것, Bash `mv` 로 파일을 옮긴 것은 쓴 것이 아니다. 공백만 바뀐 줄은 이어받지 않는다(들여쓰기 규칙이 있으므로). 에이전트가 돌린 포매터가 바꾼 줄은 에이전트 줄이다.
4. `label == a` 의 `delete` 는 이음매를 남긴다.

내용 읽기는 3.x `read_text` 와 같다: `utf-8-sig`, CRLF → LF, 외톨이 CR 유지, 앞 8KB 에 NUL 이면 바이너리, 400KB 초과는 `too_large`.

### 1.4 사건별 동작

수집 훅은 두 가지 관찰 방식만 쓴다.

**파일 관찰** — `Write|Edit|MultiEdit|NotebookEdit` (도구 입력에 경로가 있음)

| 훅 | 동작 |
|---|---|
| PreToolUse | 경로마다: 원장에 없으면 현재 내용을 K 로 기록(전부 `p`, 없으면 "없음"). 원장에 있고 stat(mtime_ns, size) 이 다르면 현재 내용으로 `apply(K, C, u)`. 사건 행(`tool_use_id`, 경로, 시작 시각)을 **열린 상태**로 남긴다 |
| PostToolUse, PostToolUseFailure | 경로마다 `apply(K, C, a)`. 사건을 닫는다 |

**작업 트리 관찰** — `Bash` 와 `mcp__.*` (어떤 파일을 바꿀지 모름)

| 훅 | 동작 |
|---|---|
| PreToolUse | `git status --porcelain=v2 -z --untracked-files=all` 한 번 + HEAD. 원장 파일은 stat 를 대조해 다르면 `u` 로 맞춘다. 원장에 없는 dirty 파일은 내용을 `p` 로 기록한다(세션당 파일마다 한 번). 사건 행에 dirty 집합의 stat 와 HEAD 를 남긴다 |
| PostToolUse, PostToolUseFailure | 다시 `git status` + HEAD. 바뀐 파일마다 기준 내용(원장 K → 없으면 Pre 시점 HEAD 의 blob → 없으면 "없음")에서 `apply(·, C, a)`. HEAD 가 움직였으면 아래 1.5 |

- 실패한 도구도 파일을 바꿀 수 있으므로(중간에 죽은 Bash) **PostToolUseFailure 를 Post 와 똑같이** 다룬다.
- MCP 도구는 이름으로 거르지 않고 모두 작업 트리 관찰로 본다. 3.x 의 `collect.edit_tools` 설정이 없어지고, 이름을 등록하지 않은 MCP 편집 도구가 조용히 빠지는 구멍(architecture.md:170)이 사라진다. 대가는 읽기 전용 MCP 호출에도 `git status` 두 번이 드는 것이다(§7 에서 측정).
- 병렬 호출: 사건마다 `tool_use_id` 로 Pre 와 Post 를 짝짓는다. 겹치는 두 구간에서 생긴 변경은 어느 쪽이든 `a` 이므로 결과가 같다. 관찰 구간 안에서 사람이 같은 파일을 고치면 `a` 가 된다 — 구간이 도구 실행 시간뿐이라 받아들인다.
- 저장소는 sqlite(§3) 이고 사건마다 `BEGIN IMMEDIATE` 트랜잭션 하나다. 3.x 의 덧붙이기 파일·O_EXCL·찢어진 쓰기 대비가 필요 없다.

### 1.5 HEAD 가 움직인 Bash (pull, merge, checkout, rebase, commit)

- 커밋만 한 경우(`git commit`): 작업 트리 내용이 그대로라 출처도 그대로다. 세션 중 커밋한 변경이 따로 처리할 필요 없이 계속 검사된다.
- 남의 커밋을 들여온 경우: 3.x 와 같은 판별을 쓴다 — `old..new` 중 **호출 시작 전에 만들어진 비머지 커밋**이 추가한 줄의 텍스트 다중집합을 구하고, 그 사건에서 `a` 가 될 새 줄 가운데 그 텍스트와 맞는 줄을 개수만큼 `o` 로 바꾼다. 개수 차감이 남는 곳은 이 한 사건의 새 줄 안뿐이다(3.x 는 세션 전체의 추가 줄에 적용했다).
- 작업 트리에서 dirty 가 아니었지만 HEAD 이동으로 내용이 바뀐 파일은 `git diff --name-only old new` 로 찾는다.

### 1.6 Stop 이 범위를 만드는 법

```
1. 열린 사건 정리 (§2)
2. 원장 파일마다 stat 대조 → 다르면 apply(K, C, u)        ← 파일을 다시 읽는 건 바뀐 것만
3. OwnedScope:
     changed[f]  = [(lineno, text) for 출처 == a]
     seams[f]    = 에이전트 이음매
     new_files   = created_by_agent 이면서 지금 있는 파일
     too_large   = 400KB 초과로 읽지 않은 파일 (3.x 와 같이 이름 붙임)
   .gitignore 에 걸린 파일은 뺀다 (git check-ignore --stdin 한 번)
4. pipeline.run(scope)   ← 3.x 와 같음. 파일 본문은 원장의 K 에서 읽는다
```

Stop 의 git 프로세스는 `git status` 한 번(§2 의 출처 미확인 감지), `check-ignore` 한 번, 사이클 재검사 때도 같다. 파일마다 git 을 띄우지 않는다.

### 1.7 CLI 범위와 `scope.base_ref`

`scan.py` 의 `--staged`/`--range`/`--files`/`--all`/기본(작업 트리)은 git 기반 그대로다(원장은 훅 전용). 3.x 의 `scope.base_ref`(훅 범위에 브랜치 변경까지 합치기)는 원장 모델과 맞지 않아 **제거**한다. 같은 일은 `scan.py --range <base>..HEAD` 로 한다.

### 1.8 3.x 오귀속 경로가 어떻게 되는가 (architecture.md:159-171)

| 3.x 경로 | 4.0 |
|---|---|
| 에이전트가 처음 건드린 뒤 사람이 같은 파일에 쓴 줄 → 에이전트 것으로 검사 | 다음 Pre 또는 Stop 에서 `u` — 검사 안 함, 이름 붙임 |
| 포매터가 다시 쓴 사람 줄 → 에이전트 것 | 사람이 돌린 포매터(에디터 저장)는 `u`. 에이전트가 돌린 포매터가 바꾼 줄은 `a` (에이전트가 만든 변경) |
| 기준선 없이 Post 만 온 편집 | `a` 로 검사하고 "Pre 없음" 으로 이름 붙임 (§2) |
| 수집 훅이 예산 안에 끝나지 못한 편집 → 검사 안 됨 | Pre 만 있는 사건 → `a` 로 검사하고 "Post 없음" 으로 이름 붙임 |
| Pre 없이 Post 만 온 Bash → 검사 안 됨 | Pre 시점 기준 내용을 HEAD blob·원장으로 대신하고 `a` 로 검사, "Pre 없음" |
| `collect.edit_tools` 에 없는 MCP 편집 도구 → 검사 안 됨 | 모든 MCP 호출을 작업 트리 관찰로 본다 |
| 남의 커밋과 똑같은 줄을 같은 Bash 호출에서 씀 → 검사 안 됨 | **남는다.** 그 한 사건 안으로 좁아질 뿐이다. 문서에 한계로 적는다 |

---

## 2. 관찰 누락 알림 (범위 2)

Stop 은 원장을 보고 다음을 **이름 붙여** 알린다. 알림은 차단 사유(reason)가 아니라 `systemMessage` 의 ` · ` 뒤 항목이고, 차단할 때도 함께 붙는다(3.x 형식 명세를 따른다).

| 이름 | 감지 | 검사 | 알림 예 |
|---|---|---|---|
| **Post 없음** | 열린 채 남은 사건(Pre 만 기록됨). Stop 이 그 파일들(작업 트리 관찰이면 dirty 집합)을 Pre 시점과 대조 | 바뀐 줄을 `a` 로 보고 **검사함** | `관찰 누락 2회 — 실행 후 기록 없음 (app/A.php 외 1개, 에이전트 변경으로 보고 검사)` |
| (바뀐 것 없는 열린 사건) | 위와 같고 내용이 그대로 | — | 알리지 않음 (권한 거부·PreToolUse 차단으로 실행되지 않은 도구) |
| **Pre 없음** | 짝이 되는 열린 사건 없이 온 Post | `a` 로 검사함 | `관찰 누락 1회 — 실행 전 기록 없음 (b.ts, 그 사이 다른 변경과 구분 못 함)` |
| **출처 미확인 변경** | (1) 원장 파일이 관찰 구간 밖에서 바뀜(`u`), (2) 원장에 없는 파일이 지난 Stop 이후 새로 dirty 가 되거나 바뀜 (`git status` 의 stat 를 세션에 기억해 두고 대조) | 검사 안 함 (D1) | `출처 미확인 변경 3개 파일 — 에이전트 도구 밖에서 바뀜, 검사 안 함 (README.md 외 2개)` |
| **수집 훅 오류** | 수집 훅이 자기 예외를 원장의 오류 행에 남김 | — | `수집 훅 오류 1회 (internal_error:OSError)` |
| **원장 없음/손상** | Stop 이 DB 를 열지 못함, 스키마 불일치 | 검사 불가 | `✖ 검사 불가 — 상태 저장소를 열 수 없음` |
| 큰 파일 / 레포 밖 파일 | 3.x 와 같음 | 안 함 | 3.x 와 같음 |
| 구조 엔진 없음 / 구조 미확인 | §4 | §4 | §4 |

- 출처 미확인의 (2) 는 같은 변경을 한 번만 알린다(Stop 마다 기억한 stat 를 갱신). 사람이 옆에서 같이 일하면 매 턴 한 줄이 붙는다.
- 3.x 의 "Bash 변경 미수집 N회"는 "Pre 없음" 으로 합쳐진다.
- 수집 훅은 여전히 출력이 없고 종료 코드 0 이다(컨텍스트 0). 오류를 stderr 대신 원장에 적어 Stop 이 말하게 한다. 원장에 적는 것조차 실패하면 stderr 뿐이다 — 그 경우 다음 Stop 이 DB 를 열지 못해 "검사 불가" 가 되거나, 열린 사건이 "Post 없음" 으로 드러난다.

> **결정 D1 — `u`(출처 미확인) 줄을 검사할 것인가.**
> 권장: **검사하지 않고 이름만 붙인다.** 이유: 사람이 에이전트와 같은 파일을 동시에 고치는 것은 흔하고, 그 줄을 지적하는 것이 3.x 의 가장 큰 오귀속(핵심 2 위반)이었다. 관찰되지 않은 도구는 4.0 에서 MCP 를 모두 관찰하므로 `u` 의 주된 출처가 사람·에디터·백그라운드 프로세스가 된다. 이름을 붙이므로 "통과처럼 보임"(핵심 3)도 아니다.
> 대안: `u` 를 `a` 처럼 검사한다 (`ledger.unknown: check` 설정 하나로 켤 수 있게). 놓침은 줄지만 사람 줄을 지적한다.

---

## 3. decide() + sqlite3 (범위 3)

### 3.1 저장소

하나의 파일 `${CLAUDE_PLUGIN_DATA}/convention-guard.db` (환경 변수가 없으면 3.x `paths.data_dir()` 규칙). 표준 라이브러리 `sqlite3`, WAL, `busy_timeout=5000`, `synchronous=NORMAL`.

| 테이블 | 대신하는 3.x 상태 |
|---|---|
| `meta(key, value)` — 스키마 버전 | — |
| `session(session, root, observed_dirty, collect_policy, updated)` | `base-*.json` |
| `ledger_file(session, root, path, exists, content(zlib), origins, sig, created_by_agent, flags)` | `touched-*.txt`, `foreign-*.jsonl` |
| `ledger_event(session, tool_use_id, tool, kind, started, head, pre_dirty, state, files)` | `bash-*-*.json`, `bashmiss-*.txt` |
| `observe_issue(session, kind, detail, at)` | 수집 훅 오류(신규) |
| `cycle_state(session, state_json, updated)` | `session-*.json` |
| `verdict(root, review_key, verdict, reason, rule_id, at)` | `verdicts.json` + 직접 만든 잠금 |
| `review_batch(id, session, root, created, body_json)`, `review_verdict(batch_id, review_key, body_json)` | `reviews/*.json`, `*.verdicts.json` |
| `parse_cache(path, sig, value_json)` | `cache-yaml.json` |

- 스키마 버전이 다르면(앞으로의 4.x 변경) 데이터 테이블을 지우고 다시 만든다. 플러그인 내부 상태는 이관하지 않는다는 4.0 의 원칙을 앞으로도 쓴다. **팀 기록(`dismissed.yaml`)은 DB 에 넣지 않는다** — 커밋되는 레포 파일이다.
- 발동 로그 `firings.jsonl` 은 상태가 아니라 로그(사용자 `log_dir` 로 옮길 수 있고 `log_report.py` 가 읽음)라서 JSONL 로 둔다.
- GC: Stop 이 7일 지난 세션 행을 한 문장으로 지운다. 판정 TTL 은 조회 조건이다.
- 판정 배치: 리뷰어 서브에이전트는 `review.py show <배치 id> --db <절대 경로>` / `record` 로 읽고 쓴다(3.x 는 배치 파일 경로를 넘겼다). 배치에는 3.x 처럼 레포·로그 경로를 넣는다.

### 3.2 decide()

사이클 전이를 순수 함수 하나로 모은다. 3.x 에서 `_stop`·`_verify`·`_open`·`_close` 와 플래그 다섯 개에 흩어진 판단이 여기로 온다.

```python
decide(state: CycleState, obs: Observation, limits: Limits) -> Decision
Decision = (next_state: CycleState, action: Action, events: list[LogEvent])
```

- **CycleState** (불변 값): `Idle(request, streak, settled_rules, unresolved, closed_in_request)` | `Open(request, cycle_id, attempt, opened, seen, review, streak, settled_rules)`
- **Observation** (셸이 만든 값): 요청 식별(`prompt_id`, `stop_hook_active`), 설정 오류, 질문으로 끝난 턴인지, 검사 결과 요약(`current: {key: entry}`, 린터 미확인 키, 표시 예산을 적용한 후보 목록, 의미 판정 대기/질문함/실행됨), 새 배치 id(셸이 미리 만든 값 — decide 는 I/O 를 하지 않는다), 시각.
- **Action**: `Silent` | `Notice(kind, parts)` | `Block(model)` | `RequestReview(items) + Block(model)`. 문구는 decide 가 만들지 않는다. `report.py` 가 Action 을 형식 명세(`docs/output-format.md`)대로 문자열로 바꾼다.
- 분류(`classify`: fixed/dismissed/still/new, `_pair_moves`)는 decide 안의 순수 보조 함수다. 3.x 처럼 분류 단계가 사이클 상태를 고치는 일(`_classify` 가 `opened` 에 끼워 넣기)은 decide 의 명시적 전이로 바뀐다.

셸(`lib/stop.py`): DB 에서 상태 읽기 → 범위·파이프라인·트리아지 → Observation → `decide` → 같은 트랜잭션에서 상태 저장 + 배치 저장 → 로그 이벤트 기록 → 출력 렌더링. 자동 수정(`mode: auto-fix`)은 decide 전에 셸이 한다.

테스트: decide 는 **표 테스트**(상태 × 관찰 → 다음 상태 × 행동)로 검증한다. 3.2 리뷰의 R3·R4·R17 같은 전이 결함을 한 행씩 고정한다. 기존 `test_hook_cycle.py` 의 턴 시나리오는 종단 테스트로 남긴다.

---

## 4. tree-sitter 구조 엔진 (범위 4)

### 4.1 엔진 선택

**py-tree-sitter + 언어별 문법 휠.** 근거: 참고 자료 29/29 정확도, 임포트 ~16ms·1,000줄 파싱 ~4ms, 지원 대상 세 언어 계열의 문법 휠이 모두 있음, 노드 종류 대응표만으로 언어를 정의할 수 있음.

| 고정 버전 | 비고 |
|---|---|
| `tree-sitter==0.25.2` | cp310–cp314 별 휠 (abi3 아님). ABI 13–15 를 읽는다 |
| `tree-sitter-javascript==0.25.0` | cp310-abi3. JS·JSX |
| `tree-sitter-typescript==0.23.2` | cp39-abi3, ABI 14. `language_typescript()`·`language_tsx()` |
| `tree-sitter-php==0.24.1` | cp310-abi3. `language_php()`(HTML 포함)·`language_php_only()` |
| `tree-sitter-python==0.25.0` | cp310-abi3 |

- 플랫폼: linux x86_64/aarch64 (glibc ≥ 2.17), musl x86_64, macOS x86_64 (≥10.9, cp312+ 는 ≥10.13)/arm64 (≥11.0), Windows amd64/arm64. **musl aarch64 와 free-threaded 빌드는 휠이 없어 엔진 없음**으로 동작한다.
- 0.26.0 도 같은 범위를 지원한다. 4단계에서 두 버전 모두 정확도 사례를 돌려 보고, 통과하는 쪽 중 오래된 0.25.2 를 기본으로 고정한다(API 는 `Parser`, `Language`, 노드 순회만 쓰므로 둘 다 같은 코드로 돈다).
- 뺀 후보: tree-sitter-language-pack(첫 사용 시 다운로드, glibc 2.34 하한), ast-grep(규칙 언어 교체가 필요하고 43MB), WASM(Node 런타임 필요), Pygments(주석·문자열만).

### 4.2 Blade

PyPI 에 Blade 문법이 없다. Blade 는 **전처리기 + tree-sitter-php** 로 다룬다.

- 전처리기(표준 라이브러리, Blade 문법 그대로): `{{-- --}}` 주석, `{{ }}`·`{!! !!}` 출력식, `@php … @endphp`, `<?php … ?>`, 지시문 인자 `@foreach(...)`, 짝 지시문 블록(`@foreach…@endforeach`, `@for`, `@while`, `@forelse…@empty…@endforelse`, `@if…@endif` 등).
- PHP 구간은 각각 `language_php_only` 로 파싱하고 오프셋을 원문으로 되돌린다. 지시문 블록은 loop/branch 범위가 된다. 그 밖의 HTML 텍스트는 `string`(리터럴 텍스트)으로 본다.
- 전처리기는 엔진 어댑터의 일부다. 엔진이 없으면 Blade 도 다른 언어와 똑같이 UNKNOWN 이다(§4.6).

### 4.3 정규식 게이트 → 구조 확인

```
규칙마다
  ① 게이트: 에이전트 소유 줄(line·requires) / 파일 본문(file) 에 규칙 정규식 매치
       구조 조건이 없는 규칙 → 여기서 후보 확정 (엔진을 부르지 않음)
       매치가 없는 규칙   → 끝
  ② 확인: 구조 조건이 있는 규칙의 매치가 있는 파일만 파싱 (파일당 한 번, 프로세스 안 메모)
       not_in / in_scope / block_empty 를 노드 종류로 판정 → ACCEPT / REJECT / UNKNOWN
```

엔진 모듈은 ② 에 처음 들어갈 때만 임포트한다. 게이트에 걸린 매치가 없는 Stop 은 tree-sitter 를 임포트하지 않는다.

### 4.4 노드 대응표

언어마다 데이터 한 덩어리(`scripts/lib/structure/nodes.py`)로 둔다. 함수 헤더 정규식은 없어진다.

| 범주 | 판정에 쓰는 것 |
|---|---|
| comment | 주석 노드 (`comment`). PHP `#[` 는 `attribute` 라서 주석이 아님 |
| string | 문자열·템플릿·heredoc/nowdoc·정규식 리터럴·JSX 텍스트·PHP 인라인 HTML(`text`)·Python 문자열/f-string. **단 그 안의 코드 자식**(JS `template_substitution`, Python f-string `interpolation`, PHP 보간식 — PHP 는 래퍼 노드가 없어 문자열 노드의 이름 있는 자식 중 문자열 조각이 아닌 것)은 코드 |
| function | 함수 선언·식, 화살표 함수, 메서드, PHP 클로저·`fn`, Python `def`·`lambda` |
| loop | for/for-in/for-of/while/do, PHP `foreach`, Python `for`·`while`·컴프리헨션, 그리고 **콜백 반복**: 호출의 메서드·함수 이름이 반복 이름 목록(`forEach`, `map`, `each`, `array_map` …)에 있고 인자로 넘긴 함수 노드의 본문 |
| class | class/interface/trait/enum 선언 |
| catch | `catch_clause`, Python `except_clause` |
| block body | `block_empty` 가 보는 본문 (`statement_block`, `compound_statement`, `block`). 주석은 내용으로 친다(3.x 약속 유지) |

- 3.x 원칙을 잇는다: 블록의 헤더는 그 블록 **안**이 아니다(`for (x of await load())` 의 반복 대상은 한 번 실행). 범위는 본문 노드 기준이다.
- 반복 이름 목록은 참고 자료 정정대로 **여전히 필요**하다. 구조가 해 주는 것은 "그 이름의 호출에 인자로 넘긴 함수의 본문"이라는 관계 판정이다.
- 의미 판정 컨텍스트 팩의 `current_function` 과 `imports` 도 엔진으로 답한다. 엔진이 없으면 매치 주변 ±N줄 창을 주고 팩에 "함수 경계 미확인"을 적는다.

### 4.5 설치

참고 자료의 결론대로 **표준 라이브러리 휠 설치기**를 쓴다(venv·pip 없음, PEP 668 무관).

- `scripts/lib/engine/lock.json`: 패키지·버전·파일명·URL·sha256·플랫폼 태그 목록 (레포에 커밋, 사람이 고치지 않고 `engine.py lock` 이 PyPI JSON API 에서 만듦).
- 설치기(`lib/engine/install.py`): 인터프리터의 호환 태그 계산(`sysconfig`, glibc/musl 판별, macOS 버전) → 맞는 휠 선택 → `files.pythonhosted.org` 에서 받기 → sha256 확인 → 경로 탈출 검사 후 압축 해제 → 임시 디렉터리에서 임포트·파싱 자체 시험 → `${CLAUDE_PLUGIN_DATA}/engine/<lock 해시>/<cpXY-플랫폼>/` 로 원자적 이름 변경 + `READY` 표시. 프록시는 `urllib` 의 환경 변수를 따른다.
- 언제:
  1. `SessionStart` 훅 (`async: true`) — `scripts/session_start.py` 가 엔진이 없으면 설치한다. 첫 응답을 기다리게 하지 않는다.
  2. Stop 이 엔진이 필요한데 없고 최근 10분 안의 설치 시도가 없으면 분리된 백그라운드 프로세스로 설치를 시작하고, 이번 Stop 은 엔진 없이 진행한다(SessionStart 가 돌지 않는 환경 대비).
  3. 수동/CI: `python3 scripts/engine.py ensure` (끝날 때까지 기다리고 실패하면 0 아닌 코드). `scan.py --require-engine` 은 엔진이 없으면 실패한다.
- 오프라인: `CONVENTION_GUARD_WHEELS=<디렉터리>` 에 같은 휠을 두면 거기서 설치한다(sha256 검사는 같음).
- 로더는 고정 설치 디렉터리만 본다. 사용자 환경의 다른 버전 tree-sitter 를 집어 오지 않는다(기기마다 결과가 달라지지 않게). 테스트는 `CONVENTION_GUARD_ENGINE_DIR` 로 경로를 준다.

### 4.6 엔진이 없을 때의 기대 동작

엔진이 없는 경우: 설치 전·설치 중, 오프라인, 지원하지 않는 플랫폼(musl aarch64, free-threaded), 설치 실패, `CONVENTION_GUARD_NO_ENGINE=1`.

| 항목 | 동작 |
|---|---|
| 구조 조건이 없는 규칙 | 엔진과 무관하게 똑같이 돈다 |
| 구조 조건이 있는 규칙의 게이트 매치 | **UNKNOWN** — 후보를 남긴다 (3.x 와 같이 차단 대상) — **결정 D2** |
| 알림 | `구조 엔진 없음 (설치 중 / 실패: <사유> / 미지원 플랫폼) — 구조 조건 N개 후보를 확인 없이 올림` |
| 의미 판정 컨텍스트 | 함수 경계 대신 ±N줄 창, "함수 경계 미확인" 표시 |
| 내장 대체 계층 | **없다.** 3.x 의 마스킹·블록 트리·`pyast` 를 지운다 |

- 언어 자체가 지원 대상이 아닌 파일(예: `.yaml` 에 걸린 `no-hardcoded-secret` 의 `not_in: [comment]`)도 UNKNOWN 이고 "구조 미확인" 으로 알린다(3.x 와 같음).
- 파싱 오류: tree-sitter 는 오류가 있어도 트리를 준다. 매치가 `ERROR`/`MISSING` 노드 안이나 그 조상 아래 있으면 그 매치는 UNKNOWN 이다. 오류가 다른 곳에 있으면 판정한다.

> **결정 D2 — 엔진 없음(UNKNOWN) 후보를 차단할 것인가.**
> 권장: **3.x 와 같이 차단 대상에 넣고 이름을 붙인다.** 엔진은 자동 설치되므로 없는 상태는 드물고 눈에 보이며, "못 읽은 것을 통과로 처리하지 않는다"는 핵심 3 에 가장 곧다.
> 대안: UNKNOWN 후보는 기록만 하고 차단하지 않는다(사이클의 "린터 미확인"과 같은 취급). `block_empty` 규칙처럼 정규식만으로는 거의 모든 `catch {` 가 걸리는 경우의 오탐 차단은 피하지만, 엔진 없는 기기에서 `dd()` 같은 진짜 위반도 막지 않는다.

---

## 5. Python 하한: **3.10**

| 근거 | |
|---|---|
| 엔진 | tree-sitter 0.24 이상과 ABI 15 문법(javascript 0.25, php 0.24, python 0.25)이 3.10 이상이다. 3.9 를 지원하려면 0.23.x 고정 세트를 따로 두어야 하는데, 그 core 0.23.2 는 **cp314 휠이 없어** 3.9 와 3.14 를 한 세트로 덮을 수 없다. 두 세트 + Query API 차이 대응이 필요해진다 |
| 수명 | Python 3.9 는 2025-10 에 지원이 끝났다. 3.10 은 2026-10 에 끝나지만 Ubuntu 22.04(3.10)·Debian 12(3.11)·24.04(3.12) 의 기본 인터프리터가 3.10 이상이다 |
| 위험 | macOS Command Line Tools 의 `/usr/bin/python3` 가 3.9.x 인 기기가 있다. 그 기기에서는 `lib/__init__.py` 의 버전 가드가 "Python 3.10 이상 필요 — Homebrew/python.org 로 설치" 를 `systemMessage` 로 말하고 종료 코드 0 으로 끝난다(핵심 3). 이 기기를 지원하는 것이 중요하면 3.9 + 0.23 세트로 갈 수 있다 — 그 경우 3.14 에서는 엔진 없음 |

---

## 6. 단계와 완료 기준

각 단계 끝에 전체 테스트(§8 의 두 실행)가 통과하고, 진행 기록을 갱신하고, 단계 보고 후 승인을 받는다. 커밋은 사용자가 요청할 때 한다.

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **1. 정리 + sqlite 저장소** | Go 규칙·스택·프리셋·언어 제거, 이관·호환 경로 제거(`migrate`, `legacy_hashes`, `aliases`, 배치 v1, 상태 v1), `dismissed.yaml` 에 `version: 4`, Python 3.10 가드, `lib/store.py`(스키마·GC·3.x 파일 정리), 판정 캐시·배치·파싱 캐시를 DB 로. YAML 은 `miniyaml` 하나로(§8) | 데이터 디렉터리에 DB 와 `firings.jsonl` 외 파일이 생기지 않음. 판정 캐시 동시 쓰기 테스트(프로세스 여러 개) 통과. 골든 재생성 + diff 설명 |
| **2. decide()** | `lib/decide.py`(순수), `lib/stop.py`(셸), `hooks.py` 해체, 사이클 상태를 DB 로. 동작은 3.3 과 같게(범위는 아직 touched 기반) | decide 표 테스트(3.2 R3·R4·R17 포함 전이 표) 통과. 기존 `test_hook_cycle.py` 시나리오 전부 통과. `decide.py` 가 I/O 모듈을 임포트하지 않음을 테스트로 강제 |
| **3. 원장 + 관찰 누락** | `lib/ledger.py`, 가벼운 `collect.py`(원장 모듈만 임포트), `PostToolUseFailure` 등록, OwnedScope, 알림. `touched`/`foreign`/`gitdiff.added_lines` 의 훅 경로 제거 | 원장 단위 표 테스트(사건 열 → 줄별 출처). 종단 시나리오: 사람 중간 편집, 사람 포매터, 에이전트 sed, 에이전트 `git commit`, `git pull`(남의 커밋), 파일 이동, Pre 없음, Post 없음, 권한 거부(바뀐 것 없는 열린 사건), 미등록 MCP 편집, 백그라운드 쓰기, 병렬 호출. §1.8 표의 각 행이 테스트 하나 |
| **4. 구조 엔진** | 설치기·lock·로더, 노드 대응표, Blade 전처리기, 게이트 → 확인, `structure/native/` 삭제, 컨텍스트 팩 함수 경계 | §8 의 구조 정확도 사례가 엔진 있음/없음 두 기대대로 통과. 노드 대응표 테스트 통과. 설치기 단위 테스트(태그 계산, sha256 불일치 거부, 경로 탈출 거부, 오프라인 디렉터리) + 실제 다운로드 1회 |
| **5. 문서·측정·릴리스** | `docs/` 를 4.0 구조로 다시 쓰기, `CLAUDE.md` 갱신, 성능 측정 기록, 릴리스 검증(§8), 버전 4.0.0 | §8 절차 전부 통과. 커밋은 요청 시 `release: 4.0.0 — <한 줄>`, 본문에 하위 호환 단절 명시 |

---

## 7. 성능 목표 (고정 조건 아님)

핵심에서 빠졌으므로 **실패 조건이 아니라 측정하고 기록하는 목표**로 둔다. 목표를 넘으면 단계 보고에 원인과 함께 적는다.

| 측정 (WSL2 기준 기기) | 3.3.0 | 4.0 목표 |
|---|---|---|
| Stop, 파일 60개 변경, 후보 0건 (중앙값) | 68.7ms | ≤ 60ms (git diff 대신 원장을 읽으므로 줄어들 것으로 예상) |
| 수집 훅 1회, Edit Pre / Post | 42 / 42ms | ≤ 25ms (원장 모듈만 임포트. `python3` 기동 + json + sqlite3 임포트가 15.6ms) |
| 수집 훅 1회, Bash·MCP Pre / Post | 47 / 47ms | ≤ 35ms (`git status` 포함) |
| Stop, 게이트 매치 1건 + 엔진 파싱 | — | 기록만 |

`tests/perf/run.py` 가 이 네 값을 재서 JSON 으로 남긴다.

---

## 8. 테스트와 릴리스 검증

### 8.1 YAML: PyYAML 있음/없음 두 번 실행을 그만둔다

배포 경로가 표준 라이브러리만 쓸 필요가 없어졌지만, 규칙 로딩은 엔진처럼 다운로드에 기대면 안 된다(설치 전에도 검사해야 한다). 그래서 **내장 `miniyaml` 하나만 쓴다.** PyYAML 이 있어도 쓰지 않으므로 기기마다 파싱이 달라질 수 없고, 두 번 실행할 이유가 없다. PyYAML 은 개발 의존성으로 남아 `test_yaml_parity.py` 가 번들 YAML 전부를 두 파서로 읽어 같은지 확인하는 **정답지** 역할만 한다.

### 8.2 구조 정확도 사례 (`tests/structure/cases/`)

사례 하나 = 언어, 코드, 표시한 위치, 기대(`code|comment|string`, `in_loop`, `in_function`). 참고 자료의 29개보다 넓게, 언어별로 최소 다음을 포함한다.

| 언어 | 사례 유형 |
|---|---|
| JS/JSX | 정규식 리터럴(나눗셈과 구분, 문자 클래스 안 `/`), 템플릿 리터럴과 중첩(`${ `${x}` }`), JSX 텍스트·속성 문자열·`{}` 식, 화살표 함수(중괄호 없음/있음), `forEach`/`map` 콜백, `for…of` 헤더, 클래스 메서드, React 컴포넌트·훅, Next `'use client'` |
| TS/TSX | 제네릭 화살표(`<T,>() =>`), 타입 주석 안 문자열 리터럴 타입, 데코레이터(Nest `@Controller()`), TSX 중괄호 없는 화살표 |
| PHP | `#[` 속성 vs `#` 주석, `//` 주석 뒤 `?>`, `?>` 뒤 HTML, heredoc/nowdoc(보간 포함), 문자열 보간 `"{$a->b()}"`, 클로저 `function() use`, `fn() =>`, `array_map`/`->each` 콜백, `foreach`, `catch` 빈/주석만/내용 있음, Laravel 컨트롤러·마이그레이션 형태 |
| Blade | `{{-- --}}`, `{{ }}` 안 호출, `{!! !!}`, `@foreach…@endforeach` 안, `@php…@endphp`, HTML 텍스트 |
| Python | f-string 안의 식(3.12 중첩 따옴표 포함), 삼중 따옴표, 바이트·raw 문자열, `#` 주석, `lambda`, 컴프리헨션, `for`/`while`, 데코레이터, `except` |

- 엔진 있음: 모든 사례가 기대와 같다.
- 엔진 없음(`CONVENTION_GUARD_NO_ENGINE=1`): 모든 사례가 UNKNOWN 이고 사유가 `engine_missing` 이다.
- **노드 대응표 테스트**: 표의 모든 노드 이름이 고정 문법에 실제로 있는지(`Language.id_for_node_kind`) 확인하고, 언어마다 대표 코드를 파싱해 각 범주가 한 번 이상 나오는지 확인한다. 문법 버전을 올리면 이 테스트가 먼저 깨진다.

### 8.3 릴리스 검증 절차 (4.0)

1. `python3 scripts/engine.py ensure --dir .engine` (개발용 엔진, `.gitignore`)
2. `CONVENTION_GUARD_ENGINE_DIR=.engine .venv/bin/python tests/run_all.py` — 엔진 있음
3. `CONVENTION_GUARD_NO_ENGINE=1 .venv/bin/python tests/run_all.py` — 엔진 없음 (3.x 의 PyYAML 두 번 실행 자리를 이것이 대신한다)
4. 하한 인터프리터로 전체 1회: `uv run --python 3.10 python tests/run_all.py` (엔진 있음)
5. `python3 scripts/engine.py verify-lock` — lock 의 모든 휠이 PyPI 에서 받아지고 sha256 이 맞는지 (네트워크)
6. `python3 tests/perf/run.py` — §7 의 네 값 기록
7. 실제 세션 점검: 임시 레포에서 `claude -p --plugin-dir <레포>` 로 Edit 위반 → 차단 → 수정 → 재검증 통과 한 사이클 (이 기기에 `claude` CLI 가 있음)
8. `.claude-plugin/plugin.json`·`marketplace.json` 의 `version` 을 둘 다 4.0.0 으로

---

## 9. 모듈 구성 (4.0)

```
scripts/
  collect.py        Pre/Post/PostToolUseFailure → lib/ledger (그 밖은 임포트하지 않음)
  check.py          Stop → lib/stop
  session_start.py  SessionStart(async) → lib/engine, lib/store GC
  engine.py         엔진 status / ensure / lock / verify-lock
  scan.py dismiss.py review.py setup.py readiness.py detect_stack.py log_report.py
scripts/lib/
  store.py          sqlite 연결·스키마·GC
  ledger.py         출처 모델, apply(), 사건 처리, 관찰 누락 판정
  observe.py        git status·stat·blob 읽기 (수집 훅과 Stop 공용, 가벼움)
  scope.py          ChangeScope (+ from_ledger), CLI 범위
  gitdiff.py        CLI 범위용 diff + 남의 커밋 줄 (원장이 HEAD 이동 때만 부름)
  pipeline.py detect.py lint.py rules/ stack.py config.py dismiss.py autofix.py
  decide.py         순수 사이클 결정 (classify 포함)
  stop.py           Stop 셸: 관찰 → decide → 저장·로그·렌더
  semantic.py context.py report.py fmt.py log.py
  structure/        model.py conditions.py nodes.py(대응표) blade.py engine_backend.py
  engine/           install.py tags.py lock.json loader.py
```

## 10. 승인 받을 결정

| # | 결정 | 권장 |
|---|---|---|
| D1 | 관찰 구간 밖에서 바뀐 줄(`u`)을 검사할 것인가 | 검사 안 함, 이름만 붙임 |
| D2 | 엔진 없음(UNKNOWN) 후보를 차단할 것인가 | 차단 대상에 넣고 이름 붙임 (3.x 와 같음) |
| D3 | Python 하한 | 3.10 |
| D4 | YAML 파서 | `miniyaml` 하나만, PyYAML 두 번 실행 폐지, 대신 엔진 있음/없음 두 번 실행 |
| D5 | MCP 도구 수집 | 이름 설정 없이 모든 MCP 호출을 작업 트리 관찰 (`collect.edit_tools` 제거) |
| D6 | `scope.base_ref` | 제거 (`scan.py --range` 로 대신) |
| D7 | 단계 순서 | 정리+sqlite → decide → 원장 → 엔진 → 릴리스 |

## 11. 구현 중 바뀌거나 정해진 것

설계 승인(2026-10-01, D1~D7 권장안) 뒤 구현하면서 정한 것들이다. 위 본문은 승인 당시 그대로 둔다.

| 항목 | 정한 것 | 이유 |
|---|---|---|
| 단계 순서 | 승인대로: 정리+sqlite → decide → 원장 → 엔진 → 릴리스 | — |
| decide() 이관 방식 | 3.x 가 상태를 저장하던 시점마다 스냅샷을 찍어 `Decision.state` 로 돌려준다 | 전이를 바꾸지 않고 옮겨, 기존 종단 테스트를 고치지 않고 통과시키기 위해 |
| 판정 배치 id | 셸이 미리 만든 16자 hex 토큰 (`review_batch.id` TEXT) | decide 가 저장 전에 상태에 참조를 적을 수 있게 |
| 관찰 누락 개수 | "N회" 대신 파일 수로 센다 | 같은 Stop 에서 같은 파일을 한 번만 말하려고 |
| 중첩 레포 파일 | 원장이 쓰기를 봤으면 검사한다 (3.x 는 "검사되지 않음") | 원장은 git 이 볼 수 없는 파일도 내용으로 따라간다 |
| 줄 이동 | 같은 사건에서 지웠다 다시 쓴 줄은 출처를 잇고, 이음매도 남기지 않는다 | 옮긴 것은 지운 것이 아니다 |
| 새 파일 | 처음 볼 때 없던 파일을 에이전트가 **써서** 만든 경우만 (`a` 줄이 하나 이상) | `mv` 로 옮겨 온 파일에 새 파일 규칙이 걸리지 않게 |
| 읽기 오류 | 첫 오류 지점부터 뒤의 매치는 UNKNOWN (`parse_error`), 닫히지 않은 문자열·주석 노드는 통째로 오류 | tree-sitter 는 짝 없는 따옴표 뒤를 코드로 복구하지만 PHP 는 문자열로 본다. 오류는 뒤의 해석을 바꾼다 |
| `block_empty` 창 | 블록 범위를 읽지 못하면 그 파일을 "구조 미확인" 으로 알린다 | 레거시 catch 본문을 비운 변경이 엔진 없이 조용히 지나가던 구멍 (핵심 3) |
| 픽스처 | 구조 조건이 있는 규칙의 사례는 완결된 코드. 사례가 `<?` 로 시작하면 `<?php` 를 덧붙이지 않는다 | 실제 파서는 `} catch (…) {` 조각을 읽지 못한다 |
| Blade | 전처리기 + PHP 섬별 `php_only` 파싱, 지시문 블록은 직접 짝 맞춤 | PyPI 에 Blade 문법이 없다 |
| 콜백 반복 | 반복 이름 목록 유지, 인자 래퍼(PHP `argument`, Python `keyword_argument`)는 마지막 자식을 값으로 | 참고 자료 정정대로 이름 목록이 필요하고, 이름 있는 인자도 있다 |
| 엔진 없음 테스트 | `CONVENTION_GUARD_NO_ENGINE=1` 실행에서 구조에 기댄 사례는 건너뛰고 개수를 출력, 대신 "후보 유지 + 알림"을 확인 | 엔진 없음의 약속은 "판정"이 아니라 "말하기"다 |
| `scan.py --require-engine` | 추가 | CI 가 엔진 없이 구조 조건을 건너뛴 결과를 통과로 읽지 않게 |
| Python 스택·규칙 | `stacks/python.yaml`, `py-no-debug-output`, `py-no-bare-except` 추가 (범위 밖 추가, 단계 4 보고) | 지원 언어인데 규칙이 없어 엔진이 Python 에 쓰이는 경로가 없었다 |
| YAML | miniyaml 은 여러 줄 흐름 목록을 읽지 못한다 — 문서(rules.md)에 제약으로 적음 | 파서를 하나로 고정한 대가 |

### 실측 (WSL2, Python 3.12, 2026-10-02)

| 측정 | 3.3.0 | 4.0 | 목표 |
|---|---|---|---|
| Stop, 60개 파일, 게이트 0건 | 68.7ms (참고 자료) | 57.4ms | ≤ 60ms |
| Stop, 60개 파일 모두 catch (구조 확인 후 0건) | — | 115ms | 기록만 |
| 수집 훅 Edit Pre / Post | 42 / 42ms | 26 / 25ms | ≤ 25ms |
| 수집 훅 Bash Pre / Post | 47 / 47ms | 27 / 28ms | ≤ 35ms |
| Stop, 게이트 매치 1건 + 엔진 | — | 66.6ms | 기록만 |
| 엔진 임포트 / 1,000줄 분석 (php·js·py) | — | 20ms / 7.3·5.9·4.2ms | — |
| 구조 정확도 | 25/29 (참고 자료) | 88/88 | — |

