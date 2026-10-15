# Review-comment mining

These scripts and briefs turned the human review comments on this repo into the rule
registry draft for the semantic linter. Run them in order to repeat the derivation.
Every step writes inside the work directory. Only step 11 writes outside it.

## Before you start

- Log in with `gh` (read access to the repo). Install `jq` and `uv`.
- Put a TypeSafe key in `TYPESAFE_API_KEY` for the Jev steps. Never commit it.
- The work directory holds `corpus/` and `swarm/`. The default is
  `tools/semantic-lint/.cache/mining`, which git ignores. Give every script
  `--workdir DIR` to use another path. Do not commit anything from it.
- `common.py` holds the repo slug, the reviewer list, and the bot name pattern.
  Change them there only. The shell scripts read the slug from it.
- A script that imports `typesafe-sdk` says so in its docstring. Run it as
  `uv run --with typesafe-sdk python3 <script>`. The repo does not depend on the SDK.

## The recipe

Run the commands from the repo root. Each path starts with `tools/semantic-lint/mining/`.

1. `fetch_comments_parallel.sh [--workdir DIR]`
   - Writes `corpus/pull_comments.jsonl` (50,672 rows), `corpus/issue_comments.jsonl`
     (30,000 rows) and `corpus/pages/`.
   - Time: 2 minutes with 12 parallel pages (`PAR=12`).
   - `fetch_page.sh` fetches one page and retries 5 times. Each run fetches every page
     again.
2. `fetch_pr_meta.py`
   - Writes `corpus/pr_meta.jsonl` and `corpus/thread_state.jsonl`: PR state and the
     resolved and outdated flags of each review thread, from GraphQL.
   - Skips PRs already in `pr_meta.jsonl`.
3. `build_threads.py`
   - Writes `corpus/threads.jsonl`: one row per inline thread that a target reviewer
     started (2,265 threads on 649 PRs). Also writes `pr_comments.jsonl` and
     `stats.json`.
4. `screen_threads.py` (typesafe-sdk)
   - Writes `corpus/threads_screened.jsonl`: each thread plus a `jev` field with
     category, actionable, generalizable and severity.
   - Cost: 29 s and $0.16 for 2,265 threads. Skips rows it already screened.
     `REORDER=1` adds the order-bias check.
5. `make_slices.py`
   - Writes `swarm/slices/<slice>.jsonl` and `.md` for 14 category slices, `INDEX.json`,
     and `bot-pushback.jsonl` (reviewer replies to AI bot comments, 1,973 rows).
6. `screen_pushback.py` (typesafe-sdk)
   - Keeps the replies that dismiss or correct a bot. Writes the slices
     `bot-pushback-a` and `bot-pushback-b`.
   - Cost: 25 s and $0.10.
7. `fetch_review_time_diffs.py`
   - Writes `corpus/review_diffs/<pr>_<sha>.json`: the PR diff at the commit of each
     review comment. The prototypes read these files.
   - Time: 1 minute for 891 compare diffs. Skips files that exist.
8. Swarm mining. This step has no script. One agent per slice (16 slices) follows
   `RULE_MINING.md` and writes `swarm/out/<slice>/rules.json` (`anti_rules.json` for the
   bot-pushback slices), `rejected.md` and `REPORT.md`.
9. `validate_rules.py`
   - Checks every worker output against the contract. Writes
     `swarm/merged/all_rules.json` and `all_anti_rules.json`. It reports problems and
     drops nothing.
10. Synthesis. This step has no script. One agent follows `SYNTHESIS.md` and writes
    `swarm/synthesis/registry_draft.json`, `MERGE_LOG.md` and `REPORT.md`.
    - The run had 253 candidate rules and 84 anti-rules. It kept 57 rules. The brief
      still says 223 candidates, the count before five slices were revised.
    - The brief also reads `swarm/merged/INDEX.md`, a one-line view of
      `all_rules.json`. No script here writes it.
11. `write_rules.py`
    - Writes the rule files in `tools/semantic-lint/rules/` from the draft. Its
      docstring shows the usage.

## Prototypes

`proto_eval_rt.py` and `proto_window.py` (both typesafe-sdk) measure how well Jev
separates hunks that reviewers commented on from hunks they left alone. They read the
review-time diffs from step 7.

- `proto_eval_rt.py` samples 400 positive and 400 negative hunks. It prints AUC and
  recall by threshold, and writes `proto_eval_rt_results.jsonl` in the work directory.
- `proto_window.py` cuts each of 300 positive and 300 negative hunks to windows of 12,
  24 and 40 lines and to the whole hunk. It prints AUC for each size.

## Numbers the design cites

- Comment anchors: 91.8% sit on the last line and 24% sit on a block opener. No script
  in this directory reproduces these two counts.
- AUC is flat across window sizes (`proto_window.py`).
- The scripts print cost at $0.042 per million Jev input tokens.
