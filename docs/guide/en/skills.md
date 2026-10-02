# Skills

[README](../../../README.en.md) · [한국어](../ko/skills.md) · **English**

Hooks run on their own. Skills let the agent do **work a person starts**, such as adoption, checks and rule management. Each skill contains a procedure: call scripts, judge the results and report.

## Contents
- How to invoke
- Which skill when
- convention-setup — adoption
- convention-check — check now
- convention-readiness — adoption check
- convention-discover — find conventions
- rule-add — create a rule
- rule-tune — tune rules
- The convention-reviewer agent

## How to invoke

Ask in plain words, and Claude Code picks the skill whose description matches. Requests work in any language.

```
Set up convention-guard
Check conventions before I open a PR
```

You can also call a skill by name. Plugin skills have the `convention-guard:` prefix.

```
/convention-guard:convention-setup
/convention-guard:convention-check only --staged
```

## Which skill when

From adoption to operation, use them roughly in this order.

```
convention-setup ─→ convention-readiness ─→ (2–3 weeks in report mode) ─→ rule-tune ─→ mode: fix
                                                    │
        convention-discover ─→ rule-add ←───────────┘  when you see a rule you need
convention-check: any time (right before a commit or PR, branch check)
```

| Skill | When | What to say |
|---|---|---|
| `convention-setup` | First adoption in a repo, or redoing settings from scratch | "Set up convention-guard" |
| `convention-check` | Check now without waiting for the hook | "Check conventions before I commit" |
| `convention-readiness` | Before turning it on in a team repo, right after an update, before moving to `fix` | "Run the adoption check" |
| `convention-discover` | Find the team's existing conventions and turn them into rule candidates | "Find our conventions and draft rules from them" |
| `rule-add` | Turn a recurring review comment into a rule | "Turn this pattern into a rule" |
| `rule-tune` | After logs build up: clean up false positives, promote, switch mode | "Clean up the rules" |

## convention-setup — adoption

Sets up convention-guard in a repo **from scratch**. If a `config.yaml` already exists, it asks once whether it may overwrite it, and stops if you say no (adjusting existing settings is `rule-tune`'s job).

The goal is not to turn on many rules. It is to make **everything that gets flagged real**.

1. **Detect**: check stacks, presets, applied rules and linters (`detect_stack.py`). If no marker file (`composer.json`, `package.json`, `pyproject.toml`, `requirements.txt`, etc.) is at the root, set `stacks:` by hand.
2. **Draft**: write `.claude/convention-guard/config.yaml` with `mode: report` (`setup.py init`).
3. **Measure → adjust**: measure how many hits actually occur in the last 20 commits and in the whole repo. Lower the `severity` of rules that hit a lot, and take legacy areas out with `exclude`. Repeat until the remaining findings are real violations.
4. **Export**: write all applied rules and linter commands into a managed block in `AGENTS.md` (`setup.py emit --agents-md`). If the agent knows them before writing, there are fewer blocks. Content outside the managed block is preserved, and an `@AGENTS.md` import is added to `CLAUDE.md`.
5. **Report**: stacks, number of applied rules, adjustments, number of remaining findings.

The resulting `.claude/convention-guard/config.yaml` and `AGENTS.md` are committed. For the first 2–3 weeks of adoption, use `report` to only collect records. Then decide on switching to `fix` with `rule-tune`.

## convention-check — check now

Checks now with **the same pipeline** as the Stop hook, opens each candidate to judge whether it is a violation, and reports only confirmed violations. On request, it fixes them and checks again.

| Request | Scope |
|---|---|
| (default) What changed now | Working tree |
| Right before a commit | `--staged` |
| Before opening a PR, the whole branch | `--base-ref auto` (everything since the merge-base with the default branch) |
| This file | `--files <path>` |
| Size of legacy, audit before adoption | `--all` (only when explicitly requested) |

- What the regex narrows down are **candidates**. The skill opens each location and judges it against the rule's guidance. Linter failures are confirmed violations and go first.
- If there are semantic review candidates, it runs again with `--review` to build a verdict batch and hands it to the `convention-reviewer` agent. Only the returned `VIOLATION`s are reported as violations.
- False positives are not waved off in words. Record a dismissal with `dismiss.py`. That way `rule-tune` can tell false positives apart from "not fixed".
- When fixing, start with errors, one rule at a time, and check the same scope again after each fix. For rules with auto-fix, you can apply `--fix --write` first.

All options: [scan.py in cli.md](cli.md#scanpy--manual-check)

## convention-readiness — adoption check

Checks every item of the [adoption checklist](production-readiness.md) to see whether it is safe to actually turn on in a team repo. `readiness.py` makes the verdicts. The skill lists how to fix each fail and warn, and the items a person must confirm.

- It gives verdicts on Python, install scope, hook wiring, userConfig, setting layers, personal rules, dismissal records, rule fixtures and reach, detection volume, performance, security and CI.
- Block, re-verification, semantic review and failure modes are confirmed by running the plugin's own tests in a sandbox with a temporary data directory. It does not touch the repo or the hooks' logs.
- High-impact changes, such as `.claude/settings.json`, personal `pluginConfigs` and the team `config.yaml`, are made **only after asking the user**.
- Verdict: 1 or more fail → not ready / only warn → conditional / only pass → ready. `? manual` ("manual check") and `○ skip` ("skipped") are reported separately as unconfirmed.

Run it from the directory where you open the Claude Code session. Project and local settings are read relative to that directory.

## convention-discover — find conventions

Finds conventions the team already has and builds a **candidate table with evidence**. It does not write rule files. It passes only the items the user picks to `rule-add`.

1. **Written down**: `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`, `.github/copilot-instructions.md`, `CONTRIBUTING.md`, convention docs in `docs/`, linter settings, review comments on recently merged PRs (using `gh`).
2. **Hidden in code**: reads samples from files changed often in the last 6 months and looks for recurring structure.
3. **Classify**: linter/formatter territory / deterministic rule / semantic review rule / guidance only / already applied.
4. **Measure**: for deterministic rules, count the actual compliance rate (compliant ÷ (compliant + violations)). For semantic review rules, look at the number of candidates the gate catches and sample verdicts. A compliance rate of 80% or more is recommended. Below 30%, the opposite practice is the norm, so it does not become a rule.

Conventions are numbers, not impressions. A practice you have not counted turns into a rule that leaves only false positives.

## rule-add — create a rule

Turns a recurring finding or convention item into a rule file and verifies false positives.

1. **Judge the value**: send formatting and import order to linters/formatters, and type inference to phpstan/tsc/mypy. These do not become rules.
2. **Location and severity**: if it is specific to this repo, `.claude/convention-guard/rules/<id>.yaml`. If it changes a core rule, an `override: core/<id>` file. New rules start at `warn`.
3. **Pick the anchor**: decide what "this change is responsible for". Pick wrong, and all legacy code gets flagged ([anchors in rules.md](rules.md#anchors-what-this-change-is-responsible-for)).
4. **Find examples**: find both violations and confusing compliant cases in the repo, and write them as `tests.match` and `tests.no_match`.
5. **Verification loop**: fixture tests → full scan of the repo → open a few results and check them yourself → if compliant code got flagged, add it to `no_match` and narrow the regex.
6. **Regenerate context**: rewrite AGENTS.md with `setup.py emit`.

Rules that a regex cannot judge (N+1, layer boundaries) become `semantic_review` rules ([semantic-review.md](semantic-review.md#writing-rules)).

## rule-tune — tune rules

Uses the firing log (`log_report.py`) to look at rule health, narrows or turns off false-positive rules, promotes healthy rules, and decides on the `report` → `fix` switch. Use it 2–3 weeks after adoption, or when there are too many findings or the agent seems to ignore them. If there are no logs yet, do `convention-setup` first.

| Metric | Meaning |
|---|---|
| Fix rate | fixed ÷ (fixed + remaining) |
| Dismissals | Number recorded as false positives — direct evidence of false positives |
| Newly introduced | Number of new violations of this rule made while fixing other findings |
| Precision | For semantic review rules, the share the reviewer judged `VIOLATION` |

| Action | Condition |
|---|---|
| Promote warn → error | Fix rate 70% or more, fixed + remaining 10 or more, no recurring dismissal reason |
| Demote error → warn | False positives remain and it is blocking work |
| Turn off (`disable`) | The team does not agree — after user confirmation |
| `mode: report` → `fix` | All block-severity rules are healthy, or there is not enough data |

When narrowing a condition, fix **the fixture first**. Add the real code that was a false positive to `tests.no_match`, confirm the failure, then narrow the regex. If you reverse the order, the same false positive comes back.

## The convention-reviewer agent

This is a subagent, not a skill. When the Stop hook or `scan.py --review` prints `convention-guard:convention-reviewer 에이전트에게 아래 명령 한 줄을 그대로 …` ("pass the one-line command below to the convention-guard:convention-reviewer agent as is …") followed by a `review.py show <batch>` command, the main agent calls it. You rarely need to call it yourself.

- It reads a verdict batch (`review.py show <batch>`) and records `VIOLATION`, `VALID` or `FALSE_POSITIVE` for each candidate (`review.py record`).
- It does not modify code (no Write or Edit tools). The default model is haiku.
- It returns only violations to the main agent, one line each. The code it read and its reasoning stay inside the subagent.

More: [semantic-review.md](semantic-review.md)
