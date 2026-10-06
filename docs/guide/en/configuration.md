# Configuration

[README](../../../README.en.md) · [한국어](../ko/configuration.md) · **English**

## Contents
- Precedence and location
- All keys
- mode
- presets
- limits
- Linter delegation
- userConfig
- Environment variables
- Configuration errors

## Precedence and location

```
plugin config.yaml  <  userConfig (values chosen at install)  <  <repo>/.claude/convention-guard/config.yaml
```

The repo config is final. A personal setting cannot quietly weaken the team standard.
Write only the keys you change in the repo config. If you set only some keys of a group (`limits` etc.), the rest keep their defaults.

Generate a draft: `python3 scripts/setup.py init --stdout`

## All keys

| Key | Default | Description |
|---|---|---|
| `mode` | `report` | `report` record only / `fix` block / `auto-fix` auto-fix safe rules, then block |
| `presets` | `auto` | `auto` or a list. Can be mixed, like `[auto, architecture]` |
| `stacks` | `[]` | Force only when detection misses |
| `disable` | `[]` | Rule ids to turn off |
| `severity` | `{}` | Per-rule severity. `core/php-line-too-long: warn` |
| `exclude` | `[]` | Path globs not to check. (Files over 400KB and binaries with a NUL in the first 8KB are skipped regardless of settings, and large files are reported as "큰 파일 미검사" ("large file not checked")) Same syntax as rules; here `legacy/` reads as `legacy/**`, and a leading `/` means the repo root |
| `limits.max_error_rules` | 4 | Number of error rules shown at once |
| `limits.max_warn_rules` | 3 | Number of warn rules sent along when blocking |
| `limits.max_locations_per_rule` | 3 | Locations per rule |
| `limits.max_consecutive_blocks` | 3 | Cap on consecutive blocks within one request. Reset when a new request starts or on a turn with nothing to block |
| `limits.max_verify_attempts` | 1 | Times verification blocks again for remaining/new violations |
| `linters.enabled` | `true` | Per-stack linter delegation |
| `linters.timeout` | 90 | Seconds per linter command |
| `semantic_review.enabled` | `false` | Semantic review |
| `semantic_review.max_candidates` | 5 | Candidates per batch |
| `semantic_review.context_budget_lines` | 400 | Context lines per batch |
| `semantic_review.verdict_ttl_days` | 30 | Verdict cache lifetime |
| `skip_if_question` | `true` | Skip the check when the agent ends its turn with a question |
| `respect_supersede` | `true` | Disable the matching format rules when a formatter config exists |
| `once_per_session` | `true` | A rule fixed in the session is not flagged again (dismissals do not use the budget) |

## mode

| mode | Deterministic error | Semantic review request | Auto-fix |
|---|---|---|---|
| `report` | Record + one-line summary, no block | No | No |
| `fix` | Block → verification cycle | Request if there are candidates | No |
| `auto-fix` | Same as `fix` | Same as `fix` | Apply `fix.auto` rules first |

For the first 2–3 weeks of adoption, we recommend `report` to collect logs, checking rule health with the `rule-tune` skill, then moving up to `fix`.

## presets

`auto` means `common`, `security`, and the presets that overlap the detected stack tags. `architecture`, `performance` and `layering` turn on only when listed explicitly. List: [rules.md](rules.md#presets)

```yaml
presets: [auto, architecture]     # auto + layer-boundary semantic review
presets: [laravel, security]      # only the chosen ones (common·php·psr12 are left out)
```

## limits

The consecutive-block cap and the verification count together prevent loops.

```
block(1) → fix → verify: remains → block(2, last verification) → fix → verify: remains → record only and end
```

`max_consecutive_blocks` is a loop guard within one request. After it trips, it only records while violations remain within the same request. It resets when a new request starts (a Stop that is not a continuation), so violations left from the previous request do not block new violations in the next request. Violations that show up again across requests are marked "지난 턴에도 지적했습니다" ("flagged in the previous turn too").

## Linter delegation

This is the `lint` entry in `stacks/*.yaml`.

```yaml
lint:
  - cmd: ["./vendor/bin/phpstan", "analyse", "--error-format=raw", "{files}"]
    if_exists: vendor/bin/phpstan       # skipped quietly if missing
    files: ["**/*.php"]                 # files this linter receives
    parse: unix                         # how file:line is read from the output
```

| parse | Output format |
|---|---|
| `eslint-json` | `eslint --format=json` |
| `phpstan-json` | `phpstan --error-format=json` |
| `unix` | `file:line[:col]: message` |
| `github` | `::error file=...,line=...` |
| `diff` | Unified diff (`pint --test -v`, `php-cs-fixer --diff`) |

If a parsed location is on a **changed line**, it blocks. If it is on another line of the same file, it is passed along as a note only. If `parse` is missing or the output cannot be read, it blocks with the whole output (dropping a real failure is worse). `{dirs}` is replaced with the list of directories of the changed files.

`detect_stack.py` shows, per linter, `= 참고: parse … — 변경 줄만 차단` ("note: parse … — block changed lines only") / `= 참고: 출력 파싱 불가 — 전체 출력으로 차단` ("note: output cannot be parsed — block with full output") / `= 참고: 설치 안 됨 — 건너뜀` ("note: not installed — skipped").

## userConfig

Values chosen when installing the plugin.

| Key | Effect |
|---|---|
| `report_only` | `true` → `mode: report`, `false` → `mode: fix`. If not chosen, the plugin default (`report`). If the repo config has `mode`, that wins |
| `semantic_review` | `semantic_review.enabled` |
| `log_dir` | Location of `firings.jsonl` (do not choose a repo path — git picks it up) |

4.0 has no setting that widens the hook's check scope (3.x `scope.base_ref`) and no list of MCP tools to collect
(3.x `collect.edit_tools`). The hook checks only the **lines the agent wrote**, as recorded by the edit-event ledger,
and observes every MCP tool call. To look at a whole branch, use `scan.py --range <base>..HEAD`.
Leftover old keys become an "알 수 없는 설정 (무시)" ("unknown setting (ignored)") warning (in the hook, a `검사 경고` ("check warning") on a turn that ran the check).

## Environment variables

| Variable | Effect |
|---|---|
| `CLAUDE_PLUGIN_DATA` | Location of the state store (`convention-guard.db`) and the structure engine. Claude Code passes it to hooks. If missing, `$XDG_CACHE_HOME/convention-guard`, then `~/.cache/convention-guard` |
| `CONVENTION_GUARD_ENGINE_DIR` | Structure engine install directory (default: `$CLAUDE_PLUGIN_DATA/engine`) |
| `CONVENTION_GUARD_NO_ENGINE` | If non-empty (any value — even `0`), the structure engine is not used — every structure condition becomes UNKNOWN and it reports "구조 엔진 없음 (꺼짐)" ("no structure engine (off)") |
| `CONVENTION_GUARD_WHEELS` | Offline install: a directory holding the wheels listed in `lock.json`. Installs from here instead of downloading; the sha256 check is the same |

## Configuration errors

When the configuration is wrong, it does not check by guessing.

| Situation | Hook | scan.py / detect_stack.py |
|---|---|---|
| config parse failure, unknown mode, missing preset | Skip the check and report the reason | Exit code 2 |
| `dismissed.yaml` parse failure | Same — does not check while ignoring dismissals | Same |
| `dismissed.yaml` has no `version: 4` (pre-4.0 format) | Warn and do not apply those dismissals | Same — `dismiss.py` does not append to that file |
| Rule file error | Same | Same |
| Unknown key | Ignore, and report as `검사 경고` on a turn that ran the check | Warning |
