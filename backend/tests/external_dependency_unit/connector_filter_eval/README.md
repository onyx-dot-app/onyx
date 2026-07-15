# Connector-filter extraction eval (CI regression gate)

Scored regression eval for the source-scope filter extraction
(`decide_search_scope` in `onyx/secondary_llm_flows/source_filter.py`, driven by
`SOURCE_SCOPE_DECISION_PROMPT` in `onyx/prompts/filter_extration.py`).

`test_filter_extraction_regression.py` runs every eval question in
`scope_eval_cases.py` directly through `decide_search_scope` (real LLM, no agent
loop) and fails when the pass rate drops below a threshold (default 85%; each
case gets one retry to absorb LLM wobble, and a scope covering every connected
source grades the same as unscoped).

The dataset covers the behaviors the prompt is responsible for:

- **unscoped** — a topic, product name, or unconnected source must never be
  invented into a filter.
- **combined** — "search A and B" holds the full named set, every cycle.
- **backoff** — "check A first, then B" advances one source per cycle,
  re-searches on a topic shift, and broadens once exhausted.
- **multi-turn** — directives persist across same-topic follow-ups, are
  overridden by newer directives, and don't leak into new topics.

## When it runs

CI runs this via `.github/workflows/pr-connector-filter-eval.yml`, which
triggers ONLY when `onyx/prompts/filter_extration.py`,
`onyx/secondary_llm_flows/source_filter.py`, or this suite changes — a prompt
tweak gets scored against the full dataset before it merges, and no other PR
pays for the LLM calls. Everywhere else the suite is skipped unless
`RUN_CONNECTOR_FILTER_EVAL=1` is set.

## Run locally

```bash
RUN_CONNECTOR_FILTER_EVAL=1 \
    EVAL_LLM_PROVIDER="<provider display name>" EVAL_LLM_MODEL="claude-haiku-4-5" \
    python -m dotenv -f .vscode/.env run -- \
    pytest -sv backend/tests/external_dependency_unit/connector_filter_eval
```

Requires Postgres/Redis up. `EVAL_LLM_PROVIDER` is the provider's *configured
name* in Onyx (e.g. `"DevEnvPresetOpenAI"`), not the slug `"openai"`; when the
env vars are unset the tenant default provider is used. In CI (fresh database,
no provider configured) the conftest auto-provisions an OpenAI provider from
`OPENAI_API_KEY` using `gpt-5-mini`. Use the cheap tiers for real calls: OpenAI
`gpt-5-mini` or Anthropic `claude-haiku-4-5`.

The test prints a per-case report (expected vs got, per-category breakdown) —
run with `-s` to see it on success too.

## Extending / tuning

- Add cases to `scope_eval_cases.py` (name, category, user turns, connected
  sources, cycle state, expected scope). Expectations are graded on the
  resolved scope set only, never answer phrasing.
- Knobs: `CONNECTOR_FILTER_EVAL_THRESHOLD` (pass rate in [0,1], default 0.85)
  and `CONNECTOR_FILTER_EVAL_ATTEMPTS` (attempts per case, default 2).
- The threshold is deliberately below 100%: a couple of known-hard backoff
  cases (advance-vs-re-search judgment) fail with cheap models. A real prompt
  regression flips a whole category and sinks the score well below the bar.
- The `false-positive` trap cases (a connected source named as the TOPIC of
  the question, not as where to look) currently FAIL — the suite is red until
  the WHERE-vs-TOPIC prompt tuning lands and lifts the score back over the
  threshold.
