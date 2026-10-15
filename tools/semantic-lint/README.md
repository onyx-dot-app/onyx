# semantic-lint

semantic-lint reviews a pull request against rules mined from the review threads
of `evan-onyx`, `wenxi-onyx` and `Danelegend`. Jev screens every changed window
against every rule whose scope covers it. An LLM writes a finding only for the
strongest hits. The result is one advisory check run with annotations and one
summary comment. It never fails a PR.

The tool is standard-library Python 3.13, run with bare `python3`.

## Commands

```
python3 tools/semantic-lint/lint.py pr NUMBER [--compare-json FILE] [--publish-dir DIR]
python3 tools/semantic-lint/lint.py eval [--rule ID ...] [--write] [--seed DIR ...]
python3 tools/semantic-lint/lint.py check
python3 -m unittest discover -s tools/semantic-lint/tests -t tools/semantic-lint
```

- `pr` needs `TYPESAFE_API_KEY`, `OPENAI_API_KEY` and an authenticated `gh`. It
  prints the summary. With `--publish-dir` it also writes `check-run.json` and
  `summary.md`, which the workflow posts. The tool itself posts nothing. The
  LLM's `git_grep` tool searches the local checkout, so run it on the PR's
  merge ref to search what CI searches.
- `eval` needs `TYPESAFE_API_KEY`, and `gh` for data the cache lacks. It caches
  review comments, review-time diffs and Jev answers in
  `tools/semantic-lint/.cache/`. `--seed DIR` reads a mined corpus with the same
  layout (`pull_comments.jsonl`, `review_diffs/<pr>_<commit>.json`).
- `check` validates every rule file. The `semantic-lint-check` pre-commit hook
  runs it.

## Rules

`rules/registry.toml` holds the shared settings. Every other file in `rules/`
is one rule, and its file stem is the rule id. A rule is in one of three modes.

| Mode | Meaning | In CI |
| --- | --- | --- |
| live | sealed calibration that meets its precision floor | screened, hits go to the LLM |
| shadow | sealed calibration below the floor | screened, hits are counted only |
| inactive | no calibration, or a broken seal | not screened |

The floor is `min_precision` for the rule's severity in `registry.toml`, or the
rule's own `min_precision`. Reuse rules set 0.4, because a reuse finding posts
only when `git grep` confirms the existing code the LLM cites.

To add or tune a rule, edit its file, then run `eval --rule <id> --write`. Eval
writes the trailing `[calibration]` table. Its seal covers the question, the
examples, the scope, the window size and the Jev model, so any edit to them
makes the rule inactive until eval runs again, and `check` fails until then.
`mining/write_rules.py` generated the first rule files from the mined draft.
