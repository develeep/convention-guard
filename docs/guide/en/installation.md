# Installation

[README](../../../README.en.md) · [한국어](../ko/installation.md) · **English**

## Contents
- Requirements
- Installing
- Turning it on for the whole team
- Values chosen at install (userConfig)
- Structure engine
- Install location and data directory
- Updating and removing
- Upgrading from 3.x

## Requirements

| Item | Condition | Check |
|---|---|---|
| Claude Code | A version that supports plugins | `claude --version` |
| Python | 3.10 or later runs as `python3` | `python3 --version` |
| git | The project to check is a git working tree | `git rev-parse --show-toplevel` |
| Network | Once, when the structure engine is first downloaded (`files.pythonhosted.org`, about 1.5MB) | If offline, see [Structure engine](#structure-engine) |

Hooks run as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/..."`. Some `python3` builds are 3.9, such as the one in macOS Command Line Tools, so check first. On 3.9 or earlier, the hook reports the required version and does not check.

Native Windows (not WSL) is an unverified environment. If `python3` is missing or is the Microsoft Store stub, hooks do not run. Use WSL, or run with `scan.py` and CI instead of hooks.

## Installing

There are three ways. The result is the same.

**Inside Claude Code** (use this the first time):

```
/plugin marketplace add develeep/convention-guard
/plugin install convention-guard@develeep-convention-guard
```

The install asks for [userConfig](#values-chosen-at-install-userconfig). You can keep the defaults.

**From the terminal**:

```bash
claude plugin marketplace add develeep/convention-guard
claude plugin install convention-guard@develeep-convention-guard            # default scope: user
claude plugin install convention-guard@develeep-convention-guard --scope local   # this repo only
```

A terminal install does not ask for userConfig. It prints `3 userConfig options not yet set`. If you leave them empty, the plugin runs with its defaults (`mode: report`). To set values, pass them at install, like `--config report_only=true`, or run `/plugin configure convention-guard@develeep-convention-guard` in Claude Code.

**Try it from a local checkout** (to modify the plugin, or to try it without installing):

```bash
git clone https://github.com/develeep/convention-guard
claude --plugin-dir ./convention-guard
```

After installing, **start a new Claude Code session**. Hooks and skills are loaded when a session starts.

Install scopes:

| Scope | Applies to | Written to |
|---|---|---|
| `user` | All my projects | `~/.claude/settings.json` |
| `project` | Everyone who opens this repo (committed) | `<repo>/.claude/settings.json` |
| `local` | This repo, only me | `<repo>/.claude/settings.local.json` |

## Turning it on for the whole team

With only the `user` or `local` scope, **only you** are checked. To turn it on for every team member, put the following in the repo's `.claude/settings.json` and commit it. When team members open Claude Code in this repo, they are prompted to add the marketplace and install.

```json
{
  "enabledPlugins": { "convention-guard@develeep-convention-guard": true },
  "extraKnownMarketplaces": {
    "develeep-convention-guard": {
      "source": { "source": "github", "repo": "develeep/convention-guard" }
    }
  }
}
```

Team settings (mode, rule severity, excluded paths) go separately in `.claude/convention-guard/config.yaml`, which you commit. To create it, see [convention-setup in skills.md](skills.md#convention-setup--adoption).

Before turning it on, to confirm it really works as intended in this repo, run the [adoption checklist](production-readiness.md) with the `convention-readiness` skill.

## Values chosen at install (userConfig)

| Key | Default | Effect |
|---|---|---|
| `report_only` | `true` | `true` means `mode: report` (record only), `false` means `mode: fix` (block) |
| `semantic_review` | `false` | Turns on semantic review (the convention-reviewer subagent) |
| `log_dir` | (empty) | Location of the firing log `firings.jsonl`. If empty, the plugin data directory |

If the repo's `config.yaml` has the same key (`mode`, `semantic_review.enabled`), **the repo setting wins.** This way, a personal setting cannot quietly lower the team standard.

Use an absolute path outside the repo for `log_dir`. A relative path like `./logs` resolves inside each repo, so logs scatter across repos and git picks them up.

All setting keys are in [configuration.md](configuration.md).

## Structure engine

To avoid treating code inside comments and strings as violations, a syntax tree is needed. convention-guard downloads and installs tree-sitter wheels by itself (it does not use venv or pip).

- **When**: when a session starts (SessionStart hook, in the background), when Stop needs the engine and it is missing (in the background), and when you run `engine.py ensure` yourself.
- **What**: it downloads only the wheels pinned in `scripts/lib/engine/lock.json`, and rejects any whose sha256 does not match.
- **Before install or on failure**: checks still run. Candidates whose structure conditions could not be confirmed are not filtered out, and it reports `구조 엔진 없음 (사유)` ("structure engine missing (reason)"). It does not treat them as passing.

```bash
python3 "$CG/scripts/engine.py" status    # whether it is installed, and where
python3 "$CG/scripts/engine.py" ensure    # install now and wait until done (for CI)
```

`$CG` is the plugin install path. Get it as shown [below](#install-location-and-data-directory).

In an offline environment, collect the wheel files listed in `lock.json` in one directory and run `ensure` with `CONVENTION_GUARD_WHEELS=<that directory>`. The sha256 check is the same. musl aarch64 and free-threaded Python have no wheels, so they run without the engine (`구조 엔진 없음 (미지원 플랫폼)` ("structure engine missing (unsupported platform)")).

## Install location and data directory

Skills call scripts through `${CLAUDE_PLUGIN_ROOT}`, so you do not need the path. You need the install path only when you run scripts directly from the terminal. The path changes with each version, so do not memorize it. Look it up.

```bash
CG=$(claude plugin list --json | python3 -c "import json,sys; print(next(p['installPath'] for p in json.load(sys.stdin) if p['id'].startswith('convention-guard@')))")
echo "$CG"    # e.g. ~/.claude/plugins/cache/develeep-convention-guard/convention-guard/4.1.0
```

When you use `--plugin-dir`, that checkout path is `$CG`.

| Location | Contents |
|---|---|
| `$CG` | Plugin code (scripts, rules, skills). Do not touch it |
| `~/.claude/plugins/data/convention-guard-develeep-convention-guard/` | The hooks' data directory (`CLAUDE_PLUGIN_DATA`): state store `convention-guard.db`, structure engine `engine/`, firing log `firings.jsonl` |
| `<repo>/.claude/convention-guard/` | Team settings `config.yaml`, dismissal records `dismissed.yaml`, repo-only rules `rules/`. Committed |

Scripts run directly from the terminal use `$XDG_CACHE_HOME/convention-guard` (or `~/.cache/convention-guard` if unset) when `CLAUDE_PLUGIN_DATA` is not set. This is a **different directory** from the hooks'. To see logs or verdicts the hooks collected from the terminal, prefix the command.

```bash
CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/convention-guard-develeep-convention-guard \
  python3 "$CG/scripts/log_report.py" --repo .
```

## Updating and removing

```bash
claude plugin update convention-guard@develeep-convention-guard      # restart the session to apply
claude plugin disable convention-guard@develeep-convention-guard     # turn off (stays installed)
claude plugin uninstall convention-guard@develeep-convention-guard   # remove
```

Inside Claude Code, do the same from the `/plugin` screen. If you turned it on for the whole team, also edit `enabledPlugins` in `.claude/settings.json`.

If you only want to stop blocking for now, do not remove it. Set `mode: report` in the repo's `config.yaml`. The only thing left in the repo is `.claude/convention-guard/`. To clean up state and caches, delete the data directory above and `~/.cache/convention-guard`.

## Upgrading from 3.x

4.0 breaks backward compatibility. There is no migration tool.

- A 3.x `dismissed.yaml` (a file without `version: 4`) is not applied, and you get a warning. Record your dismissals again.
- The verdict cache and session state are not read. They build up again from scratch.
- Delete `scope.base_ref` and `collect.edit_tools` from your settings. If they remain, you get the warning `알 수 없는 설정 … (무시)` ("unknown setting … (ignored)"). To check a whole branch, use `scan.py --range <base>..HEAD`.
- Go rules and presets were removed.
