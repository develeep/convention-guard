# How it works

[README](../../../README.en.md) · [한국어](../ko/how-it-works.md) · **English**

This page explains the behavior that plugin users need to know. The module structure and design decisions are in the developer doc [architecture.md](../../architecture.md) (Korean).

## Contents
- What happens in one turn
- Who wrote the line: the edit-event ledger
- What becomes a candidate
- Blocking and re-verification
- Reading notices
- Dismissing false positives
- Semantic review
- State and logs
- Known limits

## What happens in one turn

```
Session start    if the structure engine (tree-sitter) is missing, install it in the background
   │
Each tool call   compare before and after Write·Edit·MultiEdit·NotebookEdit·Bash·mcp__*
   │            and record "who wrote it" for each line (no output, 0 agent context)
   │
Turn end (Stop) lines the agent wrote → regex gate → structure check → apply dismissals → candidates
                 ├ no candidates → pass. No AI call
                 ├ deterministic candidates → (mode: fix) block. The agent fixes or dismisses
                 └ semantic review candidates → ask the convention-reviewer agent for a verdict
   │
Next Stop       check the same scope again → fixed / dismissed / still / new
```

Stop means "turn end", not "task done". If the agent ends the turn with a question, the check is skipped (`skip_if_question`).

## Who wrote the line: the edit-event ledger

convention-guard does not read `git diff` at Stop time. It reads a ledger that records the provenance of lines **on every tool call**. So even inside one file, it checks only the lines the agent wrote.

| Origin | Meaning | Checked |
|---|---|---|
| Original line | A line that already existed when the ledger first saw the file (legacy) | No |
| Agent | A line that appeared between before and after an agent tool call | **Yes** |
| Someone else's commit | A line brought in when a Bash call moved HEAD, as with `git pull` | No |
| Unknown origin | A line changed outside a tool call (a person, an editor, a background process) | No, reported by name |

- Moving lines inside a file, or moving a file with `mv`, is not "writing". A line where only whitespace changed is a changed line.
- A spot where the agent only deleted lines (for example, emptying a catch block) is also recorded and gets checked.
- Committing does not change provenance. Changes committed during the session are also checked.
- `scan.py`, which is not a hook, has no ledger, so it looks at the changes git shows (`--staged`, `--range`, and so on).

## What becomes a candidate

For each rule, an **anchor** defines "what this change is responsible for". Examples: does an added line match the pattern, is a required declaration missing in a new file, was file A changed but not file B. Touching a file full of legacy violations does not flag the existing violations.

```
lines the agent wrote
  → regex gate             keep only lines that match the pattern. Most turns end here
  → structure condition    inside a comment or string? inside a loop, function, or catch? (tree-sitter)
  → dismissal records      drop code the team recorded as a false positive
  → candidates
```

- **A candidate is not a violation.** The regex only narrows things down. The verdict comes from the agent (or reviewer) that looks at the code.
- **Comments and strings are not code.** A commented-out `console.log(` or a `dd(` inside a string is not flagged. The inside of `${...}` in a template literal and `{...}` in an f-string counts as code.
- If linters are installed, checks are delegated per stack, and only failures on changed lines block.

Full list of anchors and structure conditions: [rules.md](rules.md)

## Blocking and re-verification

The same candidate is handled differently depending on `mode`.

| mode | error candidate | warn candidate |
|---|---|---|
| `report` (default) | Record it and show a one-line notice. Do not block | Record it and show a one-line notice |
| `fix` | **Block** the turn and pass the location, guidance, and dismiss command to the agent | Does not block on its own. Passed along when something else blocks |
| `auto-fix` | Same as `fix`, but rules with `fix.auto` are fixed automatically first | Same as `fix` |

A block opens a verification cycle. When the agent fixes things and ends the turn again, the same scope is checked again and the results fall into four groups.

| Result | Meaning |
|---|---|
| fixed | The flagged candidate is gone |
| dismissed | Recorded as a false positive |
| still | Still there (reformatting in place or moving it as a whole also counts as still) |
| new | A candidate that was not there at first — usually created by the fix just made |

If still or new includes an error, it blocks once more, up to `limits.max_verify_attempts` (default 1). After that, it only records what is left and closes. `limits.max_consecutive_blocks` (default 3) caps consecutive blocks within one request to prevent an infinite loop.

```
block → fix → re-verification: still → block (last) → fix → re-verification: still → record only and close
```

When a new request starts, the consecutive block count resets. If a violation left from the previous request shows up again, it is marked "지난 턴에도 지적했습니다" (flagged in the previous turn too).

## Reading notices

Hook output starts with one line: `convention-guard <icon> <word> — <summary>`. The icons are `✖` error, `⚠` warn, `ℹ` info, `✔` pass.

| What you see | Meaning | What to do |
|---|---|---|
| `✖ 차단 — error 1 · warn 0` (blocked) | In `fix` mode, there is an error candidate, so the turn is blocked | The agent fixes it or dismisses it |
| `✔ 재검증 통과 — 고쳐짐 1 · 기각 0` (re-verification passed — fixed 1 · dismissed 0) | Everything flagged was resolved | Nothing |
| `⚠ 재검증 종료 — … · 이후 기록만` (re-verification ended — … · record only from now on) | Hit the re-verification limit, so it records what is left and closes | A person checks the remaining violations |
| `✖ 기록 — error 1 · 차단 안 함: mode=report` (recorded — not blocked: mode=report) | `report` mode, so it records without blocking | Normal during adoption. Run `rule-tune` after 2–3 weeks |
| `⚠ 기록 — warn 1 (core/…)` (recorded) | Only warns, so no block | Fix if needed |
| `✖ 건너뜀 — 설정 오류: …` (skipped — config error) | Could not read a config, rule, or dismissal file, so nothing was checked | Fix the file |
| `✖ 건너뜀 — 내부 오류: …` (skipped — internal error) | An error in the plugin itself. The turn does not break | Report it as an issue |

Anything that could not be checked is reported by name so that it does not look like a pass.

| Notice | Meaning |
|---|---|
| `구조 엔진 없음 (설치 전 / 설치 중 / 설치 실패 / 미지원 플랫폼 / 꺼짐)` (no structure engine (not installed yet / installing / install failed / unsupported platform / off)) | Structure conditions could not be applied, so candidates are raised without filtering |
| `구조 미확인 N개 파일` (structure unverified in N files) | Matches after a spot the parser could not read are raised without checking |
| `관찰 누락 — 실행 후 기록 없음` / `실행 전 기록 없음` (missed observation — no after-run record / no before-run record) | The collection hook's Pre or Post did not arrive. Changed lines are checked as the agent's |
| `출처 미확인 변경` (change of unknown origin) | A file changed outside a tool (a person, an editor). Not checked |
| `작업 트리 관찰 실패` (working tree observation failed) | `git status` failed, so the files changed by a Bash/MCP call are unknown |
| `수집 훅 오류` (collection hook error) | The collection hook recorded its own exception |
| `큰 파일 미검사` (large file not checked) | Files over 400KB are skipped |
| `git 레포가 아니라 검사하지 않음` (not a git repo, not checked) | The project is not a git working tree |
| `검사 경고` (check warning) | Unknown config keys, a linter that did not finish within budget, and so on |

## Dismissing false positives

If a candidate is not a violation, do not fix it. Dismiss it. The block message includes the dismiss command as is.

```
$ python3 ".../scripts/dismiss.py" --key core/js-no-console:legacy.js:257280dd62 --by agent --reason "<one-line reason>"
```

A dismissal is stored in `.claude/convention-guard/dismissed.yaml` as `rule:file:code fingerprint`. The fingerprint is the content of that line, so it survives lines being added above, and the line is flagged again when it changes. Commit the file to share it with the team. Dismissals are the evidence `rule-tune` uses to find rules with false positives.

## Semantic review

For rules that a regex cannot decide, such as N+1 queries or layer boundaries, the `convention-reviewer` subagent gives a verdict using about one function's worth of context. This happens only when there is a candidate and no cached verdict. It is off by default. Details: [semantic-review.md](semantic-review.md)

## State and logs

| Location | Contents | Committed |
|---|---|---|
| `<repo>/.claude/convention-guard/config.yaml` | Team config | Yes |
| `<repo>/.claude/convention-guard/dismissed.yaml` | Dismissal records (`version: 4`) | Yes |
| `<repo>/.claude/convention-guard/rules/` | Repo-only rules, core rule overrides | Yes |
| `convention-guard.db` in the data directory | Ledger, cycle state, verdict cache, verdict batches (sqlite) | No |
| `engine/` in the data directory | Structure engine | No |
| `firings.jsonl` in the data directory | Firing log (can be moved with `log_dir`) | No |

The data directory location is in [installation.md](installation.md#install-location-and-data-directory). The log rotates once at 5MB, and session state, the ledger, and verdict batches are cleaned up after 7 days. If a plugin version change alters the storage format, the store is not migrated. It is created again.

The log keeps rule ids, file paths, code fingerprints, and dismissal and verdict reasons. The ledger keeps the contents (compressed) of files the agent touched.

## Known limits

- **Monorepos**: the stack is decided once at the repo root. If several stacks are mixed, all their rules turn on, so split them with a rule's `applies_to.files` and the config's `exclude`.
- **A regex is a regex.** Verdicts that need type inference or a call graph belong to linters (phpstan, tsc, mypy) or semantic review rules.
- **Human edits during a tool call**: if a person edits the same file at the moment an agent tool is running, those lines count as the agent's. If a person later edits a line the agent wrote, that line becomes unknown origin and drops out of the check.
- **A turn that ends with a progress report** can also be checked, because Stop means turn end.
- **The main agent can ignore a semantic review request.** It is asked once more, and after that it is recorded as `review_skipped`.
- **Files not checked**: files matched by `.gitignore`, files over 400KB (reported by name), and binaries.
- **Structure engine platforms**: musl aarch64 and free-threaded Python have no wheels, so they run without the engine.
- **Native Windows** is not tested. Use WSL.
