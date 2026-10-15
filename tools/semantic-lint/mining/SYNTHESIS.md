# Registry synthesis brief

You merge 223 candidate rules and 84 anti-rules from 16 mining workers into one rule
registry draft for a semantic PR linter. Read this file in full first, then the inputs.
Do not spawn subagents. Do not call any API. Write only to your output path.

## Inputs

Directory: `<workdir>/swarm/`

- `merged/INDEX.md`: a compact one-line index of every candidate rule and anti-rule. Read this
  in full first and plan merges and drops from it.
- `merged/all_rules.json`: every candidate rule in full (736k chars), with a `slice` field.
  Schema in `RULE_MINING.md`. Read a candidate's full record only when you keep or merge it;
  use a small script to pull records by id instead of reading the whole file.
- `merged/all_anti_rules.json`: every anti-rule (what senior reviewers dismissed from AI bots).
- `out/<slice>/REPORT.md`: each worker's observations, conflicts, and deterministic-tool notes.
- `RULE_MINING.md`: the schema the workers followed.
- Existing rules in the repo (read-only, do not edit):
  `.greptile/rules.md`, `cubic.yaml`, `backend/AGENTS.md`, `web/AGENTS.md`, `CONTRIBUTING.md` lines 353-506.

## The linter these rules feed

Jev (TypeSafe AI's decision model) answers one `noul` (yes/no probability) per rule per
diff window of at most 40 lines. State is the file path plus the window text. An LLM
writes the finding only above a per-rule threshold measured by an eval harness on
historical review comments. The LLM stage has the repo checkout and can grep. Jev reads
instructions literally, cannot count or do arithmetic, and handles negation badly.

## Priorities (from the user)

The registry's first-class families, in this order:

1. No wrapper functions (single-statement, pass-through, single-caller wrappers to inline).
2. Inline and simplify architecture (abstractions, layers, flags, branches, indirection
   added before anything needs them; near-copy functions to parametrize).
3. Files in the right place (db queries in db modules, models in models.py, ee code in
   ee/, prompts in prompt files, no code in `__init__.py`, no re-export shims).
4. Use pre-existing functions (hand-rolled parsers, duplicated helpers, derived settings).
   These need a repo search at the LLM stage; mark them `needs_repo_search: true` and say
   what to search for.

Every other family is secondary. Keep the strong ones. Cut the weak ones hard.

## Merge rules

- One judgment, one rule. Merge candidates that encode the same judgment across slices
  (for example wrapper rules from dead-code-b, questions-other, config-env, control-flow).
  Union their `source_threads`, `reviewers`, and examples. Keep the sharpest Jev question.
- Drop a rule when any of these holds, and record it in the drop log:
  a deterministic tool already enforces it (ruff rule, ty, eslint, pre-commit hook, or a
  ruff rule the reports say should be enabled); an existing greptile or cubic rule says
  the same with no sharper boundary; fewer than 3 source threads unless it states an
  explicit convention in the reviewer's words; `confidence: low`; it needs repo-wide
  context Jev cannot see and the LLM cannot resolve with a grep.
- A contested rule (reviewers disagree, or it conflicts with CONTRIBUTING or AGENTS.md)
  is kept only when the recent threads (2026) settle it. Otherwise move it to
  `decisions_needed` with both sides quoted.
- Anti-rules become constraints. For each kept rule, list the anti-rule ids whose
  dismissed finding type this rule could reproduce, and fold their boundary into the
  rule's `false` criteria and `llm_guidance` (for example "deliberate behaviour change",
  "guarded upstream", "stacked PR adds the caller later", "pre-existing or moved code").
  Also produce a global `never_flag` list of anti-rule patterns no rule may emit.
- Jev questions: one literal positive sentence about the window, no negation, no "and"
  joining two judgments. `true` and `false` carry `what`, `not_for`, and 1 to 4 examples
  of at most 8 lines, verbatim from the source rows. Prefer examples whose hunk shows the
  whole construct.
- Target 40 to 60 kept rules. Fewer, sharper rules beat coverage.

## Output

Write to `<workdir>/swarm/synthesis/`:

1. `registry_draft.json`: `{"rules": [...], "never_flag": [...], "decisions_needed": [...],
   "deterministic_followups": [...]}`. Each rule keeps the mining schema plus:
   `family` (one of `wrapper`, `simplify`, `placement`, `reuse`, `other`),
   `merged_from` (candidate ids), `anti_rule_constraints` (anti-rule ids),
   `needs_repo_search` (bool) and `repo_search_hint` (string or null),
   `threshold_hint` (0.3 to 0.8, your prior; eval will replace it).
   Order rules by family, priority families first, then by source count.
2. `MERGE_LOG.md`: one line per candidate rule: kept as X, merged into X, or dropped
   (reason). Every one of the 223 candidates appears exactly once.
3. `REPORT.md` (at most 40 lines): counts by family and severity, the ten strongest rules
   with source counts, every entry in `decisions_needed` in one line each, and
   `PASS`, `ISSUES`, or `BLOCKED`.

Verify before finishing: every `source_threads` id in a kept rule came from a candidate's
`source_threads`; every example is one a candidate carried; the `merged_from` ids cover
all 223 candidates between kept and dropped. Write prose without em dashes and without
colons as mid-sentence connectors.
