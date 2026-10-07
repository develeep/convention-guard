# Production readiness checklist

[README](../../../README.en.md) · [한국어](../ko/production-readiness.md) · **English**

This is the procedure to confirm "every feature works as intended" before you actually turn on
convention-guard in a team repo. Each item is laid out as **Why / Check / Expect / If it fails**,
and the check method is marked as one of three.

| Mark | Meaning |
|---|---|
| **[auto]** | `readiness.py` reads this repo and the install state directly and decides |
| **[sandbox]** | `readiness.py` runs the plugin's own tests in a temporary repo and decides — no need to end a real turn |
| **[manual]** | A person has to check it |

```bash
python3 <install path>/scripts/readiness.py            # full (~10s)
python3 <install path>/scripts/readiness.py --quick    # skip sandbox and measurement (~1s)
```

Run it in the directory where you open the Claude Code session. Project and local settings (B2, B5) are read relative to that directory.

Each output line is one item id of this document. The `convention-readiness` skill runs this check and summarizes the result.

The install path is the value Claude Code recorded (it changes with every version, so do not memorize the path):

```bash
python3 -c "import json,os;d=json.load(open(os.path.expanduser('~/.claude/plugins/installed_plugins.json')));print([e['installPath'] for k,v in d['plugins'].items() if k.startswith('convention-guard@') for e in v][0])"
```

This plugin has one core safety principle — **something that was not checked must never look like a clean pass.**

## Contents
- A. Environment prerequisites
- B. Claude Code plugin — install, scope, wiring
- C. Repo configuration layers
- D. Do all rules work?
- E. Detection volume — how many hits in our repo?
- F. Block, fix, re-verify cycle
- G. Semantic review (subagent)
- H. Failure modes — does it never die silently?
- I. Performance budget
- J. Security and privacy
- K. CI integration
- L. Operation — the first 2–3 weeks
- M. Rollback
- N. What this checklist does not verify

---

## A. Environment prerequisites

- [ ] **A1. Python 3.10 or later runs as `python3`** [auto][sandbox]
  - Why: The hooks run as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py"`. The structure engine (tree-sitter) has no wheels below 3.10. On some machines the `python3` from macOS Command Line Tools is 3.9.
  - Expect: `python3` on PATH is 3.10+. On 3.9 or older it states the required version and what to do, and does not die silently (`tests/unit/test_version_guard.py`).
  - If it fails: Upgrade the interpreter, or point `python3` at the team's standard Python.

- [ ] **A2. Are there team members on native Windows?** [manual]
  - Why: On native Windows, `python3` may be missing or a Microsoft Store stub, so the hooks do not run.
  - Check: Each team member runs `python3 --version`. If the machine running the check is native Windows, it is a WARN via [auto].
  - If it fails: Use WSL, or run with `scan.py` + CI (K) instead of hooks. **This path is not verified in the repository's CI.**

- [ ] **A3. The check target is a git worktree** [auto]
  - Expect: If it is not git, stderr shows `convention-guard: error: git 레포가 아닙니다` ("not a git repo") + **exit 2** (not 0, which means pass). `readiness.py` itself also exits 2 under the same rule.

- [ ] **A4. Rules are read without installing anything** [auto][sandbox]
  - Why: Rules and config are read with one built-in YAML parser (`miniyaml`). PyYAML is not used even if present.
  - Expect: In the sandbox, `detect_stack.py` reads the rules without errors. If there is an error, config.yaml or a local rule contains YAML syntax the built-in parser cannot read (multi-line flow lists, etc.).

- [ ] **A5. The structure engine is installed** [auto]
  - Why: Structure conditions (`not_in`, `in_scope`, `block_empty`) are decided with tree-sitter. Without the engine the conditions cannot be applied, so candidates come up unverified (reported as "구조 엔진 없음" ("structure engine missing")).
  - Expect: `python3 scripts/engine.py status` shows the path. The convention-setup skill installs it; on a machine where setup never ran, the first Stop installs it in the background.
  - If it fails: Run `python3 scripts/engine.py ensure` directly to see the reason. Offline, put the wheels from `lock.json` in `CONVENTION_GUARD_WHEELS` and install. musl aarch64 and free-threaded Python have no wheels and are not supported.

---

## B. Claude Code plugin — install, scope, wiring

- [ ] **B1. An install that applies to this repo exists and is up to date** [auto]
  - Why: Installs are recorded with user / project / local scope (`~/.claude/plugins/installed_plugins.json`). A local install applies only to the `projectPath` repo.
  - Expect: There is an install record that applies to this repo, and its version equals the latest in the marketplace.
  - If it fails: Install or update from `/plugin`.

- [ ] **B2. It is on for team members too (enabled scope)** [auto]
  - Why: `enabledPlugins` is overridden in the order user < project < local. **If you enable it only in user or local scope, only you are checked.**
  - Expect: The final value is true, and the project `.claude/settings.json` has `enabledPlugins` and `extraKnownMarketplaces` committed.
  - If it fails:
    ```json
    {
      "enabledPlugins": { "convention-guard@<marketplace>": true },
      "extraKnownMarketplaces": { "<marketplace>": { "source": { "source": "git", "url": "<repository>" } } }
    }
    ```

- [ ] **B3. The hooks are wired and actually run** [auto][sandbox]
  - Why: Pre/PostToolUse and PostToolUseFailure (edit event ledger) / Stop (check) must all be present for "only lines the agent wrote" to hold. If a hook is missing or dies, Stop reports it as "관찰 누락" ("observation gap").
  - Expect: `hooks.json` wires PreToolUse, PostToolUse and Stop (these three are checked; PostToolUseFailure is in the same file but not checked) + the state store (`convention-guard.db`) in the hook data directory (B4) shows recent activity.
  - If it fails: In a session, change one line in a file, end the turn, and check again. If it is still missing, see whether it is enabled in `/plugin`.

- [ ] **B4. You know where the data directory is** [auto]
  - Why: Installed hooks write to `CLAUDE_PLUGIN_DATA` (`~/.claude/plugins/data/convention-guard-<marketplace>/`) given by Claude Code. Scripts you run by hand, when this variable is absent, look at `$XDG_CACHE_HOME/convention-guard/` (if unset, `~/.cache/convention-guard/`; if that cannot be created, a temporary directory) — **a different directory**.
  - Expect: The two locations are the same, or you know they differ and which path to use.
  - If it fails: When running `log_report.py` or `review.py` directly, prefix `CLAUDE_PLUGIN_DATA="<hook data directory>"`. Without it the log looks "비어 있음" ("empty").

- [ ] **B5. userConfig is as intended per scope** [auto]
  - Why: The values chosen at install time are kept in `pluginConfigs["convention-guard@…"].options` of the settings for each scope.
  - Expect:
    - `report_only` and `semantic_review` are true/false.
    - `log_dir` is an **absolute path outside the repo**. A relative path (`./logs`) resolves against the hook's working directory, i.e. **inside each repo**, so logs scatter across repos and may be picked up by git.
  - Note: `mode` and `semantic_review` in the repo `config.yaml` always take precedence over userConfig (C2).

- [ ] **B6. The 6 skills and the reviewer agent are present** [auto][sandbox][manual]
  - Expect: `convention-check`, `convention-discover`, `convention-setup`, `rule-add`, `rule-tune`, `convention-readiness` and `agents/convention-reviewer.md`. Structure (name, description, references, existence of scripts) is checked by `tests/skills/test_skill_structure.py`.
  - Manual: Whether the skills are actually followed correctly is only known by running the `tests/skills/evals/*.json` scenarios with Claude.

---

## C. Repo configuration layers

```
plugin config.yaml  <  userConfig  <  <repo>/.claude/convention-guard/config.yaml
rules: core(plugin)  <  user(~/.claude/convention-guard/rules)  <  local(<repo>/.claude/convention-guard/rules)
```

- [ ] **C1. The repo config is valid** [auto]
  - Expect: No error notes. Unknown keys are ignored and shown as warnings.
  - Expect: `mode: report` for a first rollout. WARN if `fix` or `auto-fix`.
  - If it fails: If there is an error, the hook skips the check (and says so). Fix the error.

- [ ] **C2. Precedence holds** [sandbox]
  - Expect: Repo values beat userConfig (one person cannot lower the bar). Writing only some keys of a group keeps the defaults for the rest. A wrong type is an error. Unknown keys (including 3.x and 0.x keys) give the warning `알 수 없는 설정 … (무시)` ("unknown setting … (ignored)") (`tests/unit/test_config_and_rules.py`).

- [ ] **C3. Stack and preset detection match our repo** [auto][manual]
  - Expect: `stacks` matches the real stack. WARN if empty.
  - If it fails: Set `stacks:` in `config.yaml`. A monorepo is decided only once at the root, so split it with `applies_to.files` / `exclude`.

- [ ] **C4. Linter delegation is as intended** [auto]
  - Expect: A missing linter shows `설치 안 됨, 건너뜀` ("not installed, skipped"), an available linter shows `변경 줄만 차단 (parse: …)` ("block only changed lines"). If it shows `출력을 읽지 못해 무관한 기존 에러로도 차단` ("output unreadable, so unrelated existing errors also block"), it is a warn — unrelated existing errors will also block.
  - Bundled commands use **only binaries that already exist**, such as `npx --no-install` and `./vendor/bin/*`.
  - If it fails: Add `parse:` in `stacks/*.yaml`, or set `linters.enabled: false`.

- [ ] **C5. All team members run the same rules (personal layer)** [auto]
  - Why: Personal rules in `~/.claude/convention-guard/rules/` run only on that machine. The same commit gets flagged differently per person.
  - Expect: It is empty, or you know it is personal.
  - If it fails: If they are team rules, move them to the repo's `.claude/convention-guard/rules/`.

- [ ] **C6. The dismissal record is readable** [auto]
  - Why: If `dismissed.yaml` is broken, the hook skips the check.
  - Expect: Parsing succeeds, and the count is shown.

---

## D. Do all rules work?

- [ ] **D1. Every rule passes its own fixtures — core, user, local** [sandbox]
  - Check: `tests/rules/test_rule_fixtures.py --repo <repo> --user-dir <directory>`
  - Expect: Every `tests.match` hits and `no_match` does not. Overrides are checked merged into the original. `fix.auto` resolves the violation and leaves correct code as is.

- [ ] **D2. Every applied rule reaches some file** [auto]
  - Why: Even with `✔ on`, if `applies_to.files` does not match the repo layout (`app/**` while the code is in `src/`), it never hits. It is a rule that is on but dead.
  - Expect: Each applied rule reaches at least one tracked file (pair rules by `when_changed`).
  - If it fails: If that stack does not exist yet, you can ignore it. If the layout differs, fix `applies_to.files` with an `override`.

- [ ] **D3. Legacy code is not flagged** [sandbox][manual]
  - Why: Anchors are "added lines / new files / change set", so untouched code must be out of scope.
  - Sandbox: `tests/rules/test_rule_scenarios.py` — a "new code is flagged / legacy stays quiet" scenario for every non-`when_line_added` rule.
  - Manual: In a file with many legacy violations, change one unrelated line and run `scan.py` → existing violations must not appear. If they do, check whether that rule's anchor is `file_regex` (anchor table in [rules.md](rules.md#anchors-what-this-change-is-responsible-for)).

- [ ] **D4. Code inside comments and strings is not flagged (structure conditions)** [sandbox]
  - Expect: In `not_in: [comment, string]` rules, matches inside comments and strings are excluded, only real code (`tests/structure/test_detect_conditions.py`, `test_conditions.py`).

- [ ] **D5. Semantic review rules are actually reviewed** [auto]
  - Why: Even with semantic review rules on, if `semantic_review.enabled` is false they only find candidates and do not decide.
  - Expect: If any semantic review rule is applied, `semantic_review` is on.

---

## E. Detection volume — how many hits in our repo?

- [ ] **E1. Measure recent changes (the key number for the rollout decision)** [auto]
  - Check: Check the last 20 commits (`--commits N`) with linters included.
  - Expect: error+warn is **2 or fewer per commit**. With more than that, the agent keeps getting blocked once you move to `fix`.
  - If it fails: Adjust `severity` / `exclude` using the table in step 4 of `convention-setup`.

- [ ] **E2. Full-scan size** [auto, with `--all`]
  - Expect: Top 5 rules by error count. If they cluster in one directory, it is a legacy area → `exclude`.

- [ ] **E3. Get a feel for false positives** [manual]
  - Check: For each rule, open three or four places from E1 and E2.
  - Expect: 2–3 or fewer false positives out of 20. If more, do not turn that rule on yet. If you dismiss a false positive with `dismiss.py`, it does not come back as long as the code stays the same.

---

## F. Block, fix, re-verify cycle

This is the stage before moving to `mode: fix`. **Only error severity blocks.** All items are [sandbox] — `tests/integration/test_hook_cycle.py`, `test_autofix.py`, `test_dismiss_and_report.py` run the real Stop hook turn by turn to check.

- [ ] **F1. error blocks, warn is only logged** — On block: violation location, fix instruction, dismiss command. With warns only, a system message `convention-guard ⚠ 기록 — warn N (<rule id>)` ("logged — warn N"). `mode: report` does not block.
- [ ] **F2. Fixing it passes (re-verification)** — The next Stop re-checks the same scope and ends quietly. `verify` in the log.
- [ ] **F3. No infinite loop** — Past `limits.max_verify_attempts` (default 1) it shows `재검증 종료 — … · 이후 기록만` ("re-verification ended — … · log only from now on"); overall it stays within `limits.max_consecutive_blocks` (default 3).
- [ ] **F4. False-positive dismissals survive** — The dismissal key is `rule:file:code fingerprint`. It holds when lines are added above, and is released when that line changes. `dismissed` in the log.
- [ ] **F5. The agent hears about auto-fixes** — In `mode: auto-fix`: `자동 수정 N (파일) — 편집 전에 다시 읽으세요` ("N auto-fixes (files) — re-read before editing"). `fix` mode does not touch files.
- [ ] **F6. A turn that ends with a question is not checked** — `skip_if_question: true` (default). Changes committed during the session stay in scope (the ledger keeps each line's origin even after a commit).

---

## G. Semantic review (subagent)

It is **off** by default. All items are [sandbox] — `tests/integration/test_semantic_review.py`, `tests/semantic/*`.

- [ ] **G1. Nothing to judge means zero AI calls** — A turn with no change caught by the gate and no meaningful added line in a file under a `when_code_added` glob creates no review batch.
- [ ] **G2. With candidates, it hands over a one-line review command** — `convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 전달` ("pass the one-line command below as is to the convention-guard:convention-reviewer agent") + `review.py show <batch>`.
- [ ] **G3. The context pack is "one function's worth"** — Candidate + surroundings + imports + lines this change added. Within `semantic_review.context_budget_lines` and the rule's `max_context_lines`.
- [ ] **G4. Verdicts are cached** — VALID is not asked again; VIOLATION blocks like a deterministic candidate. Re-reviewed when the function body, related files or the rule change. TTL `verdict_ttl_days` (default 30).
- [ ] **G5. A missing verdict does not look like a pass** — It asks once more, then logs `review_skipped` + `판정 대기 N` ("N verdicts pending").

---

## H. Failure modes — does it never die silently?

**This is the most important section.** There is one dangerous way to fail — "broken, but looks like a pass". [sandbox] — `tests/integration/test_cli_contract.py`, `test_lint_anchor.py`, `test_self_exclude.py`.

- [ ] **H1. Bad config skips the check but says so** — `convention-guard ✖ 건너뜀 — 설정 오류: ...` ("skipped — config error: ..."). The CLI prints stderr `convention-guard: error: ...` + exit 2.
- [ ] **H2. Unknown config keys are reported** — Warning `알 수 없는 설정 <key> (무시)` ("unknown setting <key> (ignored)"). The 3.x keys `scope.base_ref` and `collect.edit_tools` fall in this category. A `dismissed.yaml` without `version: 4` is not applied and gives a warning.
- [ ] **H3. Internal bugs do not break the turn** [auto] — `readiness.py` feeds abnormal input to the installed `check.py` to check: exit 0 + `convention-guard ✖ 건너뜀 — 내부 오류: <cause>` ("skipped — internal error: <cause>").
- [ ] **H4. Files whose structure could not be read are reported** — `구조 미확인 N개 파일 — ...` ("structure unverified in N files — ...") or `구조 엔진 없음 (사유) — 구조 미확인 N개 파일` ("structure engine missing (reason) — structure unverified in N files"); candidates are not filtered and come up. CI can make this case a failure with `scan.py --require-engine`.
- [ ] **H5. A scope computation failure is not read as a pass** — "Cannot check" message + exit 2.
- [ ] **H6. What the collect hook missed is reported** — A tool with no Post (`관찰 누락 — 실행 후 기록 없음` ("observation gap — no post-run record"); changed lines are still checked), a Post with no Pre (`실행 전 기록 없음` ("no pre-run record")), changes outside tools (`출처 미확인 변경` ("change of unknown origin")), errors in the collect hook itself (`수집 훅 오류` ("collect hook error")), linters that could not run within budget (check warning).
- [ ] **H7. The plugin's own files are not check targets** — `.claude/convention-guard/**` and `.claude/rules/**` are not flagged by their own rules.

---

## I. Performance budget

- [ ] **I1. The Stop hook finishes within budget** [auto]
  - Structure: Stop hook timeout 150s, linter stage cap 110s, `linters.timeout` **per linter** default 90s (sequential).
  - Why: If the hook dies on timeout it prints nothing, so it cannot be told apart from a pass.
  - Expect: The E1 check (with linters) PASS within 30s, FAIL over 110s.
  - If it fails: Lower `linters.timeout`, or move heavy linters to CI.

- [ ] **I2. Cost does not grow linearly as you add rules** [manual, development checkout]
  - Basis: `python3 tests/perf/run.py` — at 4.0 (WSL2, 3.12): 60-file Stop with nothing caught by the gate 57ms, one collect hook run 25–30ms, analyzing a 1,000-line file 4–7ms. Targets are in [design-4.0.md](../../design-4.0.md) (Korean) §7.

---

## J. Security and privacy

- [ ] **J1. Repo config cannot make it run arbitrary commands** [auto]
  - Basis: The repo `config.yaml` accepts only a closed set of keys. Linter commands live only in the plugin's `stacks/*.yaml` and run as `shell=False` list arguments.
  - Expect: No `shell=True` in the plugin scripts.
- [ ] **J2. The only external network call is the structure engine install** [auto] — The only module on the run path that imports network modules is `scripts/lib/engine/install.py`. Even it fetches only pinned wheels from `files.pythonhosted.org` and rejects them if they do not match the sha256 in `lock.json`. Linters use `npx --no-install`.
- [ ] **J3. Plugin artifacts are not picked up by the repo** [auto] — `firings.jsonl` and `convention-guard.db` are not in `git status`. The only things committed to the repo are `config.yaml`, `dismissed.yaml` and `rules/` under `.claude/convention-guard/`.
- [ ] **J4. Repo local rules are subject to code review** [manual] — Local rules can add regular expressions. A regex with catastrophic backtracking slows the hook down.
- [ ] **J5. The team knows what is kept in the logs** [manual] — `firings.jsonl` holds rule ids, file paths and fingerprints; dismissal and verdict reasons hold human-written text. It rotates once to `firings.jsonl.1` at 5MB; session state, the ledger and review batches are cleaned up after 7 days. The ledger keeps the content (compressed) of files the agent touched and of files that were already modified right before a Bash call, and is cleaned up when the session goes unused for 7 days.

---

## K. CI integration

The hooks are a local safety net; enforcement happens in CI.

- [ ] **K1. Check only the PR's changes, and do not read exit 2 as success** [auto — when a workflow file exists]
  ```yaml
  - uses: actions/checkout@v4
    with: { fetch-depth: 0 }          # without this there is no base ref → exit 2
  - run: python3 <plugin>/scripts/scan.py --range "origin/${{ github.base_ref }}..HEAD" --fail-on error --no-color
  ```
  - Exit codes: `0` pass / `1` at or above the threshold severity / `2` cannot check. **Do not wrap it in `|| true`.** Do not hardcode the default branch name; use `github.base_ref`.
  - [auto]: Looks for `scan.py` in `.github/workflows/*.yml` and `.gitlab-ci.yml`, and checks `fetch-depth: 0`, `--fail-on never` and `|| true`. If none is found, [manual].
- [ ] **K2. If you use semantic review rules, do not read "no verdict" as a pass** [manual] — `--review --fail-on-pending`.
- [ ] **K3. Machine-readable output** [manual] — `--json`.
- [ ] **K4. If you forked the plugin, put its own tests in CI** [manual]
  ```bash
  python3 -m pip install -r requirements-dev.txt   # dev dependencies (without PyYAML, the YAML parity comparison is skipped)
  python3 tests/run_all.py --repo /path/to/your-repo
  ```

---

## L. Operation — the first 2–3 weeks

- [ ] **L1. Collect 2–3 weeks of records with `report`** [manual]
- [ ] **L2. Look at rule health** [manual]
  ```bash
  CLAUDE_PLUGIN_DATA="<hook data directory from B4>" python3 <plugin>/scripts/log_report.py --repo .
  ```
  - Without `CLAUDE_PLUGIN_DATA` it reads a different directory and looks empty (B4). If you set `log_dir`, use `--log <log_dir>/firings.jsonl`.
  - Numbers to watch: **fix rate**, **dismissal rate**, semantic review **precision**, **new** (new violations created by fixes).
- [ ] **L3. Decision criteria** [manual] — High fix rate and low dismissal rate → `severity: error`, `mode: fix`. High dismissal rate → narrow it or turn it off (`rule-tune`). Not enough data → wait.
- [ ] **L4. Export all conventions to the agent context** [sandbox][manual]
  - `python3 <plugin>/scripts/setup.py emit --agents-md` — all applied rules and linters go into a managed block in AGENTS.md, and `@AGENTS.md` goes into CLAUDE.md. Human-written content is preserved (`tests/integration/test_setup_emit.py`).

---

## M. Rollback

- [ ] **M1. Make it harmless immediately**: `mode: report` in the repo `config.yaml`.
- [ ] **M2. Turn off per rule**: `disable: [core/rule-id]`.
- [ ] **M3. Remove completely**: Disable in `/plugin` (in the scope from B2). The only thing left in the repo is `.claude/convention-guard/`.
- [ ] **M4. Clear caches**: Delete the hook data directory from B4 and `~/.cache/convention-guard`.

---

## N. What this checklist does not verify

| Item | Status |
|---|---|
| Hook execution on native Windows (non-WSL) | **Unverified.** `hooks.json` calls `python3` (A2) |
| Monorepo with multiple stacks | Stack is decided only once at the root — split manually with `applies_to.files` / `exclude` |
| Decisions that need types or a call graph | Not a job for regexes. Use a linter or a semantic review rule |
| "Turn ended" ≠ "work done" | A turn that ended with an interim report may still be checked |
| Ignoring the semantic review request | The main agent can ignore it. After a re-request, `review_skipped` is logged |
| `--all` on huge repos (tens of thousands of files) | The performance corpus is about 60 files |
| Parallel Bash calls (no `tool_use_id`) | The event key is a tool+input hash, so when the same command overlaps, the later Pre overwrites the earlier one and the leftover Post is reported as "관찰 누락(pre_missing)" ("observation gap"). Leftover events are cleaned up on the next Stop |
| Does Claude follow the skills correctly? | Only the structure is checked automatically. Behavior is evaluated manually with `tests/skills/evals` (B6) |
