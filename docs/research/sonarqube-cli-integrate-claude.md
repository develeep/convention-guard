# SonarQube CLI `sonar integrate claude` 심층 조사 — convention-guard 와 비교

접근일: 2026-10-08. 1차 출처만 근거로 썼다. 공식 문서는 docs.sonarsource.com, 공식 블로그·약관은 sonarsource.com, 코드는 [SonarSource/sonarqube-cli](https://github.com/SonarSource/sonarqube-cli)(LGPL-3.0, 공개)를 봤다. **코드는 태그 `1.9.0.15656`(커밋 `4eabd67`, 2026-09-29)에 고정했다.** 문서와 코드가 다르면 코드를 따르고 차이를 따로 적었다. 확인하지 못한 항목은 "확인 못 함"으로 표시했다.

코드 링크는 `https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/` 아래 경로다. 아래에서는 이 접두어를 **`@1.9.0/`** 로 줄여 쓴다. 각 링크는 전체 URL 이다.

---

## 요약

- **에이전트에게 결과를 넘기는 경로는 두 가지다.** 하나는 편집 직후 `PostToolUse` 훅이 `hookSpecificOutput.additionalContext` 로 넘기는 것이고, 이 경로는 **절대 막지 않는다**. 다른 하나는 시크릿 훅이다. `UserPromptSubmit` 는 `{"decision":"block"}` 을, `PreToolUse`(Read)는 `permissionDecision: "deny"` 를 stdout JSON 으로 낸다. exit code 2 나 stderr 는 쓰지 않는다([agent-post-tool-use.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts#L146), [format-sqaa-hook-context.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/format-sqaa-hook-context.ts#L177), [agent-prompt-submit.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-prompt-submit.ts#L42), [claude-pre-tool-use.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-pre-tool-use.ts#L45)).
- **Stop 훅은 없다.** 재검증 루프는 훅이 아니라 `CLAUDE.md` 에 써 넣는 **지시문**("Vortex analysis protocol")이 만든다. 지시문은 턴 끝에 `sonar analyze agentic --depth DEEP` 을 돌리고, 손댄 줄에 이슈가 있으면 고친 뒤 "Repeat until clean" 하라고 한다. 반복 상한은 없다([sqaa-instructions-feature.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/features/sqaa-instructions-feature.ts#L37-L69)).
- **분석은 서버에서 한다.** 훅은 편집된 파일의 **전체 내용**을 SonarQube 의 Vortex 분석 API 에 POST 한다(Cloud `/a3s-analysis/analyses`, Server `/api/v2/a3s/analyses`). 서버는 CI 분석 때 저장한 프로젝트 컨텍스트(의존성, 컴파일 산출물, 타입 정보, 빌드 설정)를 복원해 분석한다([sqaa-analysis-client.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-analysis-client.ts#L41), [Sonar Vortex analysis 문서](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/sonar-vortex-analysis)).
- **분석 범위는 파일 단위다.** 편집마다 파일 하나를 STANDARD 로, 턴 끝에는 파일 목록 또는 git 변경 집합을 DEEP 으로 분석한다. 변경 줄로 거르지 않고 파일 전체의 이슈를 돌려준다. "손댄 줄인지"는 **에이전트가 판단**하라고 지시문이 맡긴다.
- **오탐 처리 기능은 CLI 에 없다.** 훅 경로에서 이슈 상태(False Positive/Accepted)를 반영하거나 로컬 기각 목록을 두는 코드를 찾지 못했다. 서버 응답 타입에 `patchResult{newIssues, matchedIssues, closedIssues}` 가 있지만 CLI 는 쓰지 않는다([sqaa-wire-types.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-wire-types.ts#L46)). 서버가 기존 이슈 상태를 거르는지는 확인 못 함.
- **전제 조건이 무겁다.** Vortex 구독이 필요하다(Cloud 는 Enterprise 또는 연간 Team 플랜 + Sonar Agent Essentials, Server 는 2026.5 이상 Enterprise/Data Center + 별도 구독). CI 에서 long-lived 브랜치를 분석해 두어야 하고, user token 만 쓸 수 있다([Vortex prerequisites](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/vortex-prerequisites.md)). 구독이 없으면 시크릿 훅과 MCP 서버만 설치된다.
- **실패하면 조용히 통과한다(Vortex 분석).** 프로젝트 키 미해결, 네트워크 오류, 분석 실패가 모두 출력 없이 `none` 으로 끝난다. 시크릿 훅은 인증이나 바이너리가 없으면 **fail closed** 로 막는다. 다만 스캔 자체가 실패하면 통과시킨다([agent-post-tool-use.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts#L58-L141), [hook-dependencies.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/hook-dependencies.ts#L72)).
- **convention-guard 와 겹치는 부분은 작다.** Sonar 는 "Sonar 규칙 + 서버 측 CI 컨텍스트로 정밀한 정적 분석"에 강하다. convention-guard 는 "팀 컨벤션 + 에이전트가 쓴 줄만 + Stop 차단과 상한 있는 재검증 + 지문 키 기각"에 강하다.

---

## 설치와 구성

### 설치 경로

- **CLI 설치**: Homebrew(`brew install sonarqube-cli`), mise, 설치 스크립트(Linux/macOS/Windows). 지원 OS 는 Linux x86-64/ARM64, macOS ARM64, Windows x86-64 이고, SonarQube Server 는 v25.1+ 이다([README](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/README.md)).
- **Claude Code 연동**: 로그인 후 `sonar integrate claude` 를 실행한다. 맨 `sonar integrate` 를 실행하면 설치된 에이전트를 감지해 고르게 한다. `--non-interactive` 를 지원한다([integrations 문서](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations), [integrate/CLAUDE.md](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md)).
- **Claude Code 플러그인 경로**: `claude plugin install sonarqube@claude-plugins-official` → `/sonarqube:sonar-integrate` 로 설치한다. 이 스킬은 CLI 를 설치·인증한 뒤 `sonar integrate claude --non-interactive` 에 위임한다. 문서는 "Both methods produce identical results" 라고 한다([install Vortex for Claude Code](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/install-vortex-claude-code.md), [Sonar 블로그 2026-09-21](https://www.sonarsource.com/resources/library/sonar-vortex-with-claude-code/)).
- **설치 범위는 항상 전역이다.** 문서는 "Every `sonar integrate` command installs **globally** in your user home"이라고 한다([integrations](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)). 1.9.0 코드에서도 `resolveIntegrateInstallTarget()` 가 무조건 `{ installRoot: homedir(), installScope: 'global' }` 를 돌려준다([agent-integrate-prelude.ts#L129](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/agent-integrate-prelude.ts#L129)). 1.8.0 미만에서는 `sonar integrate claude --project <key>` 로 프로젝트별 설치를 했다([install 문서](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/install-vortex-claude-code.md)). 프로젝트 키는 훅 실행 시점에 `discoverProject()` 로 찾는다. 찾는 순서는 known-server-project-mapping → `sonar-project.properties`/`.sonarlint` → git remote 바인딩이다([integrate/CLAUDE.md "Agent SQAA delivery"·"Context Augmentation"](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md)).

### 쓰는 파일 (전역 설치 기준, `~` = 홈)

| 파일 | 내용 | 근거 |
| --- | --- | --- |
| `~/.claude/settings.json` | `hooks` 아래 항목 추가. 항목은 `{matcher, hooks:[{type:"command", command:<스크립트 절대경로>, timeout:60}]}` 이다. 소유 판정은 command 문자열에 든 마커(`sonar-secrets`, `sonar-sqaa`, `sonar-posttoolusefailure`, Vortex 마커)로 한다 | [declaration.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts), [_common/hooks.ts#L102·L225-L298](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/hooks.ts#L225-L298) |
| `~/.claude/hooks/sonar-secrets/build-scripts/{pretool-secrets,prompt-secrets}.sh` (Windows `.ps1`) | `sonar` 가 PATH 에 없으면 `exit 0`, 있으면 `sonar hook claude-pre-tool-use` / `claude-prompt-submit` 실행 | [_common/hooks.ts#L35-L45](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/hooks.ts#L35-L45) |
| `~/.claude/hooks/sonar-sqaa/build-scripts/posttool-sqaa.sh` | `sonar hook claude-post-tool-use` (Vortex 구독 시) | [declaration.ts#L91-L110](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts#L91) |
| `~/.claude/hooks/sonar-posttoolusefailure/...` | `sonar hook claude-post-tool-use-failure` (CAG, 허용 org 만) | [declaration.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts) |
| `~/.claude/CLAUDE.md` (전역) / 프로젝트 `CLAUDE.md` (프로젝트 범위) | `<!-- sonar:begin:sonarqube-agentic-analysis-protocol -->` … `<!-- sonar:end:… -->` 로 감싼 "Vortex analysis protocol" | [declaration.ts#L301](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts#L301), [sqaa-instructions-feature.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/features/sqaa-instructions-feature.ts) |
| `~/.claude.json` (전역) / `.mcp.json` (프로젝트) | SonarQube MCP 서버 등록. 컨테이너 런타임(docker/podman/nerdctl)이 필요하다 | [declaration.ts#L307](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts#L307), [tool-detector.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/core/host/environment/tool-detector.ts), [블로그 전제 "Docker Desktop, Podman, or Nerdctl running"](https://www.sonarsource.com/resources/library/sonar-vortex-with-claude-code/) |

### settings.json 에 들어가는 훅 항목 (코드에서 재구성)

정확한 JSON 예시는 문서에 없다. 아래는 [declaration.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts)와 [_common/hooks.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/hooks.ts)로 재구성한 모양이다. 경로 문자열의 정확한 따옴표 처리는 생략했다.

```json
{
  "hooks": {
    "PreToolUse":         [{ "matcher": "Read",       "hooks": [{ "type": "command", "command": "~/.claude/hooks/sonar-secrets/build-scripts/pretool-secrets.sh", "timeout": 60 }] }],
    "UserPromptSubmit":   [{ "matcher": "*",          "hooks": [{ "type": "command", "command": "~/.claude/hooks/sonar-secrets/build-scripts/prompt-secrets.sh",  "timeout": 60 }] }],
    "PostToolUse":        [{ "matcher": "Edit|Write", "hooks": [{ "type": "command", "command": "~/.claude/hooks/sonar-sqaa/build-scripts/posttool-sqaa.sh",       "timeout": 60 }] }],
    "SessionStart":       [{ "matcher": "startup|clear", "hooks": [ "...CAG session-start..." ] }],
    "SubagentStart":      [{ "hooks": [ "...CAG session-start..." ] }]
  }
}
```

- `PostToolUse` matcher 는 활성 서브피처의 합집합이다. CAG 허용 org 이면 `Edit|Write|Bash|PowerShell|Monitor|Read` 가 되고, `PostToolUseFailure` 항목도 생긴다([hook-container-feature.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/hook-container-feature.ts), [context-augmentation-hook-subscriber.ts#L29](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/context-augmentation-hook-subscriber.ts#L29)). CAG 훅이 실제로 동작하는 org 는 내부 허용 목록(`DISTILLATE_ORG_ALLOWLIST`)으로 제한된다([integrate/CLAUDE.md](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md)).
- Vortex 묶음은 설치 전에 entitlement 를 확인한다. `enabled`/`over_consumption` 이면 설치하고, `not_entitled`/`not_applicable` 이면 기존 Vortex 피처를 제거하고, `check_failed` 이면 유지한다(같은 문서 "Vortex feature" 절).

---

## 훅별 동작

| 훅 이벤트 (matcher) | 실행되는 것 | 에이전트에 가는 출력 | 막는가? |
| --- | --- | --- | --- |
| `UserPromptSubmit` (`*`) | `sonar hook claude-prompt-submit`. 프롬프트 텍스트를 로컬 `sonar-secrets` 바이너리에 stdin(`--input --json`)으로 넘겨 스캔한다. 타임아웃은 30초다([secrets.ts#L117-L163](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/secrets.ts#L117)) | 시크릿 발견(바이너리 exit 51) 시 stdout `{"decision":"block","reason":"Sonar detected secrets in prompt"}` | **예**. 인증이나 바이너리가 없어도 `decision: block` 이다(fail closed). 스캔 예외는 로그만 남기고 통과한다([agent-prompt-submit.ts#L42-L84](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-prompt-submit.ts#L42), [config-constants.ts#L273](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/core/config-constants.ts#L273)) |
| `PreToolUse` (`Read`) | `sonar hook claude-pre-tool-use`. `tool_name === 'Read'` 이고 파일이 있으면 그 파일을 `sonar-secrets` 로 스캔한다 | 발견 시 `hookSpecificOutput: {hookEventName:"PreToolUse", permissionDecision:"deny", permissionDecisionReason:"Sonar detected secrets in file: <path>"}` | **예**(Read 차단). 인증이나 바이너리가 없어도 deny 한다. 스캔 예외는 통과한다([claude-pre-tool-use.ts#L45-L95](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-pre-tool-use.ts#L45)) |
| `PostToolUse` (`Edit\|Write`) | `sonar hook claude-post-tool-use` → 디스패처가 SQAA 구독자(Edit/Write)와 CAG 구독자(허용 org 의 Bash/PowerShell/Monitor/Read)를 순서대로 부른다 | 분석 성공 시 항상 `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<파일별 이슈 목록 + 요약>"}}`. 이슈가 0개여도 요약 줄을 넣는다 | **아니오**. "findings report via `hookSpecificOutput.additionalContext` and never block the agent"([integrate/CLAUDE.md](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md), [claude-hook-dispatch.ts#L44-L81](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-hook-dispatch.ts#L44)) |
| `PostToolUseFailure` (CAG matcher) | CAG 바이너리로 그대로 전달 | CAG 가 내는 JSON | 확인 못 함(CAG 바이너리 소스 비공개) |
| `SessionStart` (`startup\|clear`), `SubagentStart` | `sonar hook agent-session-start --agent claude` → `sonar-context-augmentation tool print-session-start-context` | Vortex context(아키텍처 등) 주입 | 아니오 |
| `Stop` / `SubagentStop` | **설치하지 않음** | — | — |
| (지시문) `CLAUDE.md` "Vortex analysis protocol" | 턴 끝에 에이전트가 직접 `sonar analyze agentic --depth DEEP [--file …]` 을 실행한다 | 명령 출력(Bash 결과) | 강제력 없음. 지시문은 "**MUST**", "Skipping … is a protocol violation" 이라고 쓰지만 훅으로 검증하지 않는다 |

**문서와 코드의 차이**: 문서는 PreToolUse 시크릿 훅이 "runs before file reads/writes" 라고 쓴다([integrations](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)). 1.9.0 코드는 matcher 가 `Read` 이고 핸들러도 `tool_name !== 'Read'` 이면 바로 통과한다([declaration.ts#L185](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts#L185), [claude-pre-tool-use.ts#L67](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-pre-tool-use.ts#L67)). 즉 **쓰기 전 검사는 없다.** Write/Edit 에 시크릿이 들어가도 PreToolUse 에서 막지 않는다. Vortex 분석이 "Secrets Detection: supported for all files" 이므로 PostToolUse 결과에 나올 수는 있다([Vortex analysis 문서](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/sonar-vortex-analysis)). 하지만 이것도 막지는 않는다.

**재검증 루프**: 루프는 지시문 4번 항목에만 있다. "If Vortex analysis reports issues on lines you touched in this turn, fix them, then re-run Vortex analysis on the same scope … Repeat until clean (or only pre-existing findings on lines you did not touch remain)."([sqaa-instructions-feature.ts#L64](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/features/sqaa-instructions-feature.ts#L64)) 반복 상한, 연속 차단 상한, 진행 상태 저장은 없다. 지시문 1번은 프로젝트가 설정되지 않았다는 응답을 받으면 "say **nothing** about it" 이라고 한다. 따라서 이 경우 사용자는 검사가 돌지 않았다는 사실을 알 수 없다.

---

## 정적 분석은 어떻게 진행되는가

`Edit`/`Write` 한 번에 대해 PostToolUse 훅이 하는 일을 1.9.0 코드 순서대로 적었다.

1. **스크립트 진입**: Claude Code 가 `posttool-sqaa.sh` 를 실행한다(훅 타임아웃 60초). `sonar` 가 PATH 에 없으면 `exit 0` 으로 아무것도 내지 않는다([_common/hooks.ts#L35-L45·L102](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/hooks.ts#L35)).
2. **입력 파싱**: stdin JSON 에서 `tool_name` 과 `tool_input.file_path` 만 읽는다. 파싱에 실패하면 조용히 끝낸다. `tool_response` 나 diff(old_string/new_string)는 **쓰지 않는다**([agent-post-tool-use.ts#L58-L61·L163-L170](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts#L58)).
3. **연결·프로젝트 확인**: 저장된 연결(서버 URL, 토큰)을 해석한다. Cloud 인데 org 가 없거나 `discoverProject(cwd)` 로 프로젝트 키를 못 찾으면 `none` 으로 끝난다. 파일이 cwd 밖이어도 건너뛴다(L63-L90).
4. **업로드 내용**: 파일을 디스크에서 **통째로** 읽고(`readFileSync`, L95) git 브랜치를 자동 감지한다(`resolveSqaaBranch`). 요청 본문은 `{organizationKey?, projectKey, branchName?, files:[{path:<cwd 기준 상대 POSIX 경로>, content:<파일 전체>}]}` 다. STANDARD 는 `analysisDepth` 필드를 생략하고, DEEP 일 때만 `"DEEP"` 을 넣는다([sqaa-api.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-api.ts), [sqaa-depth.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-depth.ts), [sqaa-wire-types.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-wire-types.ts)). 품질 프로파일이나 규칙 목록을 **내려받지 않는다**. 로컬 분석기(sonar-scanner, SonarQube for IDE 의 언어 분석기)도 **실행하지 않는다**. CLI 저장소에서 그런 호출 경로를 찾지 못했다.
5. **서버 호출**: `POST /a3s-analysis/analyses`(Cloud, 지역별 API 호스트) 또는 `POST /api/v2/a3s/analyses`(Server, A3S hub)를 부른다([sqaa-analysis-client.ts#L41](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-analysis-client.ts#L41)). POST 타임아웃은 60초다([http-client.ts#L63](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/core/server/http-client.ts#L63)). 503 이면 최대 3회 재시도하고, 백오프는 2·4·8초다([sqaa-api.ts#L50](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-api.ts#L50), [config-constants.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/core/config-constants.ts)). 계산상 재시도 창이 훅 타임아웃 60초를 넘을 수 있다. 그 경우 Claude Code 가 훅을 끊는 것으로 보이지만, 실제 동작은 확인 못 함.
6. **서버 측 분석**: 서버는 CI 분석 때 저장한 컨텍스트를 복원해 분석한다. 문서는 "During a CI analysis, SonarQube collects and stores your project's context: its dependencies, compiled artifacts, type information, and build configuration. When your agent analyzes a file, that context is restored on demand, so the analysis runs with the same inputs as a full CI scan"이라고 설명한다([make your agent verify its code](https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code)). 따라서 업로드는 파일 하나지만 분석은 **프로젝트 컨텍스트(타입, 의존성)를 갖춘** 상태에서 돈다. 서버 내부 엔진(어떤 분석기 버전인지, 크로스파일 심볼을 얼마나 쓰는지)은 확인 못 함. 서버 코드는 공개되지 않았다.
7. **STANDARD 와 DEEP**: CLI 코드가 보여 주는 것은 전송 필드 차이뿐이다. 기본값은 단일 파일 모드면 STANDARD, 다중 파일이나 변경 집합 모드면 DEEP 이다([sqaa-depth.ts#L50](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-depth.ts#L50)). 지시문은 DEEP 이 "cross-file findings are included" 라고 설명한다([sqaa-instructions-feature.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/features/sqaa-instructions-feature.ts#L37)). 문서 페이지에는 STANDARD/DEEP 정의가 없다. 서버가 두 모드에서 정확히 무엇을 다르게 하는지(예: taint 분석 포함 여부)는 확인 못 함.
8. **응답과 출력**: 응답 `issues[]` 는 `{id, rule, message, textRange{startLine,endLine,…}, flows}` 형태다. 이것을 사람이 읽는 텍스트로 만들어 `additionalContext` 로 낸다([format-sqaa-hook-context.ts#L61-L83·L177](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/format-sqaa-hook-context.ts#L61)). 이슈를 변경 줄로 거르지 않는다.
9. **실패·오프라인**: 네트워크 오류, 타임아웃, 5xx, 파일 읽기 실패, 출력 생성 실패는 모두 debug 로그와 텔레메트리만 남기고 **출력 없이** 끝난다(`decision: 'none'`). 403(Vortex entitlement 철회)일 때만 "Vortex unavailable" 안내를 낸다([agent-post-tool-use.ts#L121-L150](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts#L121), [vortex-unavailable-hook-notice.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/vortex-unavailable-hook-notice.ts)). 오프라인에서는 분석이 전혀 일어나지 않는다. 에이전트는 이 사실을 알 수 없다.

**턴 끝 DEEP 분석**(`sonar analyze agentic`)은 에이전트가 Bash 로 실행한다. 대상은 `--file` 목록이고, 없으면 git 변경 집합이다. 변경 집합은 `git diff HEAD`(staged + unstaged)에 untracked 비무시 파일을 더한 것이고, `--staged` 나 `--base <ref>` 로 바꿀 수 있다. 이것도 **파일 이름 목록**만 쓰고, 파일 전체 내용을 청크로 나눠 보낸다. 파일당 상한은 10MB 이고, 413 응답이면 청크를 나눠 다시 보낸다([sqaa-changeset.ts#L33·L65](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-changeset.ts#L33), [sqaa-api.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-api.ts)). 명령 도움말에는 "Run server-side Vortex analysis. Limitations apply."라고 적혀 있다([docs/commands.html](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/docs/commands.html)).

**지원 언어**(서버 측 Vortex): Java, JavaScript, TypeScript, C#, C, C++, Python, Dart, Swift, Kotlin, Go, Objective-C, PHP, PowerShell, Shell, Ruby, Apex, SQL, VB.NET, CSS, HTML, Terraform, Docker, Kubernetes, Groovy 를 지원한다. taint 분석은 Java/JS/TS/C#/VB.NET 에만 있고, 시크릿 검출은 모든 파일에 적용된다. Cloud 에서 Automatic analysis 로 분석된 Java 프로젝트는 "only basic analysis results are returned" 이다([Sonar Vortex analysis](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/sonar-vortex-analysis)). 검색 요약에서는 7개 언어 목록(Java~Python)을 봤는데, 이는 과거 버전 문서로 보인다. 본문 기준으로 25개라고 적었다.

**지연·성능**: 공식 문서의 표현은 "checks your agent's code changes in seconds", "results in record times", "minimal latency" 뿐이다. 수치 벤치마크는 확인 못 함([같은 문서](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/sonar-vortex-analysis)).

**시크릿 스캔**은 로컬 바이너리 `sonar-secrets`(1.9.0 고정 버전 2.49.0.12346, `CommercialDistribution` 배포물)로 돈다. 실행 시 인증 환경 변수를 넘긴다([package.json](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/package.json), [secrets.ts](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/secrets.ts)). 바이너리가 네트워크를 쓰는지는 확인 못 함(소스 비공개).

---

## 분석 범위와 규칙

- **편집 단위**: `Edit`/`Write` 도구의 `file_path` 하나를 대상으로 하고, 파일 전체를 분석한다. `MultiEdit`, `NotebookEdit`, Bash 로 바뀐 파일은 matcher 에 없어서 편집 직후 분석이 없다([declaration.ts#L91](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts#L91), [agent-post-tool-use.ts#L158](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts#L158)). 턴 끝 git 변경 집합 분석에서는 잡힌다.
- **줄 단위 구분 없음**: 사람이 쓴 줄과 에이전트가 쓴 줄을 나누지 않는다. "손댄 줄의 이슈만 고쳐라"는 지시문이 에이전트 판단에 맡긴다. 블로그 시연에서는 에이전트가 "distinguished those pre-existing findings from its own changes" 했다고 쓴다([Sonar 블로그](https://www.sonarsource.com/resources/library/sonar-vortex-with-claude-code/)). 이는 도구가 아니라 모델이 한 구분이다.
- **규칙 출처**: 서버에서 분석하므로 프로젝트에 연결된 Quality Profile 을 쓸 것으로 보이지만, Vortex 문서에서 명시 문장은 확인 못 함. 커스텀 규칙(서드파티 플러그인 규칙, 사용자 정의 규칙)의 적용 여부도 확인 못 함. 응답의 `rule` 키(예: `java:S5443`)는 Sonar 규칙 키이고, 에이전트는 MCP 서버로 규칙 본문을 조회할 수 있다([블로그](https://www.sonarsource.com/resources/library/sonar-vortex-with-claude-code/), [integrations](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)).
- **관련 제품**: Vortex 는 "Agentic Analysis(SQAA)" 와 "Context Augmentation(CAG)" 두 Capability 의 묶음이다([integrate/CLAUDE.md "Vortex feature"](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md), [Vortex Supplemental Terms](https://www.sonarsource.com/legal/sonar-vortex-supplemental-terms/)). SonarQube MCP Server 도 같이 등록된다. AI Code Assurance(프로젝트 단위 품질 게이트)나 SonarQube for IDE 와 코드 경로가 연결되는 곳은 CLI 저장소에서 찾지 못했다. 사용자 문서상으로는 모두 "Agent Centric Development Cycle" 묶음에 속한다([agent-centric-development-cycle 문서](https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code)).

---

## 오탐 처리

- **로컬 억제 장치 없음**: CLI 훅 경로에는 기각 목록, 지문 키, 판정 캐시가 없다. `src/commands/analyze/sqaa*.ts`, `src/commands/hook/` 에서 FALSE_POSITIVE/ACCEPTED/NOSONAR 처리 코드를 찾지 못했다(태그 1.9.0.15656 grep).
- **서버 이슈 상태 동기화**: 응답에 `patchResult{newIssues, matchedIssues, closedIssues}` 필드가 정의돼 있다. 서버가 기존 이슈와 매칭하는 것으로 보이지만 CLI 는 이 필드를 읽지 않는다([sqaa-wire-types.ts#L46](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/analyze/sqaa-wire-types.ts#L46)). 서버에서 False Positive/Accepted 로 표시된 이슈가 Vortex 응답에서 빠지는지는 확인 못 함.
- `sonar list issues --statuses` 는 OPEN/CONFIRMED/FALSE_POSITIVE/ACCEPTED/FIXED 필터를 지원한다. 그러나 이것은 서버에 저장된 이슈를 조회하는 별도 명령이고, 훅 결과와는 무관하다([docs/llms.txt](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/docs/llms.txt)).
- 결국 오탐 대응은 지시문(손대지 않은 줄의 기존 이슈는 무시)과 에이전트 판단에 달려 있다. 지시문 6번은 "Do not suppress, summarize away, or omit Vortex analysis findings from your reply"라고 한다.

---

## 제약·전제

- **구독·에디션**: Cloud 는 "an Enterprise plan or an annual Team plan"과 Sonar Agent Essentials 가, Server 는 "SonarQube Server 2026.5 or later, Enterprise or Data Center edition"과 별도 구독이 필요하다([Vortex prerequisites](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/vortex-prerequisites.md)). 과금은 주문서에 정한 Billable Unit 기준의 사용량제이고, 월 Usage Allowance 는 이월되지 않는다([Supplemental Terms](https://www.sonarsource.com/legal/sonar-vortex-supplemental-terms/)). "2026-06-30 부터 유료 GA" 라는 문구는 검색 결과 요약에서만 봤고, 약관 본문에서는 확인 못 함.
- **토큰**: user token 만 쓸 수 있다. "Project tokens, global tokens, and scoped organization tokens do not work with Vortex."(같은 prerequisites 문서)
- **CI 선행 분석**: "Your project must be analyzed in your CI pipeline on a long-lived branch"(같은 문서, [how-to](https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code)).
- **데이터 전송**: 편집 파일 전체가 Sonar(Cloud) 또는 자체 Server 로 간다. 약관은 제출된 소스를 Customer Data 로 정의한다. 보존 기간 문구는 확인 못 함([Supplemental Terms](https://www.sonarsource.com/legal/sonar-vortex-supplemental-terms/)).
- **런타임**: MCP 서버에 컨테이너 런타임이 필요하다. CLI 바이너리는 Linux x86-64/ARM64, macOS ARM64, Windows x86-64 를 지원한다([README](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/README.md)).
- **전역 설치**: 홈 디렉터리에 설치되어 모든 프로젝트에 적용된다. 프로젝트 키를 못 찾는 레포에서는 PostToolUse 가 조용히 아무것도 하지 않는다.

### 다른 에이전트 (`sonar integrate <대상>`)

대상은 `claude`, `copilot`, `codex`, `cursor`, `antigravity`, `git` 이다([integrate/CLAUDE.md](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md)). 문서는 Conductor 도 언급한다([integrations](https://docs.sonarsource.com/sonarqube-cli/integrations/integrations)).
- **Codex**: `PostToolUse`(apply_patch)가 변경 집합을 STANDARD 로 분석하고, `AGENTS.md` 에 DEEP 지시문을 넣는다.
- **Copilot/Cursor/Antigravity**: 지시문·규칙 파일만 쓴다. Cursor 의 `afterFileEdit` 는 컨텍스트를 돌려줄 수 없어서다.
- **Cursor 시크릿 훅**: 파일 읽기 훅 2개가 exit 2 + `permission: deny` 로 막고, 시크릿 파일을 `.cursorignore` 에 추가한다.
- **git**: pre-commit 시크릿 검사(필수)와 SCA 의존성 위험 검사, pre-push 시크릿 검사를 건다.

### 버전 이력

- 저장소 첫 태그는 `0.1.0.223`(2026-02-25)이다. 시크릿 훅은 2026-02 초기 커밋부터 있었다(예: `73fab67` CLI-32, 2026-02-24). 콜백 기반 `sonar hook claude-post-tool-use` 는 `0b74480` (2026-04-16, CLI-244/245)에서 들어왔고, 처음 포함된 태그는 `0.10.0.1266`(2026-04-26)이다. `1.0.0.2628` 은 2026-06-10, 이 조사의 기준 `1.9.0.15656` 은 2026-09-29 다(로컬 클론의 `git log`/`git tag --contains`). 전역 설치 기본화는 CLI 1.8.0 부터다([install 문서](https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/install-vortex-claude-code.md)).

---

## convention-guard 와 비교

| 항목 | SonarQube CLI `integrate claude` | convention-guard |
| --- | --- | --- |
| 검사 시점 | 편집마다 PostToolUse(Edit/Write), 턴 끝은 **지시문**으로 에이전트가 직접 실행 | Pre/PostToolUse 는 기록만, **Stop 훅**이 검사 |
| 막는가 | 코드 품질은 막지 않음(additionalContext). 시크릿만 차단(프롬프트, Read) | Stop `decision: block` 으로 차단 |
| 재검증 | 지시문 "Repeat until clean", 상한 없음, 상태 없음 | `decide.classify`(fixed/dismissed/still/new…), `max_verify_attempts`·`max_consecutive_blocks` |
| 범위 | 파일 전체(편집 파일, 또는 git 변경 집합). 줄 구분은 에이전트 몫 | 원장 기반 **에이전트가 쓴 줄**(Bash 변경 포함) |
| 관찰 대상 도구 | Edit, Write (MultiEdit/NotebookEdit/Bash 없음) | Write, Edit, MultiEdit, NotebookEdit, Bash |
| 규칙 | Sonar 규칙(서버 측, 25개 언어, taint·시크릿) | 팀 YAML 규칙(정규식 앵커 + tree-sitter 구조 + 선택적 의미 판정) |
| 분석 위치 | 서버(CI 컨텍스트 복원), 파일 내용 업로드 | 로컬(표준 라이브러리 + tree-sitter), 의미 판정만 서브에이전트 |
| 실패 시 | 조용히 통과(출력 없음). 시크릿은 인증/바이너리 부재 시 fail closed | 자기 오류로 깨뜨리지 않되 "읽지 못한 것을 통과로 처리하지 않음", 관찰 누락을 이름 붙여 보고 |
| 오탐 | 로컬 장치 없음. 서버 상태 반영 여부 확인 못 함 | 코드 지문 키 기각(`dismissed.yaml`), 판정 캐시 |
| 비용·전제 | Vortex 구독, CI 분석, user token, 네트워크 | 없음(로컬), 의미 판정 시에만 모델 호출 |

**Sonar 가 강한 곳**
- 타입·의존성·빌드 설정이 있는 상태에서 하는 정밀한 버그·보안 분석(taint 포함)이 강하다. convention-guard 의 구조 엔진은 파일 단위 구문 트리만 본다.
- 프롬프트와 Read 단계의 시크릿 차단이 있다. convention-guard 에는 해당 기능이 없다.
- 응답에 규칙 키가 붙고, MCP 로 규칙 본문을 조회해 수정하게 한다.
- 편집 직후 피드백을 주어서 턴 끝까지 기다리지 않는다.

**convention-guard 가 강한 곳**
- 에이전트가 쓴 줄과 레거시를 도구가 구분한다. Sonar 는 모델에게 맡긴다.
- 실제 차단이 있고, 상한 있는 재검증 상태 기계가 있다. Sonar 는 지시문 준수에 기대며 상한이 없다.
- 관찰 범위가 넓다(MultiEdit/NotebookEdit/Bash).
- 실패를 숨기지 않는다. Sonar 는 오프라인·미설정·오류를 모두 무출력으로 처리하고, 미설정이면 "say nothing" 이라고 지시까지 한다.
- 오탐 기각을 지문 키로 기억한다.
- 서버, 구독, 업로드가 필요 없다.

**빌려올 만한 것**
1. **편집 직후 가벼운 피드백(비차단)**: PostToolUse 에서 정규식 게이트만 돌려 `additionalContext` 로 미리 알리면, Stop 차단 횟수를 줄일 수 있다. 다만 수집 훅 성능 목표(~25ms)와 "수집 훅은 규칙 모듈을 임포트하지 않는다" 제약과 부딪치므로 설계 검토가 필요하다.
2. **실패 정책을 갈라 적기**: Sonar 는 "보안 보호가 못 돌면 막는다(fail closed)"와 "품질 분석이 못 돌면 통과"를 명시적으로 나눴다. convention-guard 도 규칙별로 이 둘을 고를 수 있게 하는 것을 생각해 볼 수 있다.
3. **설정 파일 소유 마커**: 사용자 파일에는 `<!-- sonar:begin:… -->` 마커로 감싼 구역만 쓰고 지운다. 훅 항목 소유도 command 문자열 마커로 판정한다. 이렇게 하면 공유 파일을 안전하게 갱신·제거할 수 있다.
4. **`${CLAUDE_PROJECT_DIR}` 경로 인용 교훈**: 작은 따옴표 안에서는 확장되지 않아 훅이 조용히 실패한다는 실측 기록이 있다([integrate/CLAUDE.md](https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md)).

---

## 확인 못 한 것

- 서버 측 Vortex 엔진의 실체: 어떤 분석기 버전인지, STANDARD 와 DEEP 의 정확한 차이(taint 나 크로스파일 포함 범위).
- 서버의 False Positive/Accepted 이슈 상태가 Vortex 응답에 반영되는지, `patchResult` 의 의미.
- 규칙이 프로젝트 Quality Profile 을 그대로 따르는지, 커스텀/서드파티 규칙이 적용되는지.
- 지연 시간 수치. 503 재시도가 60초 훅 타임아웃을 넘길 때의 실제 동작.
- `sonar-secrets` 바이너리의 네트워크 사용 여부와 규칙 출처.
- CAG(`sonar-context-augmentation`)의 PostToolUse/PostToolUseFailure 출력 형식(소스 비공개).
- 제출 코드의 보존 기간. 유료 GA 날짜(검색 요약에서만 봄).

---

## 출처

- SonarSource/sonarqube-cli 저장소, 태그 1.9.0.15656 — https://github.com/SonarSource/sonarqube-cli/tree/1.9.0.15656
  - src/commands/integrate/CLAUDE.md — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/CLAUDE.md
  - src/commands/integrate/claude/declaration.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/claude/declaration.ts
  - src/commands/integrate/_common/hooks.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/hooks.ts
  - src/commands/integrate/_common/agent-integrate-prelude.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/agent-integrate-prelude.ts
  - src/commands/integrate/_common/features/sqaa-instructions-feature.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/integrate/_common/features/sqaa-instructions-feature.ts
  - src/commands/hook/agent-post-tool-use.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-post-tool-use.ts
  - src/commands/hook/claude-hook-dispatch.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-hook-dispatch.ts
  - src/commands/hook/format-sqaa-hook-context.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/format-sqaa-hook-context.ts
  - src/commands/hook/claude-pre-tool-use.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/claude-pre-tool-use.ts
  - src/commands/hook/agent-prompt-submit.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/agent-prompt-submit.ts
  - src/commands/hook/hook-dependencies.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/commands/hook/hook-dependencies.ts
  - src/commands/analyze/sqaa-api.ts · sqaa-analysis-client.ts · sqaa-depth.ts · sqaa-wire-types.ts · sqaa-changeset.ts · secrets.ts — https://github.com/SonarSource/sonarqube-cli/tree/1.9.0.15656/src/commands/analyze
  - src/core/server/http-client.ts — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/src/core/server/http-client.ts
  - README.md — https://github.com/SonarSource/sonarqube-cli/blob/1.9.0.15656/README.md
- SonarQube CLI integrations — https://docs.sonarsource.com/sonarqube-cli/integrations/integrations
- Sonar Vortex analysis — https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/sonar-vortex-analysis
- Make your agent verify its code — https://docs.sonarsource.com/agent-centric-development-cycle/verify/how-to-guides/make-your-agent-verify-its-code
- Vortex prerequisites — https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/vortex-prerequisites.md
- Install Vortex for Claude Code — https://docs.sonarsource.com/agent-centric-development-cycle/inside-your-agent-the-agentic-loop/how-to-guides/install-vortex-claude-code.md
- Sonar 블로그 "How to set up Sonar Vortex in Claude Code"(2026-09-21) — https://www.sonarsource.com/resources/library/sonar-vortex-with-claude-code/
- Sonar Vortex Supplemental Terms — https://www.sonarsource.com/legal/sonar-vortex-supplemental-terms/
