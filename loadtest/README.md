# Onyx Chat Load Tests (Locust)

Load tests for the critical chat path: streaming chat turns with tool calls
and (later phases) deep research, measured by per-milestone latency.

**Guiding principle:** these tests measure Onyx's application code and
infrastructure under load — never LLM answer quality. The LLM is a
controllable dependency: a real cheap model is used only for the initial
harness shakeout; real load runs use a zero-cost deterministic mock LLM
provider (Phase 1) so call volume is unlimited and every regression is
attributable to Onyx code/infra.

This is a **standalone uv project** — intentionally not a member of the root
uv workspace, so Locust's gevent pins never constrain the backend lockfile.
Code here must never import `onyx.*` (gevent monkey-patching breaks backend
deps); the stream parser is vendored.

## Setup

```bash
cd loadtest
uv sync
```

## Running

```bash
ONYX_API_KEY=<key> uv run locust --headless -u 5 -r 1 -t 5m -H https://st-dev.onyx.app
```

Or with the web UI (live charts at http://localhost:8089):

```bash
ONYX_API_KEY=<key> uv run locust -H https://st-dev.onyx.app
```

The API key is created by an admin via `POST /api/admin/api-key`
(`{"name": "loadtest", "role": "basic"}`) or Admin Panel → API Keys.

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `ONYX_API_KEY` | required | Bearer token for all requests |
| `ONYX_LLM_PROVIDER` + `ONYX_LLM_MODEL` | unset | Per-request `llm_override` (e.g. provider name + `gpt-5-mini`); unset = persona default |
| `ONYX_WAIT_SECONDS` | 15 | Think time between turns per user |
| `ONYX_STREAM_READ_TIMEOUT` | 180 | Max seconds between stream chunks before failing the turn |
| `ONYX_DEEP_RESEARCH` | unset | `true` = send `deep_research: true` on every turn |

## Metrics

Each chat turn fires named pseudo-requests the moment the milestone packet
arrives on the stream; Locust aggregates percentiles per name:

- `chat:first_packet` — first stream line (server accepted + began work)
- `chat:first_search_doc` — first search-tool document batch
- `chat:first_answer_token` — first answer content (TTFT)
- `chat:total_turn` — full turn wall time; success/failure is recorded here
- `chat:send (headers)` — the raw HTTP request; its time is headers-only
  (stream=True), so read milestones above for real latency

A turn fails if: non-200 response, an error packet appears, the stream stalls
past the read timeout, or the stream ends without answer content.

## Roadmap

- Phase 0 (this): basic chat vs st-dev, real cheap LLM via `llm_override`
- Phase 1: `mock_llm/` — OpenAI-compatible deterministic mock server
- Phase 2: in-cluster Locust master/workers + mock provider on st-dev (`k8s/`)
- Phase 3: weighted scenario suite (chat+search, multi-turn, deep research)
- Phase 4: Prometheus export + Grafana correlation dashboard
