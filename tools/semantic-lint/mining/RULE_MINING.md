# Rule mining brief (read in full before any work)

You are one worker in a swarm. Each worker owns one slice of the review-comment corpus
and turns it into candidate lint rules. The parent merges all slices. Your slice is
named in your spawn message. Do not read other slices. Do not edit any file outside your
output path. Do not spawn subagents. Do not call any LLM or Jev API.

## What a rule is

A rule is one recurring review judgment that a reviewer (`wenxi-onyx`, `evan-onyx`,
`Danelegend`) applied to a diff hunk, stated so that a yes/no question about a new hunk
can detect it. The linter asks Jev (a decision model, no text generation) one `noul`
question per rule per hunk, then an LLM writes the finding. So a rule must be:

- Detectable from the hunk plus the file path, without repo-wide reasoning.
- General. It would fire on other PRs, not only on the one it came from.
- Specific enough that a yes/no question has a clear boundary. Split a fuzzy concern
  into two rules rather than one vague one.
- Not already enforced by a deterministic tool (ruff, ty, eslint, prettier, pre-commit
  hooks) and not a duplicate of an existing AI reviewer rule. Existing rules live in the
  repo at `.greptile/rules.md`, `cubic.yaml`, `backend/AGENTS.md`, `web/AGENTS.md`,
  and `CONTRIBUTING.md` section "Engineering Best Practices". Read them first. When a
  comment matches an existing rule, record it under `overlaps_existing` instead of
  creating a new rule, unless the comments show a sharper boundary than the existing text.

## Input

Your slice file is JSONL. Each row is one reviewer thread:

```
{id, pr, pr_title, pr_author, pr_merged, pr_size, reviewer, path, line, diff_hunk, body,
 created_at, html_url, resolved, outdated, replies: [{author, body, created_at}],
 jev: {category, category_conf, actionable, generalizable, severity, ...}}
```

`jev.*` fields are a cheap pre-screen, not ground truth. Read the comment and the hunk
yourself. `resolved` true or an author reply like "done" means the change was accepted.
A reply that pushes back and no change means the rule may be contested; note that.

## Method

1. Read every row in your slice. Group rows that express the same judgment.
2. For each group of 2 or more rows, write one candidate rule. A single strong row that
   states an explicit convention ("we never do X here") may also become a rule; mark
   `single_source: true`.
3. For each rule, pick 2 to 4 positive examples (rows where the rule fired) and, when the
   slice has them, 1 to 2 near-miss examples (code that looks similar but the reviewer did
   not object to, or a reply that clarified the boundary). Quote the smallest hunk excerpt
   that shows the pattern, at most 12 lines.
4. Draft the Jev question. Instructions are one sentence in plain present tense about the
   hunk, with no negation and no double judgment. Criteria describe `true` and `false`
   with `what` and `examples`. Jev reads literally, leans toward the first choice option,
   and cannot count or do arithmetic.
5. Draft the LLM guidance. Two or three sentences telling a reviewer-voice LLM what to say
   and what fix to suggest, in the reviewer's terms.
6. Record what you rejected and why in `rejected.md` (one line each): comments that were
   one-offs, questions, praise, duplicates of existing rules, or not detectable from a hunk.

## Output

Write `rules.json` to your output path. Schema (every field required unless marked):

```json
{
  "slice": "<slice name>",
  "rows_read": 0,
  "rules": [
    {
      "id": "<kebab-case, prefixed by area, e.g. backend-error-handling-no-bare-except>",
      "title": "<one line>",
      "statement": "<the rule as an instruction to the author, one or two sentences>",
      "rationale": "<why the reviewers care, in their words where possible>",
      "scope_globs": ["backend/**/*.py"],
      "severity": "nit | should_fix | must_fix",
      "reviewers": {"evan-onyx": 3, "wenxi-onyx": 1, "Danelegend": 0},
      "source_threads": [123456, 234567],
      "single_source": false,
      "contested": false,
      "overlaps_existing": ["greptile: OnyxError over HTTPException"],
      "positive_examples": [
        {"thread_id": 123456, "hunk_excerpt": "...", "comment_excerpt": "...", "accepted": true}
      ],
      "negative_examples": [
        {"thread_id": 234568, "hunk_excerpt": "...", "why_not": "..."}
      ],
      "jev_question": {
        "instructions": "The added lines ...",
        "criteria": {
          "true": {"what": "...", "examples": ["..."]},
          "false": {"what": "...", "examples": ["..."]}
        }
      },
      "llm_guidance": "...",
      "confidence": "high | medium | low"
    }
  ]
}
```

Also write `rejected.md` and `REPORT.md`. `REPORT.md` is at most 25 lines: rows read,
rules produced, the three strongest rules with their source counts, slice-specific
observations (what this reviewer group cares about that surprised you), and `PASS`,
`ISSUES`, or `BLOCKED` with the reason.

## Quality bar

- Every `source_threads` id must exist in your slice. Every excerpt must be a verbatim
  substring of that row's `diff_hunk` or `body`.
- Prefer 8 precise rules over 25 vague ones. A rule whose Jev question you cannot phrase
  without "and" or "or" is two rules or no rule.
- Keep prose plain. No em dashes. No colons as mid-sentence connectors.
