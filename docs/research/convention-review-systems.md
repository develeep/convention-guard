# 컨벤션 강제·코드 리뷰 시스템 조사 — convention-guard 와 비교

접근일: 2026-10-08. 1차 출처(공식 문서, 공식 저장소, 퍼스트파티 changelog/blog)만 근거로 썼다. 문서에서 확인하지 못한 항목은 "확인 못 함"으로 적었다. 제품 문서는 자주 바뀌므로 아래 내용은 접근일 기준이다.

비교 기준인 convention-guard 의 동작은 이 레포의 [README.md](../../README.md), [CLAUDE.md](../../CLAUDE.md), `scripts/lib/decide.py` 머리말을 따랐다. Pre/PostToolUse 훅이 줄 출처를 원장에 기록하고, Stop 훅이 **에이전트가 쓴 줄만** 정규식 게이트 → tree-sitter 구조 조건 → (후보가 있고 캐시가 없을 때만) 서브에이전트 의미 판정 순서로 검사한다. 위반이 있으면 차단하고 수정 → 재검증 사이클을 돈다. 사이클 상한은 `limits.max_verify_attempts`·`limits.max_consecutive_blocks` 이다.

---

## 요약

1. **에이전트용 "규칙" 기능은 대부분 강제가 아니라 프롬프트 컨텍스트다.** Cursor Rules, Copilot custom instructions, Cline·Roo·Windsurf rules, Aider `CONVENTIONS.md`, AGENTS.md 가 모두 문서상 "컨텍스트에 넣는다"로 설명된다([Cursor](https://cursor.com/docs/context/rules), [Cline](https://docs.cline.bot/features/cline-rules), [Windsurf](https://docs.devin.ai/desktop/cascade/memories), [Aider](https://aider.chat/docs/usage/conventions.html)). convention-guard 가 전제로 삼는 "적어 둬도 잊힌다"는 문제를 이 도구들은 구조적으로 해결하지 않는다.
2. **턴 종료 시 차단하고 계속 진행시키는 훅은 이제 주요 에이전트 대부분에 있다.** Claude Code `Stop`, Codex `Stop`, Copilot CLI `agentStop`(연속 8회 상한), Cursor `stop` 의 `followup_message`(기본 5회 상한), Kiro `Stop` 이 그렇다. Windsurf Cascade 는 응답 뒤에 계속 진행시키는 훅이 없다. 따라서 convention-guard 의 차단 메커니즘은 Claude Code 전용 기술이 아니고, 다른 에이전트로 옮길 수 있다.
3. **보안 벤더들이 이미 "에이전트가 쓴 파일을 훅으로 검사 → 에이전트가 스스로 고침"을 제품으로 내놓았다.** [Semgrep Guardian](https://docs.semgrep.dev/semgrep-guardian/overview)과 [SonarQube CLI 의 `sonar integrate claude`](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)가 그렇다. 둘 다 PostToolUse 시점에 **파일 단위**로 검사하고, 결과를 에이전트에 넘기기만 한다. 줄 출처 구분과 Stop 차단은 확인하지 못했다. Sonar 는 소스로 확인했다. Stop 훅이 없고, 재검증은 `CLAUDE.md` 지시문에만 있으며 상한이 없다([상세](sonarqube-cli-integrate-claude.md)). Guardian 의 Claude Code 플러그인은 고정 규칙셋만 쓰고 조직 Policy 를 적용하지 않는다고 명시한다.
4. **줄 단위 AI 출처 기록은 따로 존재하지만 검사와 결합된 사례는 찾지 못했다.** [git-ai](https://usegitai.com/docs/get-started/how-git-ai-works)는 Edit/Write/Bash 훅으로 AI 가 쓴 줄을 체크포인트하고 git notes 에 남긴다. 다만 문서상 리뷰·검사는 하지 않는다. [Agent Trace](https://agent-trace.dev/)(Cursor 주도 RFC v0.1.0)는 `human/ai/mixed/unknown` 줄 범위를 담는 포맷만 정의한다. SonarQube AI Code Assurance 는 **프로젝트 단위** 플래그다([문서](https://docs.sonarsource.com/sonarqube-server/quality-standards-administration/ai-code-assurance/quality-gate-for-agentic-ai)). 이번 조사 범위에서는 "에이전트가 쓴 줄만 검사"가 convention-guard 의 가장 뚜렷한 차별점이다.
5. **"변경분만" 검사는 CI 도구에서 이미 표준이다.** reviewdog `-filter-mode=added`(기본값), Semgrep diff-aware(`SEMGREP_BASELINE_REF`), CodeQL diff-informed analysis, SonarQube new code period, Sourcery review rules(수정된 줄만), Ellipsis(아직 리뷰하지 않은 커밋만), Bugbot(이전 리뷰 이후 변경만)이 그렇다. 다만 모두 **git diff 기준**이어서, 같은 브랜치 안에서 사람이 쓴 줄과 에이전트가 쓴 줄을 구분하지 못한다.
6. **AI PR 리뷰어는 PR/푸시마다 LLM 을 항상 돌리는 과금 모델이다.** Claude Code Review 는 리뷰당 평균 $15–25([문서](https://code.claude.com/docs/en/code-review)), Copilot code review 는 Balanced 기준 $0.25–5([문서](https://docs.github.com/en/copilot/concepts/agents/code-review))다. 결정론적 탐지 뒤에만 LLM 을 쓰는 게이팅은 Semgrep Assistant 가 가장 가깝다. diff-aware 스캔당 새 finding 최대 10개만 자동 분석한다([문서](https://docs.semgrep.dev/semgrep-assistant/overview)). convention-guard 의 "후보 없으면 AI 호출 0"은 이 계열에서도 드문 설계다.
7. **오탐 처리 방식이 갈린다.** 상용 AI 리뷰어는 반응·답글·커밋에서 **학습**한다(Greptile: 3회 무시하면 억제, Bugbot learned rules, Qodo 는 반복 기각을 조용히 함, CodeRabbit learnings). 규칙 기반 도구는 **베이스라인/억제 파일**(ESLint `eslint-suppressions.json`, Betterer `.betterer.results`, Ruff `--add-noqa`)이나 인라인 주석을 쓴다. convention-guard 의 코드 지문 키 기각은 결정론적이고 감사 가능하다. 대신 일반화(학습)는 `rule-tune` 같은 수동 경로에 맡긴다.
8. **대부분의 AI 리뷰어는 기본이 코멘트만이다.** Claude Code Review 의 check run 은 항상 neutral 이라 머지를 막지 않는다. Copilot 은 기본적으로 승인에 포함되지 않는다. 막을 수 있는 경우는 CodeRabbit pre-merge check `error` 모드 + Request Changes Workflow, Continue checks(GitHub status check 실패), Sourcery status check, Danger `fail()` 이다. 에이전트 **턴 안에서** 막고 고치게 하는 것은 Copilot coding agent 의 자체 검증(CodeQL·secret scanning 후 스스로 수정)과 Guardian/Sonar 훅 정도다.
9. **convention-guard 에 없고 다른 곳에 있는 것.** 리뷰 지침 파일 자동 흡수(CodeRabbit 은 `.cursorrules`·`CLAUDE.md`·`copilot-instructions.md` 를 자동으로 읽음), 미사용 억제 탐지(ESLint `--prune-suppressions`), 반응 기반 자동 억제(Greptile), "기존 코드 버그" 별도 등급(Claude Code Review 의 Pre-existing), 크로스툴 디렉터리(Continue 의 `.agents/checks/`), 출처 포맷 표준(Agent Trace).

---

## 비교표

범례: **트리거** 언제 도는가 / **규칙 형식** / **범위** 무엇을 보는가 / **AI 게이팅** LLM 을 언제 부르는가 / **오탐 처리** / **루프** 코멘트만인가, 막고 고치게 하는가.

| 시스템 | 트리거 | 규칙 형식 | 범위 | AI 게이팅 | 오탐 처리 | 루프 |
| --- | --- | --- | --- | --- | --- | --- |
| **convention-guard** | 에이전트 훅(Pre/PostToolUse 기록, Stop 검사) + CLI `scan.py` | YAML(정규식 앵커 + tree-sitter 구조 조건 + 선택적 의미 판정) | **에이전트가 쓴 줄**(원장), CLI 는 staged/range/files/all | 후보가 있고 판정 캐시가 없을 때만 서브에이전트 | 코드 지문 키 기각(`dismissed.yaml`), 판정 캐시 | Stop 차단 → 수정 → 재검증(상한 있음) |
| Claude Code hooks | 에이전트 이벤트(Stop, PreToolUse 등) | 셸/HTTP/MCP/prompt/agent 훅 | 훅 구현에 달림 | `prompt`/`agent` 훅은 발생할 때마다 호출 | 없음(직접 구현) | Stop `decision: block` 으로 계속 진행 |
| hookify (Claude Code 공식 플러그인) | 에이전트 이벤트(bash/file/stop) | Markdown + YAML frontmatter, 정규식 조건 | 도구 입력(new_text 등) | 없음 | 규칙 on/off | warn / block |
| Semgrep Guardian | PostToolUse(파일 쓰기마다) | Semgrep 규칙(플러그인은 고정 규칙셋) | 에이전트가 쓴 **파일** | 확인 못 함 | 확인 못 함 | finding 을 에이전트에 전달, 재생성은 에이전트 판단 |
| SonarQube CLI integrate claude | PostToolUse(Edit\|Write), PreToolUse(Read 시크릿), UserPromptSubmit(시크릿), 턴 끝은 CLAUDE.md 지시문 | Sonar 규칙(서버 측 Vortex 분석) | 편집된 파일 전체(턴 끝은 git 변경 집합) | 정적 분석(LLM 아님) | 로컬 장치 없음(서버 상태 반영은 확인 못 함) | `additionalContext` 로 전달·차단 안 함, 재검증은 지시문("Repeat until clean", 상한 없음), 시크릿만 차단([상세](sonarqube-cli-integrate-claude.md)) |
| Copilot coding agent 자체 검증 | 에이전트가 PR 끝내기 전 | CodeQL, Advisory DB, secret scanning, Copilot review | 에이전트가 쓴 코드 | review 단계는 LLM | 확인 못 함 | 문제가 있으면 끝내기 전에 스스로 수정 시도 |
| Copilot CLI hooks | `agentStop`, `preToolUse` 등 | 셸 명령(`.github/hooks/*.json`) | 훅 구현에 달림 | 없음 | 없음 | `block` 으로 계속 진행, 연속 8회 상한 |
| Cursor hooks | `afterFileEdit`, `stop` 등 | 셸 스크립트 | 훅 구현에 달림 | 없음 | 없음 | `followup_message`, 기본 `loop_limit` 5 |
| Codex hooks | `Stop`, `PostToolUse`(apply_patch 포함) | 셸 명령 | 훅 구현에 달림 | 없음 | 없음 | `Stop` block 이면 이어서 진행 |
| Kiro hooks | PostFileSave, Stop, Pre/PostToolUse 등 | JSON + 셸 명령 또는 에이전트 프롬프트 | 이벤트 대상 | agent action 은 매번 | 확인 못 함 | 확인 못 함 |
| Windsurf Cascade hooks | pre/post_write_code 등 12개 | 셸 명령 | 이벤트 대상 | 없음 | 없음 | pre 훅만 차단, 응답 뒤 계속 진행 불가 |
| Cursor Rules / AGENTS.md / Copilot instructions / Cline / Roo / Windsurf rules / Aider | 매 요청(컨텍스트 주입) | 자연어 Markdown(+ glob frontmatter) | glob 또는 디렉터리 근접성 | 항상(프롬프트의 일부) | 규칙 토글 | 강제 없음 |
| Aider lint/test | 매 편집 후 | 외부 린터/테스트 명령 | 편집한 파일 | 수정에 LLM | 확인 못 함 | 0이 아닌 종료 코드면 자동으로 고치기 시도 |
| Continue checks | PR(CI), 로컬 `/check` 스킬 | Markdown + frontmatter(자연어 프롬프트) | PR diff(에이전트가 파일을 더 읽을 수 있음) | 체크마다 매번 | 프롬프트 수정 | GitHub status check 실패 + 제안 diff |
| CodeRabbit | PR, CLI/Claude Code 플러그인 | 자연어 path instructions, ast-grep, pre-merge custom checks | PR diff, CLI 는 uncommitted/base | PR 마다 | learnings, `[IGNORED]` 체크박스 | 코멘트, `error` 모드면 머지 차단 |
| Greptile | PR | 자연어 규칙(JSON/MD, scope glob) | PR | PR 마다 | 반응·답글·커밋 학습, 반복 무시 억제 | 코멘트(차단은 확인 못 함) |
| Qodo / PR-Agent | PR(자동/명령), CLI | best practices / Review Standards, Rule Miner | 전체 레포 컨텍스트 + PR | 도구당 LLM 1회(PR-Agent) | PR 히스토리 기반 우선순위, 반복 기각은 조용히 | 코멘트·제안 |
| Sourcery | PR 열림/푸시 | 자연어 review rules(3,000자, path glob) | **수정된 줄만** | PR 마다 | 확인 못 함 | 인라인 코멘트, status check 로 머지 차단 가능(GitHub) |
| Graphite Agent | 새 PR 자동 | UI 자연어 custom prompt, 파일 기반 규칙 | PR | PR 마다 | comment exclusions, up/downvote 분석 | 코멘트 + 수정 제안 |
| Ellipsis | PR 푸시마다 | `.ellipsis/code-review.yaml` 리뷰어(프롬프트) 최대 8개 | **아직 리뷰하지 않은 커밋** | 리뷰어마다(예산 있음) | 확인 못 함 | 코멘트 |
| Cursor Bugbot | PR 업데이트 자동 또는 언급 | `.cursor/BUGBOT.md`, team rules, learned rules | 이전 Bugbot 리뷰 이후 변경 | PR 마다 | `@cursor remember`, learned rules | 코멘트, Autofix 는 Cloud Agent 가 푸시 |
| Codex review | `@codex review` 또는 자동 | AGENTS.md `## Code Review Rules` | PR | PR 마다 | 확인 못 함 | P0/P1 만 코멘트, `@codex fix` 로 수정 푸시 |
| Gemini Code Assist | PR 열림 자동, `/gemini review` | `.gemini/styleguide.md`, `config.yaml` | PR | PR 마다 | 심각도 임계값, ignore_patterns | 코멘트 |
| Copilot code review | 수동 요청 또는 ruleset 자동 | `copilot-instructions.md`, `*.instructions.md`(applyTo) | PR | 리뷰마다(AI credits) | 확인 못 함 | 코멘트(승인 기능은 preview) |
| Claude Code Review | PR 열림/푸시/`@claude review` | `REVIEW.md`, `CLAUDE.md` | diff + 주변 코드 | 리뷰마다(평균 $15–25) | 검증 단계로 오탐 필터, 👍/👎 | 코멘트, check run 은 항상 neutral |
| claude-code-action | `@claude`, 워크플로 프롬프트 | 워크플로 프롬프트 | 설정에 달림 | 실행마다(자기 API 키) | — | 코멘트 또는 커밋 |
| Semgrep CE/AppSec | CI, CLI | YAML 패턴 규칙 | 전체 또는 diff-aware(베이스라인) | Assistant 는 finding 이 있을 때만 | `nosemgrep`, Assistant autotriage | 코멘트·CI 실패, autofix |
| ast-grep | CLI/CI/LSP | YAML(pattern, kind, inside/has/not) | 지정 경로 | 없음 | 확인 못 함(아래 본문) | 종료 코드, fix |
| CodeQL | CI(code scanning) | QL 쿼리 | 전체 또는 diff-informed(변경 줄만) | 없음(Autofix 는 별도) | 알림 dismiss | 알림/체크 |
| Danger JS | CI(PR) | JS/TS dangerfile | 변경 파일·PR 메타데이터 | 없음 | 코드로 처리 | `fail()` 은 차단, `warn()` 은 경고 |
| reviewdog | CI | 아무 린터 출력 | `added`(기본)/`diff_context`/`file`/`nofilter` | 없음 | 필터 모드 | PR 코멘트, `-fail-level` |
| SonarQube | CI | Sonar 규칙 | new code period / PR | 없음(별도 AI 기능 있음) | 이슈 상태 변경 | 품질 게이트(new code 조건) |
| ESLint bulk suppressions / Betterer / Ruff add-noqa | 로컬/CI | 각 린터 규칙 | 기존 위반을 동결하고 새 위반만 | 없음 | 억제 파일 / 결과 스냅샷 / 인라인 noqa | 종료 코드 |
| pre-commit / lint-staged | git pre-commit | 훅 설정 YAML / glob → 명령 | staged 파일 | 없음 | — | 커밋 차단 |
| git-ai / Agent Trace | 에이전트 훅 / 포맷 | — | 줄 단위 AI 출처 | 없음 | — | 검사 없음(기록만) |

---

## 카테고리별 상세

### 1. AI 에이전트 가드레일·훅 시스템

#### Claude Code hooks
- 이벤트는 `PreToolUse`(차단 가능), `PostToolUse`, `PostToolUseFailure`, `Stop`, `SubagentStop`, `SessionStart` 등이다([hooks reference](https://code.claude.com/docs/en/hooks)).
- `Stop` 은 `decision: "block"` + `reason` 또는 종료 코드 2로 "Claude 가 멈추지 못하게 하고 대화를 이어 가게" 한다([같은 문서](https://code.claude.com/docs/en/hooks)).
- `stop_hook_active` 는 "Claude Code is already continuing as a result of a stop hook" 일 때 true 다. 문서는 이 값을 확인해 "never resolve" 조건에서 계속 막지 않도록 하라고 안내한다([같은 문서](https://code.claude.com/docs/en/hooks)). convention-guard 는 이 값을 `Request.continuing` 으로 받는다.
- 훅 타입은 command, http, mcp_tool, prompt, agent 다섯 가지다. `prompt` 훅은 "send a prompt to a Claude model for single-turn evaluation" 이고, `agent` 훅은 Read/Grep/Glob 을 쓰는 서브에이전트이며 실험적이다([같은 문서](https://code.claude.com/docs/en/hooks)). 이 둘은 발생할 때마다 모델을 호출한다. convention-guard 의 게이팅과 대비되는 기본 선택지다.

#### Claude Code 공식 플러그인 (anthropics/claude-code `plugins/`)
- **hookify**: `.claude/hookify.*.local.md` 에 YAML frontmatter(`event: bash|file|stop|all`, `pattern` 정규식, `conditions`, `action: warn|block`)로 규칙을 정의한다. `/hookify` 는 대화를 분석해 사용자가 교정한 행동을 규칙으로 만든다([README](https://github.com/anthropics/claude-code/blob/main/plugins/hookify/README.md)). 도구 **입력 텍스트**에 정규식을 거는 방식이다. 줄 출처, 구조 조건, 재검증은 없다.
- **security-guidance**: "PreToolUse - Monitors 9 security patterns" 경고 훅이다([plugins README](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)).
- **code-review** 플러그인: "5 parallel Sonnet agents for CLAUDE.md compliance, bug detection, …"와 confidence 점수로 오탐을 거른다([plugins README](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)).
- **ralph-wiggum**: Stop 훅이 종료를 가로채 같은 작업을 반복시킨다([plugins README](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)). Stop 차단을 루프에 쓰는 공식 예시다.

#### Semgrep Guardian (Claude Code/Codex 플러그인)
- "Your coding agent writes or edits a file. A hook … triggers a Semgrep scan of what the agent just generated. If Semgrep returns findings, the agent receives them and is prompted to regenerate the code. The agent decides whether to regenerate."([overview](https://docs.semgrep.dev/semgrep-guardian/overview))
- 규칙: "The recommended Claude Code and Codex plugins run a fixed ruleset and don't apply your organization's Policies. The local CLI integrations do."([같은 문서](https://docs.semgrep.dev/semgrep-guardian/overview))
- 범위가 파일 전체인지 새 줄만인지는 확인 못 함. Stop 차단이나 재검증도 확인 못 함.

#### SonarQube CLI `sonar integrate claude`
- UserPromptSubmit·PreToolUse 훅으로 시크릿을 검사해 노출 작업을 차단한다. "a shared PostToolUse hook for fast STANDARD analysis after each edit or write" 와 PostToolUseFailure 훅도 설치한다([integrations](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)).
- 전제: "Your project must be analyzed in your CI pipeline on a long-lived branch before you can use Vortex analysis"([how-to](https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code)).
- 결과는 `hookSpecificOutput.additionalContext` 로 돌려주고 막지 않는다. 범위는 편집된 파일 전체이고, 파일 내용을 서버의 Vortex API 로 보내 STANDARD 분석을 받는다. Stop 훅은 없다. 턴 끝 DEEP 분석과 "Repeat until clean" 재검증은 `CLAUDE.md` 지시문이 맡고, 상한은 없다. 시크릿 훅은 `decision: block`(프롬프트)과 `permissionDecision: deny`(Read)로 막는다. CLI 에는 오탐 기각 장치가 없다. 근거는 sonarqube-cli 1.9.0.15656 소스다([상세 조사](sonarqube-cli-integrate-claude.md)).

#### GitHub Copilot (coding agent 자체 검증, CLI hooks)
- coding agent 는 자기가 쓴 코드를 CodeQL, GitHub Advisory Database, secret scanning, Copilot code review 로 검사한다. "If the security validation or code review tools find any problems, Copilot attempts to resolve them before finishing the pull request"([changelog 2025-10-28](https://github.blog/changelog/2025-10-28-copilot-coding-agent-now-automatically-validates-code-security-and-quality/)). 2026-06에는 Claude·Codex 같은 서드파티 에이전트로 확대됐다([changelog 2026-06-09](https://github.blog/changelog/2026-06-09-security-validation-for-third-party-coding-agents/)). **에이전트 산출물을 끝내기 전에 검사하고 스스로 고치게 한다**는 점에서 convention-guard 와 같은 루프다. 다만 팀 컨벤션 규칙이 아니라 보안·품질 도구 기준이다.
- Copilot hooks: `.github/hooks/*.json`. `agentStop`/`subagentStop` 의 `decision: "block"` 은 "forces another agent turn using reason as the prompt" 이다. "After 8 consecutive block continuations, the CLI overrides the hook and ends the turn anyway"([hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)).

#### Cursor (Rules, hooks)
- Rules: `.cursor/rules/*.mdc`, 적용 방식은 Always Apply / Apply Intelligently / Apply to Specific Files(glob) / Manual. 문서는 "contents are included at the start of the model context" 라고 설명하고, Agent 에만 적용되며 Tab·Inline Edit 에는 적용되지 않는다. AGENTS.md 도 지원한다([rules](https://cursor.com/docs/context/rules)).
- hooks: `afterFileEdit`, `stop` 등. `stop` 의 `followup_message` 는 "Cursor will automatically submit it as the next user message", 기본 `loop_limit` 은 5다([hooks](https://cursor.com/docs/agent/hooks)).

#### OpenAI Codex hooks
- 이벤트: SessionStart/End, Pre/PostToolUse, UserPromptSubmit, SubagentStart/Stop, Stop 등. `Stop` 의 "decision: 'block' … tells Codex to continue", `stop_hook_active` 를 제공하고, PostToolUse 는 `apply_patch` 를 포함한다([hooks](https://learn.chatgpt.com/docs/hooks)). Claude Code 의 훅 모델과 거의 같아서 convention-guard 의 수집/Stop 구조를 이식할 여지가 크다.

#### Kiro hooks
- 트리거 PostFileSave, PostFileCreate, Stop, PromptSubmit, Pre/PostToolUse. 액션은 셸 명령 또는 "Agent actions - Inject prompts into the conversation"([hooks](https://kiro.dev/docs/hooks/)). Stop 에서 계속 진행시키는 의미가 있는지는 확인 못 함.

#### Windsurf (Cascade) rules·hooks
- rules: `.devin/rules/`(구 `.windsurf/rules/`), always_on / model_decision / glob / manual. 워크스페이스 규칙은 파일당 12,000자([memories](https://docs.devin.ai/desktop/cascade/memories)).
- hooks: 12개 이벤트. "Only pre-hooks … can block actions using exit code 2". `post_cascade_response` 는 감사/로깅용이고 응답을 계속 진행시키는 훅은 없다([hooks](https://docs.devin.ai/desktop/cascade/hooks)). 따라서 convention-guard 식 턴 종료 차단은 Windsurf 에서 그대로 구현할 수 없다.

#### Cline / Roo Code rules
- Cline: `.clinerules/`, frontmatter `paths` glob 으로 조건부 활성화한다. "Cline reads rules as context". `.cursorrules`·`.windsurfrules`·AGENTS.md 도 감지한다([Cline rules](https://docs.cline.bot/features/cline-rules)).
- Roo: `.roo/rules/`, `.roo/rules-{mode}/` 를 "appending their content to the system prompt", AGENTS.md 를 자동으로 로드한다([Roo custom instructions](https://roocodeinc.github.io/Roo-Code/features/custom-instructions)).

#### Aider
- conventions: `/read CONVENTIONS.md` 로 읽기 전용 + 프롬프트 캐시([conventions](https://aider.chat/docs/usage/conventions.html)).
- lint/test: 편집한 파일을 자동으로 lint 하고 "Aider will try and fix any errors if the command returns a non-zero exit code"([lint-test](https://aider.chat/docs/usage/lint-test.html)). **편집 → 결정론 검사 → 자동 수정 루프**의 오래된 선례다. 다만 범위는 편집한 파일 전체이고, 줄 출처와 기각은 없다.

#### Continue
- `.continue/checks/` 또는 `.agents/checks/` 의 Markdown(frontmatter `name`, `description`, `model`). 본문이 에이전트 시스템 프롬프트가 된다. "examines the pull request diff, and produces a pass or fail verdict"([reference](https://github.com/continuedev/continue/blob/main/docs/checks/reference.mdx)). 결과는 GitHub status check 로 나오고, 실패하면 제안 diff 가 붙는다(검색 결과의 docs.continue.dev 요약. 해당 URL 직접 접근은 404 라 저장소 문서로 대신 확인).
- 로컬: `/check` 스킬이 "runs each one as a sub-agent against your current branch". AGENTS.md 에 "run /check and fix any failures" 를 넣으라고 권한다([running-locally](https://github.com/continuedev/continue/blob/main/docs/checks/running-locally.mdx)). 체크마다 LLM 을 무조건 호출하고 정규식 게이트는 없다.

#### AGENTS.md
- "a README for agents". 형식 제약이 없는 Markdown 이고, 가장 가까운 파일이 우선한다. Linux Foundation 산하 Agentic AI Foundation 이 관리한다([agents.md](https://agents.md/)). Copilot([문서](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)), Cursor, Roo, Cline, Codex review 가 읽는다.

### 2. AI PR 리뷰어

#### CodeRabbit
- 규칙: path instructions(glob + 자연어), AST 기반 지침(ast-grep), code guidelines, custom checks([review instructions](https://docs.coderabbit.ai/guides/review-instructions)). `.cursorrules`, `CLAUDE.md`, `.github/copilot-instructions.md` 같은 에이전트 설정 파일을 자동으로 감지해 읽는다([knowledge base](https://docs.coderabbit.ai/integrations/knowledge-base)).
- 학습: "learns your team's review preferences from natural-language chat"([knowledge base](https://docs.coderabbit.ai/integrations/knowledge-base)).
- 차단: pre-merge custom checks 의 모드는 `off`/`warning`(기본)/`error` 다. `error` + Request Changes Workflow 면 머지가 막힌다. "Ignore failed checks" 체크박스를 누르면 해당 PR 만 풀리고 `[IGNORED]` 태그가 남는다([pre-merge checks](https://docs.coderabbit.ai/pr-reviews/pre-merge-checks)).
- 에이전트 연동: Claude Code 플러그인 `/coderabbit:coderabbit-review --uncommitted|--committed|--base`. Claude Code 가 구현 → 리뷰 → 지적을 순서대로 고치는 루프를 문서가 제시한다([Claude Code integration](https://docs.coderabbit.ai/cli/claude-code-integration)). 리뷰를 명시적으로 불러야 하고, Stop 훅 강제는 문서에 없다.

#### Greptile
- 규칙: `.greptile/`(config.json 의 `rule`/`scope`/`severity`/`id`, 또는 rules.md), `greptile.json`, 대시보드. scope 는 glob 이다([custom standards](https://www.greptile.com/docs/code-review/custom-standards)).
- 학습: 👍/👎, 답글, "compares initial and final commits", "Missing semicolons (suppressed after 3 ignores)", 팀 행동으로 규칙을 자동 추론한다([memory and learning](https://www.greptile.com/docs/how-greptile-works/memory-and-learning)).
- 머지 차단 메커니즘: 확인 못 함.

#### Qodo (Qodo Merge) / PR-Agent
- Qodo: PR 게시/푸시 시 자동. Review Standards 와 "Rule Miner … turns recurring patterns from your team's own PR history into new enforced rules". "quieting ones you've consistently dismissed". "analyzes the full repository, not just the changed lines"([code review](https://docs.qodo.ai/code-review)). 차단 여부는 확인 못 함.
- PR-Agent(MIT, 커뮤니티 이관): `/describe`, `/review`, `/improve`, `/ask`. 각 도구는 "a single LLM call (~30 seconds, low cost)" 이다([repo](https://github.com/qodo-ai/pr-agent)).

#### Sourcery
- PR 열림·푸시 시 자동이고 draft·봇·과대 diff 는 건너뛴다. status check 로 머지를 막을 수 있다(GitHub)([overview](https://docs.sourcery.ai/Code-Review/Overview/)).
- review rules: 자연어 3,000자, Path patterns glob. 수정된 줄만 본다는 내용은 WebFetch 요약에 있었으나 원문 문장으로는 확인 못 함([review rules](https://docs.sourcery.ai/reviews/review-rules/)). 기각 학습은 확인 못 함.

#### Graphite Agent (구 Diamond)
- 활성화하면 "automatically review all new pull requests"([setup](https://graphite.com/docs/ai-reviews-setup)). 푸시마다인지는 확인 못 함.
- UI custom prompt 를 권장한다(Rule → Bad → Good → Reasoning). comment exclusions 와 up/downvote·수용률 분석이 있다([customization](https://graphite.com/docs/ai-review-customization)).

#### Ellipsis
- `.ellipsis/code-review.yaml` 에 리뷰어를 최대 8개 둔다. 리뷰어마다 prompt·model·budget 이 따로다. "A reviewer only sees commits it has not reviewed before, and a comment on a line outside those commits is held back." 리뷰어당 30개, 리뷰당 60개 코멘트 상한이 있다([code review](https://www.ellipsis.dev/docs/agents/code-review)). **"이미 본 것은 다시 보지 않는다"** 는 범위 제어가 convention-guard 의 사이클·캐시와 닮았다. 학습 기능은 확인 못 함.

#### Cursor Bugbot
- PR 업데이트마다 자동 또는 `bugbot run`. 규칙 원천은 team rules, `.cursor/BUGBOT.md`, learned rules(`@cursor remember`). 기본 범위는 "only the changes since the previous Bugbot review". Autofix 는 "automatically spawns a Cloud Agent to fix bugs"([bugbot](https://cursor.com/docs/bugbot)).

#### OpenAI Codex code review
- `@codex review` 또는 자동. AGENTS.md 의 `## Code Review Rules` 를 "the file closest to the code"에서 찾는다. P0/P1 만 지적하고, `@codex fix the P1 issue` 로 수정을 푸시한다([GitHub 통합](https://learn.chatgpt.com/docs/third-party/github)).

#### Gemini Code Assist on GitHub
- PR 을 열면 자동 리뷰하고, `/gemini review` 로도 부른다([use on GitHub](https://docs.cloud.google.com/gemini/docs/code-review/use-code-assist-github)). `.gemini/config.yaml` 의 `comment_severity_threshold`, `ignore_patterns`(glob), `max_review_comments`, `.gemini/styleguide.md` 로 조정한다([customize](https://docs.cloud.google.com/gemini/docs/code-review/customize-repo-review)).

#### GitHub Copilot code review
- 수동 요청 또는 personal setting·ruleset 으로 자동. 기본은 코멘트만이고, 승인 리뷰 제출은 public preview 다. Lite $0.05–1, Balanced $0.25–5([code review](https://docs.github.com/en/copilot/concepts/agents/code-review)). `.github/instructions/*.instructions.md` 의 `applyTo` glob, `excludeAgent: "code-review"` 를 지원한다([custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)).

#### Anthropic: Claude Code Review / claude-code-action / `/code-review`
- Claude Code Review(managed): 여러 에이전트가 병렬로 찾고 "a verification step checks candidates against actual code behavior to filter out false positives". 심각도는 Important / Nit / **Pre-existing**("a bug that exists in the codebase but was not introduced by this PR")이다. check run 은 "always completes with a neutral conclusion so it never blocks merging". CLAUDE.md 위반은 "newly introduced violations as nits"로 보고, `REVIEW.md` 로 심각도·nit 상한·건너뛸 경로·"Re-review convergence"를 조정한다. 리뷰당 평균 $15–25([code review](https://code.claude.com/docs/en/code-review)).
- 로컬 `/code-review`: 브랜치 커밋 + 미커밋 변경을 백그라운드 서브에이전트로 리뷰하고, `--fix` 로 적용한다([같은 문서](https://code.claude.com/docs/en/code-review)). 명시적으로 불러야 하고 차단은 없다.
- claude-code-action: `@claude` 언급 또는 워크플로 프롬프트. 자기 러너와 자기 API 키로 돌고, 코드 변경 구현도 가능하다([repo](https://github.com/anthropics/claude-code-action)).

### 3. 사용자 규칙을 쓰는 정적 분석

#### Semgrep
- 규칙: YAML `pattern`, `pattern-not`, `pattern-inside`/`pattern-not-inside`, `pattern-regex`, `metavariable-regex`, `fix`, `paths` glob([rule syntax](https://docs.semgrep.dev/writing-rules/rule-syntax)). convention-guard 의 정규식 + `not_in`/`in_scope` 구조 조건과 가장 가까운 선언형 문법이다.
- diff-aware: "A diff-aware scan shows only findings caused by changes in files starting from a specific Git baseline". `SEMGREP_BASELINE_REF` 를 쓰고, 이때는 cross-file 분석을 하지 않는다([CI 설정](https://docs.semgrep.dev/deployment/customize-ci-jobs)).
- Assistant(Multimodal): autotriage, noise filtering, Memories(맞춤 지침), AI Autofix. 자동 분석 대상은 full scan 이면 Critical/High + High/Medium confidence, diff-aware 면 "up to 10 new findings … per scan"([overview](https://docs.semgrep.dev/semgrep-assistant/overview)). **결정론 탐지 후에만 LLM 을 쓰는 게이팅**의 대표 사례다.

#### ast-grep
- YAML 규칙: atomic(`pattern`, `kind`, `regex`), relational(`inside`, `has`, `follows`, `precedes`), composite(`all`, `any`, `not`, `matches`). 실행은 `ast-grep scan`([rule config](https://ast-grep.github.io/guide/rule-config.html)). tree-sitter 기반이라 convention-guard 구조 엔진과 기반이 같다. 억제 주석 방식은 이번에 원문으로 확인 못 함.

#### CodeQL
- diff-informed analysis: "reports only alerts in lines you added or changed". 변경 범위를 `path`/`startLine`/`endLine` 목록으로 넘긴다. overlay analysis 는 기본 브랜치 DB 를 재사용한다([incremental analysis](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/incremental-analysis)).

#### Danger JS
- CI 에서 `dangerfile.js/ts` 를 실행한다. `danger.git.modified_files` 등으로 PR 변경을 읽고 `fail()`(차단)/`warn()`/`message()`/`markdown()` 을 낸다([danger.systems](https://danger.systems/js/)). 규칙이 곧 코드다.

#### reviewdog
- `-filter-mode`: `added`(기본, "added/modified lines"), `diff_context`(변경 줄 ±N), `file`, `nofilter`. `-fail-level`, reporter 는 `local`/`github-pr-review`/`github-check`([README](https://github.com/reviewdog/reviewdog)). 어떤 린터든 "변경 줄만"으로 거르는 범용 어댑터다. convention-guard 의 린터 위임("변경 줄에 걸린 것만")과 같은 발상이다.

#### SonarQube "Clean as You Code"
- new code 정의: Previous Version / Number of Days(기본 30, 최대 90) / Specific Analysis / Reference Branch. PR 에서는 대상 브랜치 대비 변경을 new code 로 본다. 품질 게이트는 new code 조건 중심이다([about new code](https://docs.sonarsource.com/sonarqube-server/latest/user-guide/about-new-code/)).
- AI Code Assurance: "Sonar way for agentic AI" 게이트(new code 신규 이슈 0, 커버리지 ≥80%, 중복 ≤3% 등). 프로젝트를 "contains AI code"로 표시하는 **프로젝트 단위** 방식이다([quality gate for agentic AI](https://docs.sonarsource.com/sonarqube-server/quality-standards-administration/ai-code-assurance/quality-gate-for-agentic-ai)).

#### ESLint bulk suppressions / Betterer / Ruff
- ESLint: `--suppress-all`/`--suppress-rule` → `eslint-suppressions.json`(커밋 대상). "While the rule will be enforced for new code, the existing violations will not be reported." 위반이 해소되면 남은 억제를 에러로 알리고 `--prune-suppressions` 로 정리한다. `"error"` 규칙만 억제한다([suppressions](https://github.com/eslint/eslint/blob/main/docs/src/use/suppressions.md)). 파일 내부 형식(위치 기반인지 개수 기반인지)은 원문에서 확인 못 함.
- Betterer: 현재 이슈를 스냅샷으로 잡아 `.betterer.results` 에 두고 "fails if things get worse" 하는 래칫이다([repo](https://github.com/phenomnomnominal/betterer)).
- Ruff: 베이스라인 기능은 없다(이슈 [#1149](https://github.com/astral-sh/ruff/issues/1149) 2026-10-08 기준 OPEN). 대신 `--add-noqa`/`--add-ignore` 로 기존 위반 줄에 억제 주석을 일괄 추가한다([linter](https://docs.astral.sh/ruff/linter/)).

#### pre-commit / lint-staged
- pre-commit: "only runs on the staged contents of files by temporarily stashing the unstaged changes". CI 는 `--all-files` 또는 `--from-ref/--to-ref`([pre-commit.com](https://pre-commit.com/)).
- lint-staged: staged 파일을 glob 으로 걸러 명령을 실행하고, 부분 staged 파일의 unstaged 변경은 숨겼다가 되돌린다([repo](https://github.com/lint-staged/lint-staged)). 범위가 **파일** 단위라 줄 단위 필터는 없다.

### 4. 줄 단위 출처 / "에이전트가 쓴 코드만" / 차단→수정→재검증

#### git-ai
- "After each `Edit`, `Write`, or `Bash` tool call, the hook runs `git ai checkpoint` to mark the lines just written as AI-authored." 사람이 에이전트 실행 사이에 고친 줄은 human 으로 체크포인트한다. 커밋 시 `refs/notes/ai` 에 authorship log 를 붙이고, rebase·squash·cherry-pick 때 notes 를 다시 쓴다([how git-ai works](https://usegitai.com/docs/get-started/how-git-ai-works)).
- 메커니즘(도구 호출 단위 체크포인트, 사이의 사람 편집 분리)은 convention-guard 원장과 거의 같다. 차이는 둘이다. git-ai 는 **커밋을 넘어 출처를 유지**하고(convention-guard 는 세션 원장), **검사는 하지 않는다**.

#### Agent Trace
- "open specification for tracking AI-generated code", v0.1.0 RFC(2026-01). 줄 범위(`start_line`/`end_line`)와 기여자 유형 `human`/`ai`/`mixed`/`unknown` 을 쓰고, 저장 위치는 규정하지 않는다([agent-trace.dev](https://agent-trace.dev/)). convention-guard 의 `p/a/o/u` 출처 분류와 대응한다.

#### 차단 → 수정 → 재검증 루프 정리
- 차단 후 자동 계속: Claude Code `Stop`, Codex `Stop`, Copilot `agentStop`(8회 상한), Cursor `stop` `followup_message`(5회 기본 상한).
- 결정론 검사 후 수정: Aider auto-lint, Copilot coding agent 자체 검증, Semgrep Guardian, SonarQube PostToolUse.
- **재검증에서 고쳐짐/여전함/새 지적을 구분하는 상태 기계**: Claude Code Review 의 "next run resolves the thread when the issue is fixed", REVIEW.md 의 re-review convergence 정도만 확인됐다([code review](https://code.claude.com/docs/en/code-review)). convention-guard 의 `fixed/dismissed/dropped/still/new` 분류처럼 지문 키로 사이클을 추적하는 공개 시스템은 이번 조사에서 찾지 못했다.

---

## convention-guard 에 시사점

출처에 근거해 빌려 올 만한 것들이다. 도입 여부는 판단하지 않았다.

1. **미사용 기각 탐지·정리** — ESLint 는 해소된 억제를 에러로 알리고 `--prune-suppressions` 로 정리한다([출처](https://github.com/eslint/eslint/blob/main/docs/src/use/suppressions.md)). `dismissed.yaml` 에서 더 이상 매치되지 않는 키를 `scan.py` 나 readiness 가 알려 주면 기각 파일이 썩지 않는다(현재 지원 여부는 `scripts/` 검색 범위에서 찾지 못함).
2. **반복 기각 → 규칙 조정 제안** — Greptile 은 같은 유형을 3회 무시하면 억제하고([출처](https://www.greptile.com/docs/how-greptile-works/memory-and-learning)), Qodo 는 반복 기각을 조용히 한다([출처](https://docs.qodo.ai/code-review)). convention-guard 는 자동 억제 대신 `firings.jsonl` 의 기각 비율로 `rule-tune` 을 제안하는 정도가 결정론 원칙과 맞는다.
3. **에이전트 지침 파일을 규칙 원천으로 읽기** — CodeRabbit 은 `CLAUDE.md`·`.cursorrules`·`copilot-instructions.md` 를 자동으로 읽는다([출처](https://docs.coderabbit.ai/integrations/knowledge-base)). Claude Code Review 는 CLAUDE.md 의 "newly introduced violations"를 nit 로 지적한다([출처](https://code.claude.com/docs/en/code-review)). `convention-discover` 가 이미 하는 일이지만, 정규식 신호가 없는 문장을 `when_code_added` 규칙 후보로 바꾸는 흐름을 이 선례에 맞춰 문서화할 만하다.
4. **"기존 문제" 별도 등급** — Claude Code Review 의 Pre-existing 등급([출처](https://code.claude.com/docs/en/code-review))은 "레거시에 반응하지 않는다"를 지키면서도 정보를 버리지 않는 방법이다. 지금은 `o`/`p` 줄을 무시하는데, CLI `--review` 나 `--all` 에서 따로 묶어 보고하는 형태로 참고할 수 있다.
5. **재검증 수렴 규칙의 외부 근거** — REVIEW.md 의 "after the first review, suppress new nits and post Important findings only"([출처](https://code.claude.com/docs/en/code-review))는 `decide.py` 의 "사이클이 열린 뒤 새 지적은 보고만"과 같은 결론이다. 설계 기록에 근거로 인용할 수 있다.
6. **연속 차단 상한 기본값 비교** — Copilot CLI 8회([출처](https://docs.github.com/en/copilot/reference/hooks-reference)), Cursor 5회([출처](https://cursor.com/docs/agent/hooks))다. convention-guard 기본값은 `max_consecutive_blocks: 3`, `max_verify_attempts: 1`(`config.yaml`)로 둘보다 보수적이다. 의도한 차이인지 설계 기록에 남길 만하다.
7. **다른 에이전트로 이식** — Codex 훅은 `Stop` + `stop_hook_active` + `PostToolUse(apply_patch)` 로 Claude Code 와 대응한다([출처](https://learn.chatgpt.com/docs/hooks)). Copilot CLI(`agentStop`)와 Cursor(`afterFileEdit` + `stop` followup)도 가능하다. Windsurf 는 응답 뒤 계속 진행이 불가하다([출처](https://docs.devin.ai/desktop/cascade/hooks)). `collect.py`/`check.py` 가 이미 진입점만 얇은 구조라 어댑터 추가 비용이 낮다.
8. **출처 표준 포맷 내보내기/가져오기** — Agent Trace(`human/ai/mixed/unknown`)나 git-ai 의 `refs/notes/ai` 를 읽으면([출처](https://agent-trace.dev/), [출처](https://usegitai.com/docs/get-started/how-git-ai-works)), CI 의 `scan.py --range` 도 세션 원장 없이 "에이전트가 쓴 줄만" 범위를 쓸 수 있다. 지금은 훅 경로에서만 가능한 차별점이 CI 로 넓어진다.
9. **diff_context 모드** — reviewdog `diff_context`(변경 줄 ±N)([출처](https://github.com/reviewdog/reviewdog))는 "추가된 줄의 바로 옆 맥락" 규칙에 쓸 수 있는 앵커 아이디어다. 현재 앵커 목록에 해당하는 것이 있는지는 `docs/guide/ko/rules.md` 로 따로 확인해야 한다.
10. **LLM 게이팅 상한** — Semgrep Assistant 는 diff-aware 스캔당 자동 분석을 10개로 제한한다([출처](https://docs.semgrep.dev/semgrep-assistant/overview)). 의미 판정 배치 크기 상한을 정할 때 비교 기준으로 쓸 수 있다.
11. **크로스툴 디렉터리** — Continue 는 `.agents/checks/` 를 "an emerging cross-tool standard"로 함께 스캔한다([출처](https://github.com/continuedev/continue/blob/main/docs/checks/reference.mdx)). 팀 규칙 위치(`.claude/convention-guard/rules/`)의 대안 경로로 고려할 수 있다. 다만 이 "표준"은 Continue 의 주장이며 독립적으로 확인하지 못했다.
12. **ast-grep 규칙 호환** — ast-grep YAML(`pattern`/`kind`/`inside`/`has`/`not`)([출처](https://ast-grep.github.io/guide/rule-config.html))과 CodeRabbit 의 ast-grep 지침([출처](https://docs.coderabbit.ai/guides/review-instructions))이 있으므로, 구조 조건의 일부를 ast-grep 규칙에서 가져오면 팀이 이미 가진 규칙을 재사용할 수 있다.

---

## 출처 목록

에이전트 훅·규칙
- Claude Code hooks reference — https://code.claude.com/docs/en/hooks
- anthropics/claude-code plugins README — https://github.com/anthropics/claude-code/blob/main/plugins/README.md
- hookify README — https://github.com/anthropics/claude-code/blob/main/plugins/hookify/README.md
- Cursor Rules — https://cursor.com/docs/context/rules
- Cursor hooks — https://cursor.com/docs/agent/hooks
- Codex hooks — https://learn.chatgpt.com/docs/hooks
- GitHub Copilot hooks reference — https://docs.github.com/en/copilot/reference/hooks-reference
- Copilot repository custom instructions — https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions
- Copilot coding agent validation changelog (2025-10-28) — https://github.blog/changelog/2025-10-28-copilot-coding-agent-now-automatically-validates-code-security-and-quality/
- Security validation for third-party coding agents (2026-06-09) — https://github.blog/changelog/2026-06-09-security-validation-for-third-party-coding-agents/
- Kiro hooks — https://kiro.dev/docs/hooks/
- Windsurf/Cascade rules — https://docs.devin.ai/desktop/cascade/memories
- Windsurf/Cascade hooks — https://docs.devin.ai/desktop/cascade/hooks
- Cline rules — https://docs.cline.bot/features/cline-rules
- Roo Code custom instructions — https://roocodeinc.github.io/Roo-Code/features/custom-instructions
- Aider conventions — https://aider.chat/docs/usage/conventions.html
- Aider lint/test — https://aider.chat/docs/usage/lint-test.html
- Continue checks reference — https://github.com/continuedev/continue/blob/main/docs/checks/reference.mdx
- Continue checks running locally — https://github.com/continuedev/continue/blob/main/docs/checks/running-locally.mdx
- AGENTS.md — https://agents.md/
- Semgrep Guardian — https://docs.semgrep.dev/semgrep-guardian/overview
- SonarQube CLI integrations — https://docs.sonarsource.com/sonarqube-cli/integrations/integrations
- Sonar "Make your agent verify its code" — https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code

AI PR 리뷰어
- Claude Code Review — https://code.claude.com/docs/en/code-review
- claude-code-action — https://github.com/anthropics/claude-code-action
- CodeRabbit review instructions — https://docs.coderabbit.ai/guides/review-instructions
- CodeRabbit knowledge base — https://docs.coderabbit.ai/integrations/knowledge-base
- CodeRabbit pre-merge checks — https://docs.coderabbit.ai/pr-reviews/pre-merge-checks
- CodeRabbit Claude Code integration — https://docs.coderabbit.ai/cli/claude-code-integration
- Greptile custom standards — https://www.greptile.com/docs/code-review/custom-standards
- Greptile memory and learning — https://www.greptile.com/docs/how-greptile-works/memory-and-learning
- Qodo code review — https://docs.qodo.ai/code-review
- PR-Agent — https://github.com/qodo-ai/pr-agent
- Sourcery code review overview — https://docs.sourcery.ai/Code-Review/Overview/
- Sourcery review rules — https://docs.sourcery.ai/reviews/review-rules/
- Graphite AI reviews setup — https://graphite.com/docs/ai-reviews-setup
- Graphite AI review customization — https://graphite.com/docs/ai-review-customization
- Ellipsis code review — https://www.ellipsis.dev/docs/agents/code-review
- Cursor Bugbot — https://cursor.com/docs/bugbot
- Codex GitHub integration — https://learn.chatgpt.com/docs/third-party/github
- Gemini Code Assist on GitHub (use) — https://docs.cloud.google.com/gemini/docs/code-review/use-code-assist-github
- Gemini Code Assist on GitHub (customize) — https://docs.cloud.google.com/gemini/docs/code-review/customize-repo-review
- GitHub Copilot code review — https://docs.github.com/en/copilot/concepts/agents/code-review

정적 분석·베이스라인
- Semgrep rule syntax — https://docs.semgrep.dev/writing-rules/rule-syntax
- Semgrep CI / diff-aware — https://docs.semgrep.dev/deployment/customize-ci-jobs
- Semgrep Assistant — https://docs.semgrep.dev/semgrep-assistant/overview
- ast-grep rule config — https://ast-grep.github.io/guide/rule-config.html
- CodeQL incremental analysis — https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/scan-from-the-command-line/incremental-analysis
- Danger JS — https://danger.systems/js/
- reviewdog — https://github.com/reviewdog/reviewdog
- SonarQube about new code — https://docs.sonarsource.com/sonarqube-server/latest/user-guide/about-new-code/
- SonarQube quality gate for agentic AI — https://docs.sonarsource.com/sonarqube-server/quality-standards-administration/ai-code-assurance/quality-gate-for-agentic-ai
- ESLint bulk suppressions — https://github.com/eslint/eslint/blob/main/docs/src/use/suppressions.md
- Betterer — https://github.com/phenomnomnominal/betterer
- Ruff linter (add-noqa) — https://docs.astral.sh/ruff/linter/
- Ruff baseline issue #1149 — https://github.com/astral-sh/ruff/issues/1149
- pre-commit — https://pre-commit.com/
- lint-staged — https://github.com/lint-staged/lint-staged

출처 기록
- git-ai — https://usegitai.com/docs/get-started/how-git-ai-works
- Agent Trace — https://agent-trace.dev/
