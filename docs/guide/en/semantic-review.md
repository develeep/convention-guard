# Semantic review

[README](../../../README.en.md) · [한국어](../ko/semantic-review.md) · **English**

## Contents
- Why it is needed
- Why not hand everything to the model
- Flow
- Minimum sufficient context
- Verdict cache and deduplication
- Relation to the verification cycle
- Writing rules
- Cost and limits

## Why it is needed

Some conventions can only be judged by looking at **meaning, not the shape of the code**: N+1 queries, layer boundaries, or cases where "if A then B is needed" depends on the function's flow. A regex can narrow such code down to candidates, but it cannot judge it.

```php
$orders = Order::query()->with('items')->get();   // VALID if this line is present
foreach ($orders as $order) {
    $order->items->count();                        // a regex cannot tell the two apart
}
```

## Why not hand everything to the model

| Problem | Details |
|---|---|
| Cost | Stop fires every turn. Judging unconditionally means an LLM call every turn |
| Latency | A verdict that uses tools takes tens of seconds |
| Nondeterminism | Different verdicts for the same code |
| Failure to converge | A new finding after every fix — the verification loop never ends |

So it judges **only candidates that passed the deterministic gate**, **only code with no recorded verdict**, **with one function's worth of context**.

## Flow

```
Stop
 └ find candidates with the detect of semantic_review rules     0 candidates → done (no AI call)
    └ per candidate: context pack + context_hash / related_hash
       └ look up verdict cache (rule:file:review_hash)
          ├ VALID / FALSE_POSITIVE → excluded
          ├ VIOLATION              → included in the block message like a deterministic finding
          └ none                   → save a review batch (reference <db path>#<id>)
             └ block message: "convention-guard:convention-reviewer 에이전트에게
                            python3 .../review.py show <배치> 를 전달하세요" ("pass python3 .../review.py show <batch> to the convention-guard:convention-reviewer agent")
                └ main agent calls the subagent
                   └ reviewer: show → judge → review.py record → reply one line per violation only
                      └ main agent: fix VIOLATIONs only → Stop → verify
```

Only one command line and the reviewer's short reply enter the main agent's context. The context pack and the code the reviewer read stay inside the subagent.

Setting: `semantic_review.enabled: true` (repo config or userConfig). A preset with semantic review rules (`architecture`, `performance`, or the N+1 rule in `laravel`) must be active.

## Minimum sufficient context

The rule picks the pieces it needs, and each piece has a line budget.

| Piece | Contents | Cap |
|---|---|---|
| `current_function` | The named function or method enclosing the candidate. If long, only the head, the area around the candidate, and the tail | 80 lines |
| `snippet` | Candidate ±5 lines (falls back to ±30 lines if no function is found) | |
| `imports` | Import statements at the top of the file (per-language patterns, read on until brackets close). Excludes ones inside comments and strings and inside blocks like classes (PHP trait `use`) | 30 lines |
| `changed_hunks` | Other lines this change added in the same file | 20 lines |
| `related_files` | The head of files found via symbols in the function (e.g. `Order::query`) | 60 lines per file, up to 2 |

- Per-rule cap `semantic_review.max_context_lines`, cap for the whole batch `semantic_review.context_budget_lines`
- Cap on candidates in one batch `semantic_review.max_candidates`. Overflow candidates are deferred to the next review
- The unit of judgment is the function. Candidates caught by the same rule in the same function become one question (one verdict), and the batch entry lists all their lines. The reviewer answers VIOLATION if any one of them is a violation
- Truncated spots get `… N줄 더 — 필요하면 Read` ("… N more lines — Read if needed"). The reviewer reads more only when the verdict really needs it, up to 3 more reads per candidate

Function boundaries are found by the structure engine (tree-sitter). Supported languages are js/ts/tsx, php, Blade, and Python. If there is no engine or the file does not parse, it sends ±30 lines around the candidate without a function region and writes `함수 경계 미확인` ("function boundary unverified"). Control statements like `for (...) {` are not treated as functions. Methods and lambdas are. However, a callback passed to an iteration method (`$orders->each(function ($o) {`, `xs.forEach(x => {`) is not a unit of judgment; the enclosing function is. That is because the evidence for the verdict, like a `with()` above the loop, is in the enclosing function.

## Verdict cache and deduplication

The cache key is `rule:file:review_hash`, and `review_hash` is a fingerprint that folds together **everything that verdict depended on**.

| Piece | Contents | When it changes |
|---|---|---|
| `definition_hash` | The rule's `detect` gate + `semantic_review` (instruction, context, max_context_lines) | The question itself changed, so re-judge |
| `context_hash` | Main region — the enclosing function body (or the window around the candidate if none) | The code under judgment changed, so re-judge |
| `related_hash` | Related files in the pack (the **whole file**, not the head shown) and the import section (sorted text without line numbers) | The evidence changed, so re-judge |

The rule's `title`, `severity`, and `message` do not change the verdict, so they are left out of the fingerprint — fixing a title does not throw away the cache. `changed_hunks` is left out too: it is not the subject of judgment but a value that follows the change scope.

- If the same function is unchanged and the rule is unchanged, it is not judged again — even across sessions (for `verdict_ttl_days`)
- If **any line** of the function changes, it is judged again. Adding `with()` above the loop to fix a VIOLATION also refreshes the verdict
- It is also judged again when **a related file changes**, such as a relationship added to a Model in the pack, because the reviewer read that content to judge. The same applies when a later part not shown in the pack (e.g. `$with` on line 75) changes. It is not re-judged when only import line numbers shift because a comment was added at the top of the file
- If you edit a rule's instruction or detect, that rule's existing verdicts are not reused
- Changes to other functions in the same file, or to files not in the pack, have no effect

The cache and review batches live in the state store (`convention-guard.db`, sqlite) in the plugin data directory and are not committed to the repo. When a verdict is recorded, that repo's entries past the TTL are deleted, and each record is one transaction, so reviewers recording at the same time do not overwrite each other's verdicts. The reviewer subagent does not inherit the plugin's environment variables, so the batch is passed as one reference string holding the store path (`<db path>#<id>`). A model's opinion is not a team decision. Dismiss exceptions the team agreed on with `dismiss.py`.

## Relation to the verification cycle

| Situation | Behavior |
|---|---|
| Reviewer says VIOLATION → agent fixes → function body changes | Recorded as fixed, and the changed function is requested for review once more |
| Reviewer says VALID | Excluded at the next Stop — passes |
| Review request not run (no record) | Requests once more with "실행되지 않았습니다" ("was not run"), after that only records and ends |
| `max_verify_attempts` exhausted | Records remaining pending candidates as `review_skipped` and ends |
| `mode: report` | Does not request review (it cannot block). Records `review_skipped` |

## Writing rules

```yaml
detect:
  when_line_added: '\bforeach\s*\(|->each\s*\('     # gate: the narrower, the cheaper
semantic_review:
  context:
    - current_function
    - related_files: {symbol: '\b([A-Z]\w+)::(?:query|with|where)\b', glob: 'app/Models/{1}.php', max: 2}
  max_context_lines: 150
  instruction: |
    VIOLATION: accesses a relationship that was not loaded, inside a loop.
    VALID: already loaded with with()/load(), or no relationship access.
    If you cannot decide, it is VALID.
```

- In the instruction, one sentence each for the VIOLATION/VALID conditions, plus "if you cannot decide, VALID"
- Do not include instructions like "skim the repo structure". Rules that cannot be judged from the pack stay as guidelines (AGENTS.md)
- Fixtures test only the gate

## Cost and limits

- Reviews happen only on turns with candidates, and only for code not in the cache. A wide gate raises cost, so narrow the gate of rules with low precision (the share the reviewer judged VIOLATION) in `log_report.py`. Many `VALID` verdicts mean the gate is wide; many `FALSE_POSITIVE` verdicts mean the gate catches the wrong code, so the fixes differ
- The main agent can ignore the review request. In that case it requests once more, and the log records `review_skipped`
- `scan.py --review` verdicts depend on the local verdict cache. CI has neither the cache nor a reviewer, so do not expect verdicts in CI. Instead, add `--review --fail-on-pending` so candidates still pending review give exit code 1 and "not judged" is not read as a pass ([cli.md](cli.md#ci))
