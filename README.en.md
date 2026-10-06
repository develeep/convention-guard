# convention-guard

[한국어](README.md) · **English**

**Jump to**: [What makes it different](#what-makes-it-different) · [Quick start (5 minutes)](#quick-start-5-minutes) · [Adopting it in a team repo](#adopting-it-in-a-team-repo) · [Skills](#skills) · [Terminal and CI](#terminal-and-ci) · [Learn more](#learn-more) · [Known limits](#known-limits)

A Claude Code plugin that checks, every time an AI coding agent ends its turn, whether **the lines the agent wrote** follow your team's conventions. If they don't, it makes the agent fix them and then **verifies the fix**.

Writing conventions into `CLAUDE.md` or `AGENTS.md` is not enough: in a long session they fade. convention-guard does not ask the agent to remember. It sets up an environment where the work is checked again at the end of every turn, even if the agent forgot.

When the agent tries to end its turn with a debug log left in, the Stop hook blocks it like this. The plugin prints its messages in Korean; English glosses follow each sample.

```
convention-guard ✖ 차단 — error 1 · warn 0

■ 지적 — 고치거나 기각하세요
✖ error[core/js-no-console]: console 잔여물
  legacy.js:7  console.log(add(1, 2));
  = 안내: 디버그 로그가 남아 있습니다. 제거하거나 팀 로거로 교체하세요.
```

(Blocked — error 1 · warn 0. Findings — fix or dismiss them. `console` leftover at `legacy.js:7`. Hint: a debug log is left in; remove it or switch to the team logger.)

Once the agent fixes the line and ends its turn again, the same scope is checked again and the result is reported.

```
convention-guard ✔ 재검증 통과 — 고쳐짐 1 · 기각 0
```

(Re-verification passed — fixed 1 · dismissed 0.)

The `console.log("legacy")` that was already on line 1 of the same file was not flagged, because the agent did not write it.

## What makes it different

- **It looks only at the lines the agent wrote.** On every tool call it compares the content before and after and records where each line came from. It does not react to existing legacy code, lines a person edited alongside, or other people's commits brought in by `git pull`.
- **Comments and strings are not code.** A commented-out `console.log(` or a `dd(` inside a string is not flagged. The decision is made on a tree-sitter syntax tree, and the plugin installs that engine itself.
- **A candidate is not a violation.** Regexes only narrow down candidates; the agent that looked at the code makes the call. False positives are recorded as dismissals and are not raised again while that code stays the same.
- **Nothing to judge, no AI calls.** Only rules that regexes cannot decide, such as N+1 queries or layer boundaries, go to a subagent, and only when there is a candidate with no recorded verdict. The subagent judges from about one function's worth of context. Conventions with no regex signal at all (no business logic in controllers, for example) are judged per function when the agent adds code to the files they name.
- **It tells you what it missed.** If a collect hook died or the structure could not be read, it says so by name. Something it could not check never looks like a pass.

It ships 34 rules for Laravel·PHP·Blade, Next·React·Nest·JS/TS and Python, and you can add your team's rules in YAML.

## Quick start (5 minutes)

In an empty practice repo, watch one block → fix → re-verify cycle.

**You need**: Claude Code, `python3` 3.10 or later, git.

```bash
python3 --version    # 3.10 or later?
```

### 1. Install

```bash
claude plugin marketplace add develeep/convention-guard
claude plugin install convention-guard@develeep-convention-guard
```

Inside Claude Code, `/plugin marketplace add develeep/convention-guard` and `/plugin install convention-guard@develeep-convention-guard` do the same. Install scopes, turning it on for the whole team, and offline installs are in the [installation guide](docs/guide/en/installation.md).

### 2. Create a practice repo

```bash
mkdir cg-demo && cd cg-demo && git init -q
echo '{"name":"cg-demo","private":true}' > package.json     # detected as a JS repo
printf 'console.log("legacy");\n' > legacy.js                # an existing legacy line
mkdir -p .claude/convention-guard
cat > .claude/convention-guard/config.yaml <<'EOF'
mode: fix                     # block the turn on a violation (default is report: record only)
severity:
  core/js-no-console: error   # for this demo: raise a warn rule to blocking strength
EOF
git add -A && git commit -qm init
```

### 3. Give Claude Code a task

Run `claude` in the same directory and ask for this. Allow file edits when asked.

```
At the bottom of legacy.js, add an add function that adds two numbers, and print the result of add(1, 2) with console.log. If a convention finding comes up, you may fix it as it says.
```

### 4. See the result

When the agent writes the code and tries to end its turn, the `✖ 차단` (blocked) message above appears. The agent deletes the `console.log` line it just wrote, and the turn ends with `✔ 재검증 통과 — 고쳐짐 1` (re-verification passed — fixed 1). The legacy `console.log` on line 1 stays as it was.

In the very first session the structure engine may still be installing in the background, so you may also see `구조 엔진 없음 (설치 중)` ("structure engine missing (installing)"). The check still runs, and the notice goes away once the install finishes.

When you are done, remove it with `cd .. && rm -rf cg-demo`.

## Adopting it in a team repo

In the demo you wrote the config by hand. In a real repo, let the agent do it. Open Claude Code in the repo and say **"Set up convention-guard"**. The `convention-setup` skill then:

1. Detects the stack, linters and formatters, and shows which rules will apply.
2. Writes a draft `.claude/convention-guard/config.yaml` in `mode: report` (record only).
3. Measures how many findings the last 20 commits would actually produce, and tunes rules that fire too often and legacy directories.
4. Exports every applicable rule to `AGENTS.md`, so the agent knows them **before** it writes.

After that:

- **Check before turning it on**: "Run the adoption check" → `convention-readiness` runs the [adoption checklist](docs/guide/en/production-readiness.md) automatically. It also covers how to turn the plugin on for every teammate.
- **Record for 2–3 weeks**: `report` mode does not block; it only records.
- **Tune and switch**: "Clean up the rules" → `rule-tune` narrows false-positive rules using fix and dismissal rates, and suggests moving to `mode: fix` when the rules are healthy.

`config.yaml`, `dismissed.yaml` and `rules/` under `.claude/convention-guard/` are all meant to be committed. Example: [examples/repo-local/](examples/repo-local/)

## Skills

Ask in plain words and the matching skill is chosen. You can also call one directly as `/convention-guard:<skill>`.

| Skill | When |
|---|---|
| `convention-setup` | Adopting it in a repo for the first time, or setting it up again from scratch |
| `convention-check` | Checking now instead of waiting for the hook (before a commit or PR, a whole branch, a legacy audit) |
| `convention-readiness` | Before turning it on in a team repo, right after an update, before moving to `fix` |
| `convention-discover` | Finding your team's conventions in CLAUDE.md, PR reviews and code, and turning them into rule candidates |
| `rule-add` | Turning a recurring review comment into a rule |
| `rule-tune` | After logs build up: narrowing false-positive rules and promoting healthy ones |

What each skill does and how to use it: [docs/guide/en/skills.md](docs/guide/en/skills.md)

## Terminal and CI

You can run the scripts the skills call yourself. They use the same pipeline, so they never judge differently from the hook.

```bash
CG=$(claude plugin list --json | python3 -c "import json,sys; print(next(p['installPath'] for p in json.load(sys.stdin) if p['id'].startswith('convention-guard@')))")

python3 "$CG/scripts/scan.py" --staged                   # check before a commit. exit 0 pass / 1 findings / 2 could not check
python3 "$CG/scripts/scan.py" --range origin/main..HEAD  # changes on a branch
python3 "$CG/scripts/detect_stack.py"                    # what was detected, and which rules apply and why
```

The hook is each developer's local safety net; team-wide enforcement belongs in CI. A GitHub Actions example and every script option are in [docs/guide/en/cli.md](docs/guide/en/cli.md).

## Learn more

| Document | Contents |
|---|---|
| [Installation](docs/guide/en/installation.md) | Requirements, install scopes, turning it on for the team, userConfig, structure engine, updating and removing, upgrading from 3.x |
| [Skills](docs/guide/en/skills.md) | What the six skills and the reviewer agent do, and how to use them |
| [How it works](docs/guide/en/how-it-works.md) | Line provenance, what becomes a candidate, blocking and re-verification, reading notices, dismissals, state and logs, limits |
| [Commands](docs/guide/en/cli.md) | All script options such as `scan.py`, exit codes, CI |
| [Configuration](docs/guide/en/configuration.md) | Every setting, mode, presets, linter delegation, environment variables, configuration errors |
| [Rules](docs/guide/en/rules.md) | Rule file format, anchors, structure conditions, overrides, presets, bundled rules |
| [Semantic review](docs/guide/en/semantic-review.md) | Subagent review flow, context pack, verdict cache, cost |
| [Adoption checklist](docs/guide/en/production-readiness.md) | Everything to confirm before turning it on in production |

Documents for people who change the plugin itself are separate and in Korean: [architecture](docs/architecture.md), [development](docs/development.md), [output format](docs/output-format.md), [4.0 design](docs/design-4.0.md).

> **Coming from 3.x?** 4.0 breaks backward compatibility. It does not read 3.x dismissals or verdict caches, and some settings and the Go rules were removed. See [the 3.x section of the installation guide](docs/guide/en/installation.md#upgrading-from-3x).

## Known limits

The stack is detected once at the repo root, so a monorepo has to be split by path; checks that need type inference belong to linters; and native Windows is not verified. The full list is in [How it works: Known limits](docs/guide/en/how-it-works.md#known-limits).

## License

MIT
