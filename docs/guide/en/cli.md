# Commands

[README](../../../README.en.md) · [한국어](../ko/cli.md) · **English**

This page shows how to run the scripts that the skills call directly from a terminal or CI. Run every script as `python3 <path>`. Below, `$CG` is the plugin install path ([how to find it](installation.md#install-location-and-data-directory)).

## Contents
- At a glance
- scan.py — manual check
- detect_stack.py — what applies
- setup.py — config draft and context docs
- dismiss.py — dismiss false positives
- log_report.py — rule health
- readiness.py — adoption check
- engine.py — structure engine
- review.py — semantic review batches
- CI

## At a glance

| Script | What it does | Usually called from |
|---|---|---|
| `scan.py` | Checks without hooks. Exit code 0/1/2 | convention-check, CI |
| `detect_stack.py` | Detected stacks, presets, applied rules, linters, and the reasons | convention-setup |
| `setup.py` | `init` writes a config draft, `emit` writes the rules to AGENTS.md and others | convention-setup, rule-add |
| `dismiss.py` | Records a false positive in `dismissed.yaml` | the hook's block message, convention-check |
| `log_report.py` | Per-rule fix rate, dismissal rate, and precision from the firing log | rule-tune |
| `readiness.py` | Automatic check of the adoption checklist | convention-readiness |
| `engine.py` | Structure engine status and install | convention-setup skill, CI |
| `review.py` | View and record semantic review batches | convention-reviewer agent |
| `collect.py` · `check.py` | Hook entry points (Pre·PostToolUse / Stop) | `hooks/hooks.json` — do not run directly |

Most scripts can check another repo with `--cwd <repo>` (default: the current directory), and they share the same output format. Errors go to stderr as `convention-guard: error: …`.

## scan.py — manual check

Runs the same pipeline as the Stop hook. For the same change it gives the same result as the hook. The difference: the hook looks only at **lines the agent wrote**, while `scan.py` looks at the changes git shows.

```bash
python3 "$CG/scripts/scan.py"                         # working tree (default)
python3 "$CG/scripts/scan.py" --staged                # right before a commit
python3 "$CG/scripts/scan.py" --range main..HEAD      # changes on a branch
python3 "$CG/scripts/scan.py" --files app/X.php       # whole given files
python3 "$CG/scripts/scan.py" --all --severity error  # full-repo audit (legacy audit)
```

**Scope** (pick one)

| Option | What is checked | What counts as an "added line" |
|---|---|---|
| (none) | Working tree: changes against HEAD + new files | Added lines |
| `--staged` | Staged changes (contents are also read from the index) | Added lines |
| `--range A..B` | A revision range (contents are read from B) | Added lines |
| `--files a b …` | The whole given files | The whole file is treated as a new file |
| `--all` | Every text file among tracked files and new files that are not ignored | The whole file is treated as a new file |
| `--base-ref <ref>` | (With the working tree) adds changes against `<ref>` to changes against HEAD. `auto` means the merge-base with the default branch | Added lines |

**Output and filters**

| Option | Effect |
|---|---|
| `--severity error\|warn\|info` | **Print** only this severity and above (default info). The exit code is still based on all findings |
| `--rule <part of id>` | Only rules whose id contains this string (all of them if several match) |
| `--no-lint` | Skip linter delegation (faster) |
| `--no-dismiss` | Ignore dismissal records and show everything — use it to see what is suppressed |
| `--max-hits N` | Number of locations per rule (default 10) |
| `--json` | Machine-readable form. Includes `summary` (counts, `exit_code`), `scope`, `findings`, `review`, `fixes`, `unchecked`, and more |
| `--no-color` | Turn off color |

**Fixes, verdicts, CI**

| Option | Effect |
|---|---|
| `--fix` | Shows automatic fixes for rules that have `fix.auto` |
| `--fix --write` | Applies the fixes and reports what is left |
| `--review` | Builds a verdict batch from semantic review candidates, and includes cached `VIOLATION` verdicts in the result |
| `--fail-on error\|warn\|info\|never` | Exit code 1 if anything at this severity or above exists (default error) |
| `--fail-on-pending` | With `--review`, exit code 1 if any candidate still waits for a verdict |
| `--require-engine` | Exit code 2 if structure conditions could not be checked because the structure engine is missing |

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Pass — below the `--fail-on` threshold. There may still be warn or info candidates, so read the output |
| `1` | A finding at or above `--fail-on`, a linter failure on a changed line, or verdicts pending under `--fail-on-pending` |
| `2` | Could not check — not git, range could not be resolved, path outside the repo, error in a rule, config, or dismissal file, or (with `--require-engine`) no engine |

`2` does not mean "no findings". It means the check did not finish. Look at stderr.

Without `--review`, semantic review candidates do not affect the exit code. They only appear at the end of the output under `■ 다음` (next) as `semantic 규칙 후보 N건` (N semantic rule candidates).

## detect_stack.py — what applies

```bash
python3 "$CG/scripts/detect_stack.py"            # --cwd <repo>, --json
```

Shows the config file location, detected stack tags, enabled presets, the status of each linter, and every bundled rule as `✔ on` / `○ off` with the reason (`preset 비활성` (preset disabled), `스택/버전 불일치` (stack/version mismatch), superseded, config disable, or a severity change such as `warn->error`).

Read the `= 참고:` (note) on a linter line like this.

| Shown | Meaning |
|---|---|
| `설치 안 됨 — 건너뜀` (not installed — skipped) | The linter binary is missing, so it does not run |
| `parse … — 변경 줄만 차단` (parse … — block changed lines only) | Reads the output and blocks only failures on changed lines |
| `출력 파싱 불가 — 전체 출력으로 차단` (output cannot be parsed — block on full output) | Old errors unrelated to this change can also block — see [linter delegation](configuration.md#linter-delegation) |

If there is a config error, the exit code is 2.

## setup.py — config draft and context docs

```bash
python3 "$CG/scripts/setup.py" init --stdout              # preview a config.yaml draft fitted to this repo
python3 "$CG/scripts/setup.py" init                       # write .claude/convention-guard/config.yaml (exit code 1 if it exists)
python3 "$CG/scripts/setup.py" init --force               # overwrite the existing file
python3 "$CG/scripts/setup.py" emit --agents-md --stdout  # all applied rules + linters as an AGENTS.md managed block (preview)
python3 "$CG/scripts/setup.py" emit --agents-md           # write to AGENTS.md and add @AGENTS.md to CLAUDE.md
python3 "$CG/scripts/setup.py" emit --claude-md           # as a CLAUDE.md managed block
python3 "$CG/scripts/setup.py" emit                       # as per-path files in .claude/rules/ (--out <directory>)
```

The `init` draft uses `mode: report`. `emit` keeps human-written content outside the managed block. For each rule it writes the `prevent:` line if there is one, otherwise `제목 — message 첫 문단` (title — first paragraph of message).

## dismiss.py — dismiss false positives

If a candidate is not a violation, do not fix it. Record a dismissal. A dismissal is stored under the key `rule:file:code fingerprint`, and it is not flagged again **as long as that code stays the same**. It survives line numbers shifting because lines were added above, and it is released when that line changes.

```bash
# the key exactly as the hook's block message showed it
python3 "$CG/scripts/dismiss.py" --key core/js-no-console:src/log.js:257280dd62 --reason "output of a CLI" --by agent
# by location
python3 "$CG/scripts/dismiss.py" --rule core/js-no-console --file src/log.js --line 7 --reason "output of a CLI"
python3 "$CG/scripts/dismiss.py" --list
```

| Option | Effect |
|---|---|
| `--rule` `--file` `--line` | The location to dismiss (checks that line again to get the fingerprint) |
| `--key rule:file:fingerprint` | Records it as is, without checking again |
| `--reason "<one line>"` | Why it is not a violation (required) |
| `--by agent\|human` | Who made the call (default human) |
| `--whole-file` | Turns this rule off for the whole file |
| `--all-identical` | When the same code appears in several places in the file, dismisses all of them |
| `--list` | The list of recorded dismissals |

Commit `.claude/convention-guard/dismissed.yaml` to share it with the team. It is the record of exceptions the team agreed on.

## log_report.py — rule health

```bash
CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/convention-guard-develeep-convention-guard \
  python3 "$CG/scripts/log_report.py" --repo . --since 21
```

| Option | Effect |
|---|---|
| `--repo <path>` | Only events from this repo |
| `--since N` | The last N days |
| `--log <path>` | Set the log file directly (`<log_dir>/firings.jsonl` if you changed `log_dir`) |
| `--json` | Machine-readable form |

Without `CLAUDE_PLUGIN_DATA`, it reads a different directory from the hook and looks empty ([data directory](installation.md#install-location-and-data-directory)). How to read the numbers is in [rule-tune in skills.md](skills.md#rule-tune--tune-rules).

## readiness.py — adoption check

```bash
python3 "$CG/scripts/readiness.py"            # full (~10 seconds)
python3 "$CG/scripts/readiness.py" --quick    # skip sandbox tests and measurements (~1 second)
```

| Option | Effect |
|---|---|
| `--quick` | Only install and config items |
| `--all` | Include the error count of a full-repo audit (slow on large repos) |
| `--commits N` | Number of recent commits used to measure detection volume (default 20) |
| `--cwd` `--json` | Repo path, machine-readable form |

Each output line is one item id of the [adoption checklist](production-readiness.md). Exit code `0` no fail / `1` some fail / `2` not a git repo.

## engine.py — structure engine

```bash
python3 "$CG/scripts/engine.py" status    # install path and platform. --json
python3 "$CG/scripts/engine.py" ensure    # install if missing and wait until done. --quiet
```

`--dir <directory>` changes the engine location (default: `engine/` in the data directory). `lock` and `verify-lock` are for plugin developers who update and verify the pinned wheels.

## review.py — semantic review batches

This is the tool the convention-reviewer agent uses. A person needs it mostly to look at verdict history.

```bash
python3 "$CG/scripts/review.py" show    "<batch ref>"   # view a batch (--json)
python3 "$CG/scripts/review.py" summary "<batch ref>"   # verdict summary
python3 "$CG/scripts/review.py" record  "<batch ref>" < verdicts.json   # record verdicts (for the reviewer)
```

`record` reads a JSON array from stdin with `{"id": 1, "verdict": "VIOLATION", "reason": "…"}` for each candidate id. A verdict is one of `VIOLATION`, `VALID`, `FALSE_POSITIVE`, and every id must have a reason or nothing is recorded.

For the batch ref (`<db path>#<number>`), use the exact string the Stop hook or `scan.py --review` gave you.

## CI

Hooks are each developer's local safety net. Team-wide enforcement happens in CI. CI has no Claude Code, so fetch the plugin repository and run `scan.py` directly.

```yaml
# .github/workflows/conventions.yml
on: pull_request
jobs:
  conventions:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # without this there is no base ref, so exit code 2
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: git clone --depth 1 https://github.com/develeep/convention-guard "$RUNNER_TEMP/cg"
      - run: python3 "$RUNNER_TEMP/cg/scripts/engine.py" ensure
      - run: >-
          python3 "$RUNNER_TEMP/cg/scripts/scan.py"
          --range "origin/${{ github.base_ref }}..HEAD"
          --fail-on error --require-engine --no-color
```

- **Use the exit code as is.** If you wrap it in `|| true`, `2` (could not check) reads as a pass. Do not hardcode the default branch name. Use `github.base_ref`.
- `engine.py ensure` installs the structure engine, and `--require-engine` turns a result that skipped structure conditions for lack of an engine into a failure (2).
- Early in adoption, use `--fail-on never` to only leave a report. Raise it to `error` after reading the logs.
- If you use semantic review rules, add `--review --fail-on-pending`. CI has no reviewer and no verdict cache, so without it, candidates still waiting for a verdict read as a pass. With it, CI fails while candidates wait for a verdict, so get the verdicts in a local session first.
- To pin the plugin version, check out a specific commit instead of `git clone`.
- You can connect other tools through `summary.exit_code` in the `--json` output.
