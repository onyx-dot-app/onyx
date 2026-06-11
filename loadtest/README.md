# Onyx Chat Load Tests (Locust)

Load tests for the critical chat path: streaming chat turns, search-tool
turns, and deep research, measured by per-milestone latency.

**Guiding principle:** these tests measure Onyx's application code and
infrastructure under load — never LLM answer quality. The LLM is a
controllable dependency: the bundled mock LLM server provides unlimited,
zero-cost, deterministic call volume so every regression is attributable to
Onyx code.

This is a **standalone uv project** — intentionally not a member of the root
uv workspace, so Locust's gevent pins never constrain the backend lockfile.
Code here must never import `onyx.*` (gevent monkey-patching breaks backend
deps); the stream parser is vendored.

## Setup

```bash
cd loadtest
uv sync
```

### Mock LLM server

```bash
uv run uvicorn mock_llm.app:app --port 8001
```

Register it in Onyx (Admin Panel → LLM, or `PUT /api/admin/llm/provider`) as
provider type **`openai_compatible`** — NOT `openai`, which litellm routes
through the OpenAI Responses API bridge that the mock doesn't implement —
with `api_base` pointing at the server (e.g. `http://localhost:8001`), any
api_key, and model configurations for the model names you'll use (e.g.
`mock-model`, `mock-tools1`, `mock-agents2`).

Behavior knobs ride in the model name (litellm passes it through verbatim):

| Knob | Example | Meaning |
|---|---|---|
| `ttft<ms>` | `mock-ttft500` | time to first token |
| `itl<ms>` | `mock-itl20` | inter-token delay |
| `len<n>` | `mock-len400` | answer length in tokens |
| `tools<0/1>` | `mock-tools1` | call the search tool on the first AUTO cycle |
| `agents<n>` | `mock-agents2` | parallel research agents per DR orchestrator cycle |

The mock understands Onyx's LLM-loop contract: `tool_choice` none/auto/
required/forced, the deep-research phase sequence (clarification →
plan → orchestrator → research agents → reports), and `max_tokens` caps.
Contract tests: `uv run pytest tests/ -q`.

### Provider profiles

Knob combinations imitate real provider latency profiles — register each as
a model configuration and select per scenario to test how Onyx behaves when
the provider is fast, slow, or degraded (slow providers hold streams and
their resources open longer, which is exactly what stresses the api-server):

| Profile | Model name |
|---|---|
| Fast chat model (gpt-class) | `mock-ttft300-itl15-len150` |
| Slow reasoning model (long silent TTFT) | `mock-ttft8000-itl40-len600` |
| Degraded/overloaded provider | `mock-ttft20000-itl200-len300` |
| Long-answer generation | `mock-ttft500-itl20-len2000` |

## Running

```bash
ONYX_API_KEY=<key> uv run locust --headless -u 5 -r 1 -t 5m -H https://st-dev.onyx.app
```

Scenario selection (all run by default; pick classes explicitly):

```bash
... uv run locust --headless -u 10 -r 2 -t 10m BasicChatUser ChatWithSearchUser
... uv run locust --headless -u 5 -r 1 -t 20m DeepResearchUser
```

- **BasicChatUser** (`chat:*` metrics) — single-turn chat, plain answer.
- **ChatWithSearchUser** (`search:*`) — mock emits an `internal_search` tool
  call, so query expansion, the embedding model server, and Vespa/OpenSearch
  genuinely execute. Requires indexed documents in the target deployment.
- **DeepResearchUser** (`dr:*`) — full deep-research turn (plan, parallel
  research agents, intermediate + final reports). Heaviest scenario; one
  turn = ~8+ LLM calls + real search executions on one held stream.

The API key is created by an admin via `POST /api/admin/api-key`
(`{"name": "loadtest", "role": "basic"}`) or Admin Panel → API Keys.

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `ONYX_API_KEY` | required | Bearer token for all requests |
| `ONYX_LLM_PROVIDER` | unset | Provider name for `llm_override` (needed when the mock isn't the deployment default) |
| `ONYX_LLM_MODEL` | unset | Model for BasicChatUser (unset = persona default) |
| `ONYX_SEARCH_MODEL` | `mock-tools1` | Model for ChatWithSearchUser |
| `ONYX_DR_MODEL` | `mock-agents2` | Model for DeepResearchUser |
| `ONYX_WAIT_SECONDS` | 15 | Think time between turns per user |
| `ONYX_DR_WAIT_SECONDS` | 30 | Think time for DR users |
| `ONYX_STREAM_READ_TIMEOUT` | 180 | Max seconds between stream chunks |
| `ONYX_DR_STREAM_READ_TIMEOUT` | 300 | Same, for DR turns |
| `MOCK_TTFT_MS` / `MOCK_ITL_MS` / `MOCK_LEN_TOKENS` | 300 / 15 / 150 | Mock server defaults (model-name knobs override) |

## Metrics

Each turn fires named pseudo-requests (`<scenario>:<milestone>`) the moment
the milestone packet arrives; Locust aggregates percentiles per name:

- `*:first_packet` — first stream line (server accepted + began work)
- `*:first_search_doc` — first search-tool document batch (retrieval latency)
- `*:first_answer_token` — first answer content (TTFT)
- `*:first_dr_plan` / `*:first_research_agent` — deep-research phase starts
- `*:total_turn` — full turn wall time; success/failure recorded here
- `*:send (headers)` — raw HTTP request (headers-only timing)

A turn fails on: non-200, an error packet, a stream stalling past the read
timeout, or a stream ending without answer content / without the `stop`
packet (truncation).

## Docker

```bash
cd loadtest && docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
docker run -p 8001:8000 onyx-mock-llm
```

## Roadmap

- ✅ Phase 0: harness + milestones + mock LLM core
- ✅ Phase 1: tool-call & deep-research scripting, scenarios, Dockerfile
- Phase 2: in-cluster Locust master/workers + mock provider on st-dev (`k8s/`)
- Phase 3: weighted scenario mixes, multi-turn sessions, open-workload arrivals
- Phase 4: Prometheus export + Grafana correlation dashboard
