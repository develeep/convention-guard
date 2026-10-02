# 실 서비스 도입 체크리스트

[README](../../../README.md) · **한국어** · [English](../en/production-readiness.md)

팀 레포에 convention-guard 를 실제로 켜기 전에 "모든 기능이 의도대로 동작하는가"를
확인하는 절차입니다. 각 항목은 **왜 / 확인 / 기대 / 실패하면** 으로 되어 있고,
확인 방법이 셋 중 하나로 표시됩니다.

| 표시 | 뜻 |
|---|---|
| **[자동]** | `readiness.py` 가 이 레포와 설치 상태를 직접 읽어 판정 |
| **[샌드박스]** | `readiness.py` 가 플러그인 자체 테스트를 임시 레포에서 돌려 판정 — 실제 턴을 끝내 볼 필요 없음 |
| **[수동]** | 사람이 확인해야 하는 것 |

```bash
python3 <설치 경로>/scripts/readiness.py            # 전체 (~10초)
python3 <설치 경로>/scripts/readiness.py --quick    # 샌드박스·측정 생략 (~1초)
```

Claude Code 세션을 여는 디렉터리에서 실행하세요. 프로젝트·로컬 설정(B2·B5)은 그 디렉터리 기준으로 읽습니다.

출력의 한 줄이 이 문서의 항목 id 하나입니다. `convention-readiness` 스킬이 이 점검을 돌리고 결과를 정리합니다.

설치 경로는 Claude Code 가 기록한 값입니다 (버전마다 바뀌므로 경로를 외워 두지 마세요):

```bash
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e['installPath'] for k,v in d['plugins'].items() if k.startswith('convention-guard@') for e in v][0])"
```

이 플러그인의 핵심 안전 원칙은 하나입니다 — **검사하지 못한 것이 깨끗한 통과처럼 보이면 안 된다.**

## 목차
- A. 환경 전제
- B. Claude Code 플러그인 — 설치·범위·배선
- C. 레포 설정 계층
- D. 규칙이 전부 동작하는가
- E. 탐지량 — 우리 레포에서 몇 건 걸리나
- F. 차단·수정·재검증 사이클
- G. 의미 판정 (서브에이전트)
- H. 장애 모드 — 조용히 죽지 않는가
- I. 성능 예산
- J. 보안·프라이버시
- K. CI 연동
- L. 운영 — 도입 후 2~3주
- M. 롤백
- N. 이 체크리스트로 확인되지 않는 것

---

## A. 환경 전제

- [ ] **A1. Python 3.10 이상이 `python3` 로 실행된다** [자동][샌드박스]
  - 왜: 훅은 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py"` 로 실행됩니다. 구조 엔진(tree-sitter)에 3.10 미만 휠이 없습니다. macOS Command Line Tools 의 `python3` 가 3.9 인 기기가 있습니다.
  - 기대: PATH 의 `python3` 가 3.10+. 3.9 이하면 필요한 버전과 할 일을 말하고 조용히 죽지 않습니다 (`tests/unit/test_version_guard.py`).
  - 실패하면: 인터프리터를 올리거나 팀 표준 파이썬을 `python3` 로 잡으세요.

- [ ] **A2. Windows 네이티브 팀원이 있는지** [수동]
  - 왜: Windows 네이티브에서는 `python3` 가 없거나 Microsoft Store 스텁일 수 있어 훅이 돌지 않습니다.
  - 확인: 팀원 각자 `python3 --version`. 점검을 돌린 머신이 Windows 네이티브면 [자동]으로 WARN.
  - 실패하면: WSL 에서 쓰거나 훅 대신 `scan.py` + CI(K)로 운영하세요. **저장소 CI 에서 검증되지 않은 경로입니다.**

- [ ] **A3. 검사 대상이 git 워크트리다** [자동]
  - 기대: git 이 아니면 stderr `convention-guard: error: git 레포가 아닙니다` + **exit 2** (통과를 뜻하는 0 이 아님). `readiness.py` 자신도 같은 규칙으로 exit 2.

- [ ] **A4. 설치 없이 규칙을 읽는다** [자동][샌드박스]
  - 왜: 규칙·설정은 내장 YAML 파서(`miniyaml`) 하나로 읽습니다. PyYAML 이 있어도 쓰지 않습니다.
  - 기대: 샌드박스에서 `detect_stack.py` 가 오류 없이 규칙을 읽음. 오류가 나면 config.yaml·로컬 규칙에 내장 파서가 읽지 못하는 YAML 문법(여러 줄 흐름 목록 등)이 있는 것입니다.

- [ ] **A5. 구조 엔진이 설치돼 있다** [자동]
  - 왜: 구조 조건(`not_in`·`in_scope`·`block_empty`)은 tree-sitter 로 판정합니다. 엔진이 없으면 조건을 적용하지 못해 후보가 확인 없이 올라옵니다 ("구조 엔진 없음" 으로 알림).
  - 기대: `python3 scripts/engine.py status` 가 경로를 보여줌. 세션 시작(SessionStart 훅)이나 첫 Stop 에서 백그라운드로 설치됩니다.
  - 실패하면: `python3 scripts/engine.py ensure` 를 직접 실행해 사유를 보세요. 오프라인이면 `CONVENTION_GUARD_WHEELS` 에 `lock.json` 의 휠을 두고 설치합니다. musl aarch64 와 free-threaded Python 은 휠이 없어 미지원입니다.

---

## B. Claude Code 플러그인 — 설치·범위·배선

- [ ] **B1. 이 레포에 적용되는 설치가 있고 최신이다** [자동]
  - 왜: 설치는 user / project / local 범위로 기록됩니다 (`~/.claude/plugins/installed_plugins.json`). local 설치는 `projectPath` 레포에만 적용됩니다.
  - 기대: 이 레포에 적용되는 설치 기록이 있고, 버전이 마켓플레이스 최신과 같다.
  - 실패하면: `/plugin` 에서 설치·업데이트하세요.

- [ ] **B2. 팀원에게도 켜진다 (활성 범위)** [자동]
  - 왜: `enabledPlugins` 는 user < project < local 순으로 덮입니다. **user·local 범위에서만 켜면 나만 검사됩니다.**
  - 기대: 최종값이 true 이고, 프로젝트 `.claude/settings.json` 에 `enabledPlugins` 와 `extraKnownMarketplaces` 가 커밋돼 있다.
  - 실패하면:
    ```json
    {
      "enabledPlugins": { "convention-guard@<마켓플레이스>": true },
      "extraKnownMarketplaces": { "<마켓플레이스>": { "source": { "source": "git", "url": "<저장소>" } } }
    }
    ```

- [ ] **B3. 훅이 걸려 있고 실제로 돈다** [자동][샌드박스]
  - 왜: Pre/PostToolUse·PostToolUseFailure(편집 사건 원장) / Stop(검사)이 다 있어야 "에이전트가 쓴 줄만" 이 성립합니다. 훅이 빠지거나 죽으면 Stop 이 "관찰 누락" 으로 알립니다.
  - 기대: `hooks.json` 에 PreToolUse·PostToolUse·Stop 배선(점검 대상은 이 셋. PostToolUseFailure·SessionStart 는 같은 파일에 있지만 점검하지 않음) + 훅 데이터 디렉터리(B4)의 상태 저장소(`convention-guard.db`)에 최근 활동이 있음.
  - 실패하면: 세션에서 파일을 한 줄 고치고 턴을 끝낸 뒤 다시 점검. 여전히 없으면 `/plugin` 에서 enabled 인지 보세요.

- [ ] **B4. 데이터 디렉터리가 어디인지 안다** [자동]
  - 왜: 설치된 훅은 Claude Code 가 주는 `CLAUDE_PLUGIN_DATA`(`~/.claude/plugins/data/convention-guard-<마켓플레이스>/`)에 씁니다. 손으로 돌린 스크립트는 이 변수가 없으면 `$XDG_CACHE_HOME/convention-guard/`(없으면 `~/.cache/convention-guard/`, 그것도 못 만들면 임시 디렉터리)를 봅니다 — **다른 디렉터리**입니다.
  - 기대: 두 위치가 같거나, 다르다는 사실과 쓸 경로를 안다.
  - 실패하면: `log_report.py`·`review.py` 를 직접 돌릴 때 `CLAUDE_PLUGIN_DATA="<훅 데이터 디렉터리>"` 를 앞에 붙이세요. 안 붙이면 로그가 "비어 있음"으로 보입니다.

- [ ] **B5. userConfig 가 범위별로 의도대로다** [자동]
  - 왜: 설치할 때 고른 값은 범위별 settings 의 `pluginConfigs["convention-guard@…"].options` 에 남습니다.
  - 기대:
    - `report_only`·`semantic_review` 가 true/false 다.
    - `log_dir` 이 **레포 밖의 절대경로**다. 상대경로(`./logs`)는 훅의 작업 디렉터리, 즉 **각 레포 안**으로 풀려 레포마다 로그가 흩어지고 git 에 잡힐 수 있습니다.
  - 참고: 레포 `config.yaml` 의 `mode`·`semantic_review` 가 항상 userConfig 보다 우선합니다 (C2).

- [ ] **B6. 스킬 6개와 리뷰어 에이전트가 있다** [자동][샌드박스][수동]
  - 기대: `convention-check`·`convention-discover`·`convention-setup`·`rule-add`·`rule-tune`·`convention-readiness` 와 `agents/convention-reviewer.md`. 구조(이름·설명·참조·스크립트 실재)는 `tests/skills/test_skill_structure.py`.
  - 수동: 스킬이 실제로 올바르게 따라지는지는 `tests/skills/evals/*.json` 시나리오를 Claude 로 돌려 봐야 압니다.

---

## C. 레포 설정 계층

```
플러그인 config.yaml  <  userConfig  <  <repo>/.claude/convention-guard/config.yaml
규칙: core(플러그인)  <  user(~/.claude/convention-guard/rules)  <  local(<repo>/.claude/convention-guard/rules)
```

- [ ] **C1. 레포 config 가 유효하다** [자동]
  - 기대: 오류 노트 없음. 모르는 키는 무시되고 경고로 보입니다.
  - 기대: 첫 도입이면 `mode: report`. `fix`·`auto-fix` 면 WARN.
  - 실패하면: 오류가 있으면 훅은 검사를 건너뜁니다(말하면서). 오류를 고치세요.

- [ ] **C2. 우선순위가 지켜진다** [샌드박스]
  - 기대: 레포 값이 userConfig 를 이긴다(한 사람이 기준을 낮출 수 없음). 그룹 일부 키만 적어도 나머지 기본값 유지. 잘못된 타입은 오류. 모르는 키(3.x·0.x 키 포함)는 `알 수 없는 설정 … (무시)` 경고 (`tests/unit/test_config_and_rules.py`).

- [ ] **C3. 스택·프리셋 감지가 우리 레포와 맞다** [자동][수동]
  - 기대: `stacks` 가 실제 스택과 일치. 비면 WARN.
  - 실패하면: `config.yaml` 에 `stacks:`. 모노레포는 루트에서 한 번만 판정하므로 `applies_to.files` / `exclude` 로 나누세요.

- [ ] **C4. 린터 위임이 의도대로다** [자동]
  - 기대: 없는 린터는 `설치 안 됨 — 건너뜀`, 있는 린터는 `변경 줄만 차단 (parse: …)`. `출력 파싱 불가 — 전체 출력으로 차단` 이면 warn — 무관한 기존 에러로도 막힙니다.
  - 번들 명령은 `npx --no-install`, `./vendor/bin/*` 처럼 **이미 있는 바이너리만** 씁니다.
  - 실패하면: `stacks/*.yaml` 에 `parse:`, 또는 `linters.enabled: false`.

- [ ] **C5. 모든 팀원이 같은 규칙을 돌린다 (개인 레이어)** [자동]
  - 왜: `~/.claude/convention-guard/rules/` 의 개인 규칙은 그 머신에서만 돕니다. 같은 커밋이 사람마다 다르게 걸립니다.
  - 기대: 비어 있거나, 개인용이라는 것을 안다.
  - 실패하면: 팀 규칙이면 레포 `.claude/convention-guard/rules/` 로 옮기세요.

- [ ] **C6. 기각 기록이 읽힌다** [자동]
  - 왜: `dismissed.yaml` 이 깨지면 훅이 검사를 건너뜁니다.
  - 기대: 파싱 성공, 건수 표시.

---

## D. 규칙이 전부 동작하는가

- [ ] **D1. 모든 규칙이 자기 픽스처를 통과한다 — core·user·local** [샌드박스]
  - 확인: `tests/rules/test_rule_fixtures.py --repo <레포> --user-dir <디렉터리>`
  - 기대: 모든 `tests.match` 가 걸리고 `no_match` 는 안 걸림. override 는 원본에 병합된 상태로 검사. `fix.auto` 는 위반을 해소하고 정상 코드는 그대로.

- [ ] **D2. 적용 규칙마다 닿는 파일이 있다** [자동]
  - 왜: `✔ on` 이어도 `applies_to.files` 가 레포 구조와 안 맞으면 (`app/**` 인데 코드가 `src/`) 영원히 걸리지 않습니다. 켜져 있는데 죽은 규칙입니다.
  - 기대: 적용 규칙마다 추적 파일 1개 이상에 닿음 (짝 규칙은 `when_changed` 기준).
  - 실패하면: 그 스택이 아직 없으면 무시해도 됩니다. 구조가 다르면 `override` 로 `applies_to.files` 수정.

- [ ] **D3. 레거시가 걸리지 않는다** [샌드박스][수동]
  - 왜: 앵커가 "추가된 줄 / 새 파일 / 변경 집합"이라 손대지 않은 코드는 책임 밖이어야 합니다.
  - 샌드박스: `tests/rules/test_rule_scenarios.py` — 모든 비-`when_line_added` 규칙에 "새 코드는 걸림 / 레거시는 조용함" 시나리오.
  - 수동: 레거시 위반이 많은 파일에서 관계없는 한 줄만 고치고 `scan.py` → 기존 위반이 안 나와야 합니다. 나오면 그 규칙의 앵커가 `file_regex` 인지 보세요 ([rules.md](rules.md#앵커-무엇이-이번-변경의-책임인가) 앵커 표).

- [ ] **D4. 주석·문자열 안의 코드가 지적되지 않는다 (구조 조건)** [샌드박스]
  - 기대: `not_in: [comment, string]` 규칙에서 주석·문자열 속 매치는 제외, 진짜 코드만 (`tests/structure/test_detect_conditions.py`, `test_conditions.py`).

- [ ] **D5. 의미 판정 규칙이 실제로 판정된다** [자동]
  - 왜: 의미 판정 규칙이 켜져 있어도 `semantic_review.enabled` 가 false 면 후보만 찾고 판정하지 않습니다.
  - 기대: 적용 중인 의미 판정 규칙이 있으면 `semantic_review` 가 켜져 있다.

---

## E. 탐지량 — 우리 레포에서 몇 건 걸리나

- [ ] **E1. 최근 변경분 측정 (도입 판단의 핵심 숫자)** [자동]
  - 확인: 최근 20커밋(`--commits N`)을 린터 포함으로 검사.
  - 기대: error+warn 이 **커밋당 2건 이하**. 그보다 많으면 `fix` 로 올렸을 때 에이전트가 계속 막힙니다.
  - 실패하면: `convention-setup` 4단계 표로 `severity` / `exclude` 를 조정하세요.

- [ ] **E2. 전수조사 규모** [자동, `--all` 일 때]
  - 기대: 규칙별 error 건수 상위 5개. 한 디렉터리에 몰리면 레거시 구역 → `exclude`.

- [ ] **E3. 오탐 감을 잡는다** [수동]
  - 확인: E1·E2 에서 규칙별로 서너 곳을 열어 봅니다.
  - 기대: 20건 중 오탐 2~3건 이하. 넘으면 그 규칙은 아직 켜지 마세요. 오탐은 `dismiss.py` 로 기각하면 코드가 그대로인 동안 다시 뜨지 않습니다.

---

## F. 차단·수정·재검증 사이클

`mode: fix` 로 올리기 전의 구간입니다. **error 강도만 차단합니다.** 전 항목 [샌드박스] — `tests/integration/test_hook_cycle.py`, `test_autofix.py`, `test_dismiss_and_report.py` 가 실제 Stop 훅을 턴 단위로 돌려 확인합니다.

- [ ] **F1. error 는 차단하고, warn 은 기록만 한다** — 차단 시 위반 위치·수정 지시·기각 명령. warn 만 있으면 `convention-guard ⚠ 기록 — warn N (<규칙 id>)` 시스템 메시지. `mode: report` 는 차단하지 않음.
- [ ] **F2. 고치면 통과한다 (재검증)** — 다음 Stop 에서 같은 범위를 재검사하고 조용히 끝남. 로그에 `verify`.
- [ ] **F3. 무한 루프가 없다** — `limits.max_verify_attempts`(기본 1)를 넘으면 `재검증 종료 — … · 이후 기록만`, 전체는 `limits.max_consecutive_blocks`(기본 3) 안.
- [ ] **F4. 오탐 기각이 살아남는다** — 기각 키는 `규칙:파일:코드 지문`. 위에 줄이 추가돼도 유지, 그 줄이 바뀌면 풀림. 로그에 `dismissed`.
- [ ] **F5. 자동 수정을 에이전트가 듣는다** — `mode: auto-fix` 에서 `자동 수정 N (파일) — 편집 전에 다시 읽으세요`. `fix` 모드는 파일을 건드리지 않음.
- [ ] **F6. 질문으로 끝난 턴은 검사하지 않는다** — `skip_if_question: true`(기본). 세션 중 커밋한 변경도 범위에 남음 (원장은 커밋 뒤에도 줄의 출처를 유지).

---

## G. 의미 판정 (서브에이전트)

기본은 **꺼져 있습니다**. 전 항목 [샌드박스] — `tests/integration/test_semantic_review.py`, `tests/semantic/*`.

- [ ] **G1. 후보가 없으면 AI 호출이 0이다** — 게이트에 걸리는 변경이 없는 턴에는 판정 배치가 생기지 않음.
- [ ] **G2. 후보가 있으면 판정 명령 한 줄을 넘긴다** — `convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 전달` + `review.py show <배치>`.
- [ ] **G3. 컨텍스트 팩이 "함수 하나 분량"이다** — 후보 + 주변 + import + 이번 변경이 추가한 줄. `semantic_review.context_budget_lines`, 규칙의 `max_context_lines` 안.
- [ ] **G4. 판정이 캐시된다** — VALID 는 다시 묻지 않음, VIOLATION 은 결정론 후보처럼 차단. 함수 본문·관련 파일·규칙이 바뀌면 재판정. TTL `verdict_ttl_days`(기본 30).
- [ ] **G5. 판정을 못 받은 경우가 통과로 보이지 않는다** — 한 번 더 요청, 그다음 `review_skipped` 기록 + `판정 대기 N`.

---

## H. 장애 모드 — 조용히 죽지 않는가

**가장 중요한 섹션입니다.** 위험한 방식은 하나 — "고장났는데 통과처럼 보이는 것". [샌드박스] — `tests/integration/test_cli_contract.py`, `test_lint_anchor.py`, `test_self_exclude.py`.

- [ ] **H1. 잘못된 설정은 검사를 건너뛰되 말한다** — `convention-guard ✖ 건너뜀 — 설정 오류: ...`. CLI 는 stderr `convention-guard: error: ...` + exit 2.
- [ ] **H2. 모르는 설정 키는 말한다** — `알 수 없는 설정 <키> (무시)` 경고. 3.x 의 `scope.base_ref`·`collect.edit_tools` 도 여기에 해당합니다. `version: 4` 가 없는 `dismissed.yaml` 은 적용하지 않고 경고합니다.
- [ ] **H3. 내부 버그가 턴을 깨지 않는다** [자동] — `readiness.py` 가 설치본 `check.py` 에 비정상 입력을 넣어 확인: exit 0 + `convention-guard ✖ 건너뜀 — 내부 오류: <원인>`.
- [ ] **H4. 구조를 읽지 못한 파일은 고지된다** — `구조 미확인 N개 파일 — ...` 또는 `구조 엔진 없음 (사유) — 구조 미확인 N개 파일`, 후보는 걸러지지 않고 올라감. CI 는 `scan.py --require-engine` 으로 이 경우를 실패로 만들 수 있습니다.
- [ ] **H5. 범위 계산 실패가 통과로 읽히지 않는다** — 검사 불가 메시지 + exit 2.
- [ ] **H6. 수집 훅이 놓친 것이 고지된다** — Post 가 오지 않은 도구(`관찰 누락 — 실행 후 기록 없음`, 바뀐 줄은 검사), Pre 없이 온 Post(`실행 전 기록 없음`), 도구 밖 변경(`출처 미확인 변경`), 수집 훅 자신의 오류(`수집 훅 오류`), 예산 안에 못 돈 린터(검사 경고).
- [ ] **H7. 플러그인 자기 파일은 검사 대상이 아니다** — `.claude/convention-guard/**`, `.claude/rules/**` 는 자기 규칙에 걸리지 않음.

---

## I. 성능 예산

- [ ] **I1. Stop 훅이 예산 안에서 끝난다** [자동]
  - 구조: Stop 훅 타임아웃 150초, 린터 단계 상한 110초, 린터 **하나당** `linters.timeout` 기본 90초(순차).
  - 왜: 훅이 타임아웃으로 죽으면 아무것도 출력하지 않아 통과와 구분되지 않습니다.
  - 기대: E1 검사(린터 포함)가 30초 이내 PASS, 110초 초과 FAIL.
  - 실패하면: `linters.timeout` 을 줄이거나 무거운 린터는 CI 로.

- [ ] **I2. 규칙 수를 늘려도 비용이 선형으로 커지지 않는다** [수동, 개발 체크아웃]
  - 근거: `python3 tests/perf/run.py` — 4.0 기준(WSL2, 3.12) 게이트에 걸리는 것 없는 60개 파일 Stop 57ms, 수집 훅 1회 25~30ms, 1,000줄 파일 분석 4~7ms. 목표는 [design-4.0.md](../../design-4.0.md) §7.

---

## J. 보안·프라이버시

- [ ] **J1. 레포 설정이 임의 명령을 실행시킬 수 없다** [자동]
  - 근거: 레포 `config.yaml` 은 닫힌 키 집합만 받고, 린터 명령은 플러그인 `stacks/*.yaml` 에만 있으며 `shell=False` 리스트 인자로 실행.
  - 기대: 플러그인 스크립트에 `shell=True` 없음.
- [ ] **J2. 외부 네트워크 호출은 구조 엔진 설치뿐이다** [자동] — 실행 경로에서 네트워크 모듈을 임포트하는 것은 `scripts/lib/engine/install.py` 하나. 그것도 `files.pythonhosted.org` 의 고정 휠만 받고 `lock.json` 의 sha256 과 맞지 않으면 거부합니다. 린터는 `npx --no-install`.
- [ ] **J3. 플러그인 산출물이 레포에 잡히지 않는다** [자동] — `git status` 에 `firings.jsonl`·`convention-guard.db` 가 없음. 레포에 커밋되는 것은 `.claude/convention-guard/` 의 `config.yaml`, `dismissed.yaml`, `rules/` 뿐.
- [ ] **J4. 레포 로컬 규칙은 코드 리뷰 대상이다** [수동] — 로컬 규칙은 정규식을 추가할 수 있습니다. 폭발적 백트래킹 정규식이 들어가면 훅이 느려집니다.
- [ ] **J5. 로그에 무엇이 남는지 팀이 안다** [수동] — `firings.jsonl` 은 규칙 id·파일 경로·지문, 기각·판정 사유에는 사람이 쓴 텍스트. 5MB 에서 `firings.jsonl.1` 로 1회 로테이션, 세션 상태·원장·판정 배치는 7일 후 정리. 원장에는 에이전트가 건드린 파일과, Bash·MCP 호출 직전에 이미 수정돼 있던 파일의 내용(압축)이 남고, 세션이 7일간 쓰이지 않으면 정리됩니다.

---

## K. CI 연동

훅은 로컬 안전망이고, 강제는 CI 에서 합니다.

- [ ] **K1. PR 변경분만 검사하고, exit 2 를 성공으로 읽지 않는다** [자동 — 워크플로 파일이 있을 때]
  ```yaml
  - uses: actions/checkout@v4
    with: { fetch-depth: 0 }          # 없으면 base ref 가 없어 exit 2
  - run: python3 <플러그인>/scripts/scan.py --range "origin/${{ github.base_ref }}..HEAD" --fail-on error --no-color
  ```
  - 종료 코드: `0` 통과 / `1` 기준 강도 이상 / `2` 검사 불가. **`|| true` 로 감싸지 마세요.** 기본 브랜치 이름을 하드코딩하지 말고 `github.base_ref` 를 쓰세요.
  - [자동]: `.github/workflows/*.yml`·`.gitlab-ci.yml` 에 `scan.py` 가 있는지, `fetch-depth: 0`·`--fail-on never`·`|| true` 를 봅니다. 없으면 [수동].
- [ ] **K2. 의미 판정 규칙을 쓰면 "판정 못 함"을 통과로 읽지 않는다** [수동] — `--review --fail-on-pending`.
- [ ] **K3. 기계 판독 출력** [수동] — `--json`.
- [ ] **K4. 플러그인을 포크했다면 자체 테스트를 CI 에** [수동]
  ```bash
  python3 -m pip install -r requirements-dev.txt   # 먼저! hypothesis 가 없으면 structure/test_detect_conditions.py 가 FAIL
  python3 tests/run_all.py --repo /path/to/your-repo
  ```

---

## L. 운영 — 도입 후 2~3주

- [ ] **L1. `report` 로 2~3주 기록을 쌓는다** [수동]
- [ ] **L2. 규칙 건강도를 본다** [수동]
  ```bash
  CLAUDE_PLUGIN_DATA="<B4 의 훅 데이터 디렉터리>" python3 <플러그인>/scripts/log_report.py --repo .
  ```
  - `CLAUDE_PLUGIN_DATA` 를 빼면 다른 디렉터리를 읽어 비어 보입니다 (B4). `log_dir` 을 지정했다면 `--log <log_dir>/firings.jsonl`.
  - 보는 숫자: **수정률**, **기각률**, 의미 판정 **정밀도**, **신규**(수정이 만든 새 위반).
- [ ] **L3. 판단 기준** [수동] — 수정률 높고 기각률 낮음 → `severity: error`, `mode: fix`. 기각률 높음 → 좁히거나 끔 (`rule-tune`). 데이터 부족 → 기다림.
- [ ] **L4. 컨벤션 전부를 에이전트 컨텍스트로 내보낸다** [샌드박스][수동]
  - `python3 <플러그인>/scripts/setup.py emit --agents-md` — 적용 규칙 전부와 린터가 AGENTS.md 관리 블록으로, CLAUDE.md 에 `@AGENTS.md`. 사람이 쓴 내용은 보존 (`tests/integration/test_setup_emit.py`).

---

## M. 롤백

- [ ] **M1. 즉시 무해화**: 레포 `config.yaml` 에 `mode: report`.
- [ ] **M2. 규칙 단위 끄기**: `disable: [core/규칙id]`.
- [ ] **M3. 완전 제거**: `/plugin` 에서 disable (B2 의 범위에서). 레포에 남는 것은 `.claude/convention-guard/` 뿐.
- [ ] **M4. 캐시 정리**: B4 의 훅 데이터 디렉터리와 `~/.cache/convention-guard` 를 삭제.

---

## N. 이 체크리스트로 확인되지 않는 것

| 항목 | 상태 |
|---|---|
| Windows 네이티브(비 WSL) 훅 실행 | **미검증.** `hooks.json` 이 `python3` 를 호출합니다 (A2) |
| 모노레포 다중 스택 | 루트에서 한 번만 스택 판정 — `applies_to.files` / `exclude` 로 수동 분리 |
| 타입·호출 그래프가 필요한 판정 | 정규식의 몫이 아님. 린터 또는 의미 판정 규칙으로 |
| "턴 종료" ≠ "작업 완료" | 중간 보고로 끝난 턴도 검사될 수 있음 |
| 의미 판정 요청 무시 | 메인 에이전트가 무시 가능. 재요청 후 `review_skipped` 기록 |
| 초대형 레포(수만 파일) `--all` | 성능 측정 코퍼스는 60파일 규모 |
| 병렬 Bash 호출(`tool_use_id` 없음) | 사건 키가 도구+입력 해시라, 같은 명령이 겹치면 뒤의 Pre 가 앞의 것을 덮고 남은 Post 는 "관찰 누락(pre_missing)" 으로 알림. 남은 사건은 다음 Stop 에서 정리 |
| 스킬을 Claude 가 올바르게 따르는가 | 구조만 자동 검사. 행동은 `tests/skills/evals` 수동 평가 (B6) |
