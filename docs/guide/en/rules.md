# Rules

[README](../../../README.en.md) · [한국어](../ko/rules.md) · **English**

## Contents
- Rule layers
- File format
- Anchors: what this change is responsible for
- Structure conditions: what the match sits in
- Fixtures and scenario tests
- Overrides
- Presets
- Bundled rule list

## Rule layers

| Layer | Location | id |
|---|---|---|
| core | plugin `rules/**` | `core/<id>` |
| user | `~/.claude/convention-guard/rules/` | `user/<id>` |
| local | `<repo>/.claude/convention-guard/rules/` | `local/<id>` |

Later layers override earlier ones. Local and personal rules always load regardless of presets. Core rules load only when they belong to an active preset.

## File format

Rule files are read with the built-in YAML parser (`miniyaml`). PyYAML is not used even if installed, so files never read differently from machine to machine. The trade-off: multi-line flow lists (`[a,\n b]`) cannot be read, so write block lists (`- a`).

Full field descriptions and validation rules are in `skills/rule-add/references/schema.md`. Complete examples per anchor are in `skills/rule-add/references/examples.md`. Tests actually load and validate the examples in both documents.

```yaml
id: laravel-controller-needs-validation
title: No validation in store/update controller action
severity: error                     # error | warn | info
applies_to:
  stacks: [laravel]                 # required
  files: ["app/Http/Controllers/**/*.php"]
  exclude: ["**/vendor/**"]
detect:
  when_line_added: 'public\s+function\s+(store|update|create)\s*\('
  must_contain_in_file: '(FormRequest|Http\\Requests|->validate\(|->validated\(\)|Validator::make\()'
  must_not_in: [comment, string]    # a required element inside a comment or string counts as absent
message: |
  You added a write action, but there is no validation anywhere in this file.
  Create a FormRequest, accept it via type hint, and use $request->validated().
prevent: Accept write actions (store/update/create) with a FormRequest and use $request->validated().
tests:
  match: ["..."]
  no_match: ["..."]
```

| Severity | Behavior |
|---|---|
| error | Blocks (mode: fix / auto-fix) |
| warn | Does not block on its own; sent along when an error blocks |
| info | Record only |

## Anchors: what this change is responsible for

If a rule reacts to legacy code, it gets turned off within two weeks of adoption. So each anchor defines "this change" differently.

"Added lines" are determined differently per entry point.

- **Hook**: the **lines the agent wrote**, as recorded by the edit-event ledger ([architecture.md](../../architecture.md#편집-사건-원장) (Korean)). Lines written by people, lines that were already there, and lines brought in by someone else's commit are not included. A line deleted and rewritten in the same tool call (moved lines, `mv`) is not a written line, and a moved-in file is not a new file. Provenance stays the same after a commit.
- **CLI** (`scan.py`): based on `git diff --diff-algorithm=histogram`. The same change reads as the same lines regardless of the user's `diff.algorithm` setting. `git mv` (70% similarity or more) adds only the changed lines; an `mv` with unchanged content adds no lines.

| detect | kind | What this change is responsible for |
|---|---|---|
| `when_line_added` | line | An added line matches the pattern |
| `when_line_added` + `must_contain_in_file` | requires | The condition is on an **added line**, and the required element is **nowhere** in the file |
| `when_file_added: true` + `must_contain_in_file` | absent | The file is **new** and the required element is missing |
| `when_changed` + `require_changed` | paired | The change set has A but not B (a file with only deleted lines is also in the change set) |
| `file_regex` | file | The multi-line match span (excluding leading/trailing whitespace) **overlaps a changed line or has a line deleted inside it** (the whole file for a new file) |
| `when_code_added: true` (+ `semantic_review` and `applies_to.files` required) | unit | A **line with a word in it** was added to a file under the glob. The function holding it, or the file head gathering the lines outside functions, is the unit judged |

A required element (`must_contain_in_file`) **counts as absent if it is inside a comment**. `// TODO: replace with FormRequest` is not validation. Matches inside strings count by default (`'use client'` is itself a string). To change this, use `must_not_in`. Setting it replaces the default `[comment]`.

- `must_not_in: [comment, string]` — also excludes matches inside strings from the count
- `must_not_in: []` — counts the raw text as is (rules that require a license header written as a comment)
- A file whose structure could not be read is judged by raw-text match and reported as "구조 미확인" ("structure unverified"). Analysis runs only on files where the required element appears in the raw text
- A UTF-8 BOM at the start of the file is stripped on read. So first-line patterns like `^\s*'use client'` match in BOM files too

Rules with `semantic_review` find candidates with the same anchor and hand only the verdict to the reviewer. Conventions with no regex signal (no business logic in controllers, for example) use `when_code_added` to name only the file glob and leave the judgment to the reviewer: [semantic-review.md](semantic-review.md#always-on-review-by-file-glob)

`superseded_by: [pint.json, ...]` turns the rule off if that file exists in the repo. This avoids flagging with a regex what a formatter fixes deterministically.

Rules with `fix.auto` are auto-fixed on candidate lines only, in `mode: auto-fix` and `scan.py --fix`. The fix is not applied if the line changed after detection or if the fixed line still trips the rule. Files that do not read as UTF-8 are not fixed, and everything except the fixed lines stays byte-for-byte, down to line endings (including mixed LF/CRLF).

## Structure conditions: what the match sits in

The anchor decides "what this change is responsible for", and structure conditions **filter** those matches. A regex alone cannot tell a `dd(` inside a comment from a real `dd(`. Structure is judged with a tree-sitter syntax tree (a structure engine the plugin installs itself — [architecture.md](../../architecture.md#구조-엔진) (Korean)).

```yaml
detect:
  when_line_added: '\bdd\('
  not_in: [comment, string]     # exclude matches inside comments and string literals
```

| Condition | Values | Meaning | Usable anchors |
|---|---|---|---|
| `not_in` | `comment`, `string` | Exclude matches inside those spans | line / requires / file |
| `in_scope` | `loop`, `function`, `class`, `catch` | Accept only matches that sit inside the **body** of **all** listed scopes | line / requires / file |
| `block_empty` | `true` | Accept only when the body of the block enclosing the match is whitespace only | **file only** |

- A single value can be written without a list: `not_in: comment`
- The regex runs first. Only files with a match for a rule with structure conditions are parsed. If there are no matches, the engine is not even imported
- line and requires anchors look at **every** match on the line. If any one passes the condition, the line is a candidate. So `$label = "dd("; dd($user);` is caught by the later call even though the earlier string match is filtered out
- `string` is literal **text**: strings, template literals, regex literals, heredoc/nowdoc, JSX text and attribute values, HTML after PHP's `?>`, Blade template text. Code inside them — `${...}` in templates, `{...}` in f-strings, PHP's `"{$a->b()}"`·`$x`, heredoc interpolation, JSX `{...}` — is code
- `comment` is `//`, `/* */`, `#` (PHP, Python), Blade `{{-- --}}`. PHP's `#[` is an attribute, not a comment. PHP `//` comments end at `?>`
- `in_scope` treats only the block **body** as inside. In `for (const x of await load()) {`, `await load()` is outside the loop. So adding `in_scope: loop` to a rule whose trigger is the header line itself (a rule that looks for `foreach (`) catches nothing
- `loop` also includes callback bodies passed to iteration methods (`xs.map(x => ...)`, `$users->each(function ...)`, `array_map(fn ...)`, `map(lambda ...)`). Whether a method is an iteration method is decided by a name list (`structure/nodes.py`). A callback of an iteration method is both loop and function. Python comprehensions are loops too
- `function` includes the bodies of methods, closures, arrow functions (including ones without braces), PHP `fn`, and Python `lambda`
- `block_empty` is `file_regex`-only because with nested blocks "which block" becomes ambiguous. It treats the **whole judged block**, not the match, as the change window, so deleting the body of a legacy catch or turning it into blank lines is this change's responsibility. **Comments are content** — a `catch` block with a comment explaining why is not empty
- They cannot be attached to `when_file_added` (absent) or `when_changed` (paired), because there is no location to judge

Supported languages are JavaScript (JSX), TypeScript, TSX, PHP, Blade, and Python. In Blade, directive blocks (`@foreach…@endforeach` etc.) become scopes, and PHP inside them is read as PHP.

**What could not be read is not a pass.** In the following cases the condition is not applied, the candidate is kept, and a `systemMessage` reports which file it was.

- No structure engine — "구조 엔진 없음 (설치 전 / 설치 중 / 설치 실패 / 미지원 플랫폼 / 꺼짐)" ("no structure engine (not installed yet / installing / install failed / unsupported platform / off)"). In CI, install it first with `scripts/engine.py ensure`, and use `scan.py --require-engine` to keep runs from passing without verification
- The file has a spot the parser could not read — matches from the first read error onward are "구조 미확인" (an unclosed quote changes everything after it). Matches before it are judged normally
- Unsupported language (e.g. `not_in: [comment]` hitting a `.yaml`)

**Adding or changing** a condition expires that rule's semantic review cache. The criteria for picking candidates changed, so stored verdicts answer a different question.

### Fixtures and structure conditions

`tests.match`/`no_match` for rules with structure conditions must be **complete code the parser can read**. An unpaired fragment like `} catch (e) {` becomes a read error and is not judged — write `try { … } catch (e) { … }`, and put methods inside a class. PHP fragments get `<?php` prepended automatically (not if the fragment starts with `<?`). To test behavior outside the tag itself, turn it off.

```yaml
tests:
  lang_prefix: false
  match: ["<p>It's</p>"]
```

## Fixtures and scenario tests

| Test | What it verifies |
|---|---|
| `tests/rules/test_rule_fixtures.py` | `tests.match`/`no_match` of every rule, that auto-fix resolves the violation, preset membership, id↔file name |
| `tests/rules/test_rule_scenarios.py` | Anchor behavior with real git changes: new code is caught and **untouched legacy stays quiet** |
| `tests/integration/test_parity.py` | Pins (rule, file, line) results on 3 fixture repos |

Rules that are not `when_line_added` alone must have a legacy no-reaction scenario (enforced by tests).

Check repo-local rules with `python3 tests/rules/test_rule_fixtures.py --repo <repo>`. Overrides are checked merged into the original.

## Overrides

```yaml
# <repo>/.claude/convention-guard/rules/override-blade-query.yaml
override: core/laravel-no-query-in-blade
severity: warn
applies_to:
  exclude: ["resources/views/admin/**"]
```

It deep-merges into the original rule's raw YAML, then validates. Mappings are merged and **lists are replaced**. If you only want to turn a rule off, adjust severity, or exclude paths, the repo `config.yaml`'s `disable`/`severity`/`exclude` is simpler than an override.

## Presets

`presets/*.yaml` are bundles of core rules.

```yaml
name: laravel
description: "Laravel controller, migration, Blade, and config rules"
stacks: [laravel]        # turned on under presets: auto when this tag is detected. If empty, must be listed explicitly
rules:
  - core/laravel-*       # rule id glob
```

| Preset | auto condition | Contents |
|---|---|---|
| common | always | TODO without an owner |
| security | always | Hardcoded secrets, `$request->all()` without validation |
| php | php | Debug output, empty catch |
| psr12 | php | 12 PSR-12 style rules (9 step aside when a formatter is present) |
| laravel | laravel | Validation, migrations, Blade queries, env, route tests, N+1 |
| js | js, ts | console, empty catch, any |
| react | react | Index key |
| next | next, next-app | 'use client', img |
| nest | nest | Direct Req/Res use, repository injection in controllers |
| python | python | Debug output (print, breakpoint, pdb), bare except |
| architecture | explicit | Layer boundaries (semantic review), repository injection in controllers |
| performance | explicit | N+1 (semantic review) |
| layering | explicit | Business logic in controllers, I/O dependencies in the domain layer (always-on review by file glob) |

A rule can belong to several presets. Every core rule must belong to at least one preset (enforced by tests).

## Bundled rule list

```bash
python3 scripts/detect_stack.py --cwd <repo>
```

Shows the rules in effect (`✔ on`) and the rules not in effect (`○ off`) with the reason (preset inactive, stack mismatch, superseded, config disable).
