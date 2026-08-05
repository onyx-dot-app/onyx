# Onyx Chat Load Tests (Locust)

Load tests for the critical chat path: streaming chat turns, search-tool
turns, and deep research, measured by per-milestone latency.

**Guiding principle:** these tests measure Onyx's application code and
infrastructure under load — never LLM answer quality. The LLM is a
controllable dependency: the bundled mock LLM server provides unlimited,
zero-cost, deterministic call volume so every regression is attributable to
Onyx code.

Locust's dependencies live in the root project's optional **`loadtest`
dependency group** (not synced by default), so its gevent/flask tree only
enters the environment when you opt in. Code here must never import `onyx.*`
(gevent monkey-patching breaks backend deps); the stream parser is vendored.

## Setup

From the repo root, sync with the `loadtest` group, then work from this
directory. The `uv run` commands below all pass `--group loadtest` so the
group stays installed (a bare `uv run` re-syncs to the default groups and
would drop Locust).

```bash
uv sync --group loadtest
cd loadtest
```

### Mock LLM server

```bash
uv run --group loadtest uvicorn mock_llm.app:app --port 8001
```

Register it in Onyx (Admin Panel → LLM, or `PUT /api/admin/llm/provider`) as
provider type **`openai_compatible`** — NOT `openai`, which litellm routes
through the OpenAI Responses API bridge that the mock doesn't implement —
with `api_base` pointing at the server (e.g. `http://localhost:8001`), any
api_key, and model configurations for the model names you'll use (e.g.
`mock-model`, `mock-tools1`, `mock-agents2`). Set **max input tokens ≥
50,000** on each model configuration — deep research refuses models below
that, and unregistered models default far lower.

Behavior knobs ride in the model name (litellm passes it through verbatim):

| Knob | Example | Meaning |
|---|---|---|
| `ttft<ms>` | `mock-ttft500` | time to first token |
| `itl<ms>` | `mock-itl20` | inter-token delay |
| `len<n>` | `mock-len400` | answer length in tokens |
| `tools<n>` | `mock-tools1` | call up to `n` retrieval tools (in parallel for `n>1`) on the first AUTO cycle |
| `agents<n>` | `mock-agents2` | parallel research agents per DR orchestrator cycle |

The mock understands Onyx's LLM-loop contract: `tool_choice` none/auto/
required/forced, the deep-research phase sequence (clarification →
plan → orchestrator → research agents → reports), and `max_tokens` caps.
Contract tests: `uv run --group loadtest pytest tests/ -q`.

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
ONYX_API_KEY=<key> uv run --group loadtest locust --headless -u 5 -r 1 -t 5m -H https://<your-onyx-url>
```

### Scenario mix

With no user classes named, the **default weighted steady-state mix** runs,
approximating production traffic shape:

| Scenario | Metrics | Weight | What it exercises |
|---|---|---|---|
| **BasicChatUser** | `chat:*` | 70 | single-turn chat, plain answer |
| **ChatWithSearchUser** | `search:*` | 20 | one `internal_search` tool call → query expansion, embedding model server, Vespa/OpenSearch retrieval (needs indexed docs) |
| **MultiToolUser** | `multitool:*` | 8 | up to 3 retrieval tools in parallel in one turn (`mock-tools3`) |
| **DeepResearchUser** | `dr:*` | 2 | full DR turn — plan, parallel agents, reports; ~8+ LLM calls on one held stream |

```bash
# default weighted mix:
... uv run --group loadtest locust --headless -u 50 -r 5 -t 15m -H https://<your-onyx-url>
# or pin to specific classes:
... uv run --group loadtest locust --headless -u 10 -r 2 -t 10m -H https://<your-onyx-url> BasicChatUser ChatWithSearchUser
```

### Targeted reproducers

Run on their own (not part of the default mix) to stress a specific failure
mode. Each maps to a real production incident class:

- **LongConversationUser** (`longconv:*`) — keeps one chat session alive for
  `ONYX_SESSION_TURNS` turns (default 20), chaining `parent_message_id` so the
  history grows every turn. Drives full-history load + token counting +
  summarization/compression each turn (history-driven slowdowns).
- **DisconnectUser** (`disconnect:*`) — drops the connection mid-stream the
  moment `ONYX_DISCONNECT_AFTER` (default `first_answer_token`) arrives, then
  abandons the session. Stresses server-side disconnect cleanup of held
  transactions/connections/buffers (slow leaks). The turn is recorded as
  `disconnect:disconnected`, separate from success/failure.
- **CompressionUser** (`compress:*`) — long session (default 60 turns) of
  large messages (`ONYX_MSG_CHARS`, default 8000) so the history crosses the
  model's input-token limit and Onyx summarizes/recompresses it every turn —
  the history-driven slowdown / compression death-spiral path. **Point it at a
  mock model registered with a small `max_input_tokens` (e.g. 16k) via
  `ONYX_LONGCONV_MODEL`**, otherwise the default 200k window needs an
  impractically long history before compression triggers.

```bash
ONYX_LONGCONV_MODEL=mock-smallctx \
... uv run --group loadtest locust --headless -u 25 -r 5 -t 20m -H https://<your-onyx-url> CompressionUser
```
- **FileAttachmentUser** (`fileattach:*`) — uploads one file (`ONYX_FILE_KB`,
  default 512) up front, then attaches it to every message. Exercises the
  chat-setup path that loads attached files from object storage while the DB
  connection is held — the connection-hold contributor that plain-text
  scenarios never touch. Set `ONYX_SESSION_TURNS > 1` to accumulate files
  across a growing history (a file-heavy long chat).

```bash
... uv run --group loadtest locust --headless -u 50 -r 5 -t 15m -H https://<your-onyx-url> LongConversationUser
... uv run --group loadtest locust --headless -u 50 -r 5 -t 15m -H https://<your-onyx-url> DisconnectUser
```

### Collapse-point ramp (`ONYX_SHAPE=stepramp`)

Walk the user count up through plateaus to find the knee where the system
stops keeping up, instead of guessing a fixed count. Pair with the
slow-provider profile (`ONYX_LLM_MODEL=mock-ttft8000-itl40-len600`) to hold
streams open and surface connection/memory exhaustion sooner. The shape
overrides `-u/-r` and is only active when `ONYX_SHAPE=stepramp` is set.

```bash
ONYX_SHAPE=stepramp ONYX_RAMP_STAGES=25,50,100,200 ONYX_RAMP_DWELL=300 \
ONYX_LLM_MODEL=mock-ttft8000-itl40-len600 \
ONYX_API_KEY=<key> uv run --group loadtest locust --headless -t 25m -H https://<your-onyx-url>
```

The API key is created by an admin via `POST /api/admin/api-key`
(`{"name": "loadtest", "role": "basic"}`) or Admin Panel → API Keys.

### Worker concurrency sweep (`ThreadHogUser` + `HealthProbeUser`)

Validates the api-server worker config (`api.workers` / `api.threadpoolSize` /
CPU in the Helm chart) against the production failure mode: long-running agent
requests pin the anyio threadpool, the event loop starves, and the liveness
`httpGet /health` probe (`timeoutSeconds: 10`, `failureThreshold: 3`) starts
failing → the pod is SIGKILLed.

- **ThreadHogUser** (`hog:*`) — each turn streams a deliberately slow mock
  response (default `mock-ttft1000-itl200-len600` ≈ 121s), holding one
  threadpool thread for the whole turn. Concurrency (`-u`) maps directly to
  pool pressure.
- **HealthProbeUser** (`HEALTH:probe`) — pins `ONYX_HEALTH_PROBES` (default 1)
  users that GET `/health` once per `ONYX_HEALTH_INTERVAL` (default 1s),
  **independent of `-u`**, and fail any probe slower than `ONYX_HEALTH_SLA_MS`
  (default 10000, the liveness `timeoutSeconds`). The `HEALTH:probe` failure
  rate is the experiment's primary signal — when it goes non-zero, this config
  would start getting liveness-killed at that concurrency.

```bash
# One run: hold ~49 long requests, probe /health throughout.
ONYX_API_KEY=<key> ONYX_HEALTH_PATH=/health \
  uv run --group loadtest locust --headless -u 50 -r 5 -t 15m \
  -H https://<your-onyx-url> ThreadHogUser HealthProbeUser
```

Sweep `concurrent-long-requests ∈ {10,20,40,80}` (use `ONYX_SHAPE=stepramp`)
against chart configs `api.workers ∈ {1,2,4}` × `api.threadpoolSize ∈ {40,80}`
× CPU `∈ {2,4}`. The right config is the smallest one where `HEALTH:probe`
stays at **0 failures** through your target concurrency.

> **st-dev routing caveats:** the `/loadtest` subpath is shadowed by the
> catch-all route — point `LOCUST_HOST` at a dedicated host or port-forward.
> When `LOCUST_HOST` is the web/nginx host, set `ONYX_HEALTH_PATH=/api/health`;
> when it targets the api Service directly, `/health` is correct. st-dev is
> direct-RDS, so absolute numbers differ from customer infra — compare configs
> **relative** to each other, not against an absolute SLA.

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `ONYX_API_KEY` | required | Bearer token for all requests |
| `ONYX_LLM_PROVIDER` | unset | Provider name for `llm_override` (needed when the mock isn't the deployment default) |
| `ONYX_LLM_MODEL` | unset | Model for BasicChatUser (unset = persona default) |
| `ONYX_SEARCH_MODEL` | `mock-tools1` | Model for ChatWithSearchUser |
| `ONYX_MULTITOOL_MODEL` | `mock-tools3` | Model for MultiToolUser |
| `ONYX_DR_MODEL` | `mock-agents2` | Model for DeepResearchUser |
| `ONYX_HOG_MODEL` | `mock-ttft1000-itl200-len600` | Slow model for ThreadHogUser (sets per-turn thread-hold time) |
| `ONYX_HOG_WAIT_SECONDS` / `ONYX_HOG_STREAM_READ_TIMEOUT` | 1 / 600 | ThreadHogUser think time / max inter-chunk wait |
| `ONYX_HEALTH_PATH` | `/health` | Health-probe path (`/api/health` via web/nginx host) |
| `ONYX_HEALTH_PROBES` | 1 | Number of HealthProbeUser instances to pin (independent of `-u`) |
| `ONYX_HEALTH_INTERVAL` | 1.0 | Seconds between health probes |
| `ONYX_HEALTH_SLA_MS` | 10000 | Fail a probe slower than this (liveness `timeoutSeconds`) |
| `ONYX_LONGCONV_MODEL` | unset | Model for LongConversationUser (unset = persona default) |
| `ONYX_SESSION_TURNS` | 1 | Turns to keep one session alive (LongConversationUser 20, CompressionUser 60) |
| `ONYX_MSG_CHARS` | 0 | Per-message size in chars (CompressionUser defaults to 8000; 0 = short questions) |
| `ONYX_DISCONNECT_AFTER` | `first_answer_token` | Milestone after which DisconnectUser drops the stream |
| `ONYX_FILE_KB` | 512 | Uploaded file size (KB) for FileAttachmentUser |
| `ONYX_HOST_HEADER` | unset | `Host` header to send (set when `LOCUST_HOST` targets an internal Service to bypass an external ALB/WAF for high-rps runs) |
| `ONYX_SHAPE` | unset | `stepramp` activates the staged ramp shape |
| `ONYX_RAMP_STAGES` / `ONYX_RAMP_DWELL` / `ONYX_RAMP_SPAWN` | `25,50,100,200` / 300 / 5 | Ramp user plateaus, dwell seconds, spawn rate |
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
- `*:create-session` — multi-turn session creation (LongConversationUser)
- `disconnect:disconnected` — turns ended by a deliberate mid-stream
  disconnect (DisconnectUser); kept separate from success/failure

A turn fails on: non-200, an error packet, a stream stalling past the read
timeout, or a stream ending without answer content / without the `stop`
packet (truncation).

### Prometheus + Grafana correlation

The master exposes milestone metrics for Prometheus on a dedicated port
(default `9646`, `LOCUST_PROMETHEUS_PORT` to override) at `/metrics`:

- `locust_users`
- `locust_requests_total{name,method}` / `locust_failures_total{name,method}`
- `locust_response_time_p50_milliseconds` / `..._p95_milliseconds{name,method}`
- `locust_current_rps{name,method}`

Scrape it: annotation-based Prometheus uses the master pod's
`prometheus.io/scrape` annotations; **Prometheus Operator
(kube-prometheus-stack) ignores annotations and needs a ServiceMonitor**
targeting the `metrics` service port (commented example in `k8s/locust.yaml`).
Then import
`dashboards/chat-loadtest-correlation.json` to overlay milestone latency and
failure rate against server-side CPU/memory on one timeline — set the
dashboard's `$namespace` / `$workload` variables to the deployment under
load. That overlay is how you read the collapse point: the user count where
p95 / failure rate bend up, and which resource saturates first.

## Docker

```bash
cd loadtest && docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
docker run -p 8001:8000 onyx-mock-llm

# Locust harness image (locustfile + scenarios baked in, for k8s/)
docker build -t onyx-loadtest .
```

## In-cluster (`k8s/`)

Run the whole rig inside the target cluster so latency measurements aren't
polluted by WAN jitter and the LLM stays free:

1. `kubectl apply -n <onyx-namespace> -f k8s/mock-llm.yaml`, then register
   `http://onyx-mock-llm:8000` as an `openai_compatible` provider (see Mock
   LLM server above; keep it `is_public=false` and persona-scoped so real
   users never see it).
2. `kubectl create secret generic onyx-loadtest --from-literal=ONYX_API_KEY=...`
3. `kubectl apply -n <onyx-namespace> -f k8s/locust.yaml`, then
   `kubectl port-forward svc/onyx-loadtest-master 8089:8089` and drive runs
   from the web UI. Scale `onyx-loadtest-worker` replicas for bigger runs,
   and pin workers to a dedicated nodegroup if available (see comments in
   the manifest).

## Roadmap

- ✅ Phase 0: harness + milestones + mock LLM core
- ✅ Phase 1: tool-call & deep-research scripting, scenarios, Dockerfile
- ✅ Phase 2: in-cluster Locust master/workers + mock provider (`k8s/`)
- ✅ Phase 3: weighted scenario mix, multi-tool turns, multi-turn long-history
  sessions, mid-stream disconnects, staged collapse-point ramp
- ✅ Phase 4: Prometheus exporter (`/metrics`) + Grafana correlation dashboard
  (`dashboards/`)
