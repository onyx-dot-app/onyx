# Onyx Chat Load Tests (Locust)

Use this suite to measure Onyx throughput, latency, and resource use as concurrent
chat and search users increase. It uses Locust to send requests to an Onyx deployment.

LLM calls go to a mock server that generates answers, tool calls, and response
delays. Onyx still handles the requests and runs retrieval against the configured
search index. This setup lets you compare application builds under the same
controlled workload.

Results depend on the mock's response sizes, search decisions, and timing, as well
as the deployment and corpus. To estimate production capacity, first check how
closely those settings match real traffic. The profiles named **representative**
provide configurable starting points; they have not been validated against production traffic.

This guide is for engineers comparing Onyx builds or investigating load-related
failures. It assumes an Onyx deployment and familiarity with Python and Locust.

A **turn** starts with one user message and includes all tool and model calls until
the answer finishes. A **profile** defines the mock's output sizes, search rounds,
and delays. **Think time** is the pause after a simulated user finishes a turn.

Read the scope below, then use [Setup](#setup) and [Run a scenario](#run-a-scenario).
Profile assumptions and configuration references follow those instructions.

## What is mocked, and what runs for real?

This table describes the intended setup with the bundled mock provider. Verify
actual provider routing before interpreting a run; overrides can select other
providers, and helper calls may use a different model from the main chat call.

| Part of a turn | What this test does |
|---|---|
| LLM inference | **Mocked.** The mock serves generated responses through a Chat Completions endpoint. No real chat/reasoning model runs there. |
| Answer and reasoning content | **Mocked.** Text is synthetic. It does not answer the question or establish reasoning quality. |
| Tool choice, search rounds, query count, and tool arguments | **Mocked.** Rules and seeded profiles choose the work instead of a model making decisions. |
| Query rewriting, section selection, relevance classification, and source/time decisions | **Mocked LLM responses.** Outputs follow deterministic rules or sampled fixtures. They are not relevance judgments. |
| Citations | **Synthetic markers using real returned document numbers.** The mock does not check whether a document supports its answer. |
| Model latency, output pace, reasoning events, and argument fragmentation | **Simulated schedules and fragments.** They do not reproduce provider queues, network behavior, or the complete real latency distribution. |
| Token usage and cost | **Simulated usage accounting.** Tokenizer counts follow a fixed convention. They are not provider usage or billing measurements. |
| Provider failures | **Absent from the normal profile.** Rate limits, malformed calls, and stalls occur only in explicit fault scenarios. |
| Users and questions | **Synthetic traffic.** Locust supplies configured questions, sessions, startup delays, and think time. These are not observed human traffic patterns. |
| API execution and stream handling | **Real application work.** Request handling, orchestration, prompt construction, local tokenization, serialization, and delivery run in the target application. |
| Embeddings and retrieval | **Real configured services, unless separately replaced.** The mock LLM does not mock embeddings or the search index. Corpus and cache state still affect the work. |
| Database, Redis, pods, and networking | **Real configured infrastructure.** Its topology and resources may differ from production. |

The mock does not incur real LLM inference charges. Embedding providers and cloud
infrastructure can still incur charges. A real provider selected accidentally can
also receive calls; choosing a mock chat model does not prove every helper is mocked.

## What the results can and cannot establish

A valid result is: **“Build A completed X turns/minute under mock profile P, corpus
C, pacing T, and resources R.”** A matched comparison can identify an application
regression under those conditions. A profile can also expose a real bug or CPU
hotspot in the exercised code.

The result alone does **not** establish:

- How many real customers or concurrent production users the application supports.
- Real-model answer latency, correctness, completeness, recall, or cost.
- The prevalence of a bottleneck or failure under real traffic.
- Performance with a different provider, corpus, tool mix, session history, or cache state.

ERAG observations informed selected output sizes, search counts, and helper timings.
They do not validate the full workload. Chat, research, pacing, chunk boundaries,
and correlations between workload dimensions include explicit assumptions. Even
using all ERAG questions and documents leaves LLM behavior mocked. A separate real
ERAG run measures real-model behavior; this load suite does not replace that run.

**Reporting instructions for humans and agents:** Label results “synthetic load
with mocked LLMs.” Record provider routing, image versions, profile, seeds, corpus,
pacing, resources, and measurement windows. Report actual workload metrics with
latency, throughput, failures, and resource use. State deviations from the intended
setup. Do not call a profile representative of production without supporting
real-traffic measurements. Do not present a passed synthetic capacity threshold
as a production capacity guarantee.

Keep mock configuration, corpus, pacing, and infrastructure fixed across application
builds. Before extrapolating, compare generated prompt sizes, search rounds, stream
events, response sizes, and timing with the target real workload. Report remaining
gaps even when those individual distributions match.

## Setup

### Install the test dependencies

Run these commands from the repository root:

```bash
uv sync --group loadtest
cd tools/loadtest
```

The optional `loadtest` dependency group installs Locust and its dependencies.
Keep `--group loadtest` in subsequent `uv run` commands to retain that group.
All remaining local commands assume `tools/loadtest` as the working directory.

### Start and register the mock provider

Start the mock in a separate terminal:

```bash
uv run --group loadtest uvicorn mock_llm.app:app --port 8001
```

Register a provider through **Admin Panel → LLM** or `PUT /api/admin/llm/provider`:

| Setting | Value |
|---|---|
| Provider type | `openai_compatible` |
| API base | A URL reachable from the API server, such as `http://localhost:8001` for a shared host |
| API key | Any nonempty mock value |
| Models | `mock-profile-chat-v1`, `mock-profile-search-v1`, and any additional model names used by the selected scenarios |
| Maximum input tokens | At least 50,000 per model for deep research; use the same limit across compared builds |

Use `openai_compatible` because the mock implements Chat Completions. The `openai`
provider can route through the Responses API, which this mock does not implement.
Select a mock model for the provider's fast/helper model too. Helper calls may not
inherit the main chat override. Verify routing for both call types before testing.

Create a load-test API key through **Admin Panel → API Keys**. An admin can also use
`POST /api/admin/api-key` with `{"name": "loadtest", "role": "basic"}`.

## Run a scenario

Set the API key, provider name, and frontend URL in your shell:

```bash
export ONYX_API_KEY='<load-test-api-key>'
export ONYX_LLM_PROVIDER='<registered-mock-provider-name>'
export LOCUST_HOST='https://<your-onyx-url>'
```

Run one scenario at a time for capacity comparisons. For example, start five search users:

```bash
ONYX_MESSAGES_FILE=/path/to/questions.jsonl \
  uv run --group loadtest locust --headless -u 5 -r 1 -t 5m \
  --host "$LOCUST_HOST" --csv search ChatWithSearchUser
```

This example includes startup and warmup in its CSV. Exclude warmup before using
that CSV for a capacity decision. See [Interpret user capacity](#interpret-user-capacity).

### Select scenarios explicitly

The following weights apply when you select these four classes together. They are
a configured test mix, not a measured distribution of production traffic.

| Scenario | Metrics | Weight | Work performed |
|---|---|---:|---|
| `BasicChatUser` | `chat:*` | 70 | One user turn with a direct simulated answer |
| `ChatWithSearchUser` | `search:*` | 20 | Profile-selected search rounds with real retrieval and simulated model decisions |
| `MultiToolUser` | `multitool:*` | 8 | Up to three different retrieval tools in parallel, using `mock-tools3` |
| `DeepResearchUser` | `dr:*` | 2 | Planning, research agents, and reports using mocked model calls |

To run that mix, register all required models and name the classes:

```bash
uv run --group loadtest locust --headless -u 50 -r 5 -t 15m \
  --host "$LOCUST_HOST" \
  BasicChatUser ChatWithSearchUser MultiToolUser DeepResearchUser
```

The entrypoint also exposes diagnostic classes. Omitting class names can include
those classes; it does not guarantee the four-scenario mix above.

## Configure the mock workload

### Model-name parameters

The mock reads parameters from the model name. Register the exact name before use.

| Parameter | Example | Meaning |
|---|---|---|
| `ttft<ms>` | `mock-ttft500` | initial delay before emitted output |
| `itl<ms>` | `mock-itl20` | pacing interval; units depend on the profile, not tokenizer tokens |
| `len<n>` | `mock-len400` | generic answer length in whitespace chunks; does not pad search helper outputs |
| `sections<n>` | `mock-sections10` | select up to `n` valid sections, capped by candidates and prompt maximum |
| `class<n>` | `mock-class2` | force context expansion class `0`–`3` for controlled stress tests |
| `tools<n>` | `mock-tools1` | call up to `n` retrieval tools (in parallel for `n>1`) on the first AUTO cycle |
| `agents<n>` | `mock-agents2` | parallel research agents per DR orchestrator cycle |

The mock honors `tool_choice` values of none, auto, required, and a forced tool.
It also supports the deep-research phase sequence and output-token limits.

### Search workload calibration

Search helpers return valid outputs instead of generic filler. Semantic rewrites
keep the question. Keyword rewrites keep its terms and remove common question
words. Section selection returns offered IDs. Classification returns one digit
from `0` through `3`. These outputs drive real retrieval and context expansion.

The default selection and classification distributions come from 396 successful
ERAG questions with one search each, using Luna medium on 2026-10-22. The sanitized
[calibration file](mock_llm/search_calibration.json) contains selection rank lists
and aggregate classification counts. It contains no prompts or document content.
Stable request hashes select weighted samples, so transports and repeated calls
produce the same answer. Selection retains the sampled rank preference, caps IDs
to available candidates, and fills missing ranks from the remaining candidates.
The observed selection median was four sections. Classification counts were
`0: 56`, `1: 707`, `2: 1020`, and `3: 24`; one failed classification was excluded.
This sample describes one corpus and model, not all production workloads.

Source and time helpers return valid neutral decisions: `[]` and
`updated (None, None)`. The calibration sample had no such calls. These responses
exercise unscoped searches; they do not simulate user-directed source or date
filters. Unknown prompts still receive generic filler.

Usage uses the fixed `cl100k_base` tokenizer on serialized messages/tools and
generated text, reasoning, and tool arguments. This is a reproducible simulation
convention, not provider billing. It is separate from word count and stream chunk
count. Streamed responses include usage when `stream_options.include_usage` is
true; plain responses always include the same usage. The Docker image downloads
the encoding at build time. Local runs cache it on first use.

Both transports return the same text and reasoning. Output limits apply to token
counts, including generated reasoning. Truncated text finishes with `length`, so
tests can exercise parser fallback behavior.

Use `sections` and `class` to isolate expansion costs. Keep model knobs and corpus
identical across builds. Preserve the old mock image digest when reproducing old
runs; this version intentionally corrects the helper workload.

### Representative turn profiles (synthetic)

Basic chat and search now default to representative profiles. They use a small
fixed mix instead of one answer length. Existing numeric knobs remain available
for explicit stress tests. Register every selected model name before a run.

| Model | Workload |
|---|---|
| `mock-profile-chat-v1` | Direct answer with an assumed size mix; no automatic retrieval |
| `mock-profile-search-v1` | Search rounds, query fan-out, reasoning, and cited answers |
| `mock-profile-research-v1-agents2` | Existing two-agent research sequence with 900-word reports and 15-second nominal response duration |
| `mock-profile-held-v1` | A deliberately held response: 600 words over 121 seconds |

The search profile uses selected observations from successful Luna-medium ERAG
turns on October 22, 2026. Main and SDK had about 19% repeated-search turns. Median answers contained
75 words; means were 204–209 words; p95 was 844–904 words. This reduced fixture
uses the following buckets. It contains no recorded prompts or private documents.

| Intended share | Answer words | Search rounds | Nominal final model duration |
|---|---:|---:|---:|
| 60% | 75 | 1 | 3.0s |
| 20% | 180 | 1 | 4.5s |
| 10% | 180 | 2 | 4.5s |
| 5% | 900 | 3 | 12.0s |
| 5% | 1,300 | 4 | 18.0s |

The profile maps each question hash to one of 100 equally weighted buckets. The
full bucket set averages 209 answer words and 1.35 search rounds. Twelve buckets
use three initial queries. Later rounds use one
query each. About half of question hashes include 60 words of reasoning. These
are transparent workload assumptions, not a full empirical replay. In particular,
the correlation between answer size and extra searches is a simplified model.
Chat reuses the answer mix as an explicit assumption; ERAG does not calibrate
ordinary chat. Research and held-stream profiles are separate synthetic scenarios.

The question and `MOCK_WORKLOAD_SEED` select a stable plan. Retrieved documents,
random tool IDs, worker timing, and transport do not change that selection. A new
user message resets the search-round count. Citations reference only document
numbers found in current-turn tool results; an empty result cannot invent one.
Tool arguments use 12-character fragments. Answer and reasoning text use
six-character fragments. These boundaries model delivery work, not tokenizer IDs.

Tool-producing calls take 1.5 seconds nominally. Helper durations are 0.99 seconds
for semantic rewrite, 1.15 for keywords, 1.04 for selection, and 0.88 for
classification. Scope helpers use an uncalibrated one-second duration. Final
responses start emitting after 1.4 seconds. Streamed and plain responses share an
absolute completion deadline, so stream scheduling does not accumulate one sleep
overhead per fragment. These settings approximate typical model waits, not network
or provider tail behavior. Explicit `ttft` and `itl` knobs override the schedule;
`len` overrides answer words. Keep low-delay CPU stress runs separate from capacity
runs with representative model waits.

## Reproduce the input mix

Use `ONYX_MESSAGES_FILE` for corpus-relevant questions. It accepts one question per
line or ERAG-style `.jsonl` records with a `question` string. Gold answers and other
fields are ignored. The built-in 46 generic questions are a development fallback,
not evidence of ERAG fidelity. Do not pad or duplicate questions to enlarge a corpus.

Generate a manifest before both builds:

```bash
ONYX_MESSAGES_FILE=/path/to/questions.jsonl \
  uv run --group loadtest python workload_manifest.py \
  --model mock-profile-search-v1 --seed 0 --output search-workload.json
```

Use the same file hash, model, mock seed, generator seed, worker count, and user
count for each comparison. The manifest lists the expected one-pass mix without
question text. It accepts base profile names, including the research agent count,
but rejects stress and fault overrides. Small corpora can sample the buckets unevenly. Check the manifest
instead of assuming the bucket percentages occurred in your run.

Each simulated user gets a reproducible shuffled question sequence. Startup delay
and think-time jitter spread requests across time. Distributed schedules use the
worker index and local user number. Keep the same workers and scenario selection
between builds; changing worker assignments changes user sequences. Faster builds
can finish more of each sequence, so short runs can still have different completed
mixes. Run long enough to cover the input set and check actual workload metrics.

The mock's `/metrics` endpoint reports prepared calls by profile, size, and phase,
planned token/chunk histograms, and completed responses by transport. These counts
reset when the mock restarts. They measure model calls, not whole application turns.
Locust `/metrics` adds `onyx_loadtest_active`, `started`, `finished`, `answer_chars`,
`packets`, `search_calls`, `reasoning_packets`, and `citations`, labelled by scenario.
Finished counts include failed setup and interrupted turns; success rates come from Locust request statistics.
Counts reset at test start and survive a Locust statistics reset. Compare interval
deltas when excluding warmup. Missing workers retain their last cumulative counts
but contribute no active turns; counts can lag worker reports. Scrape the mock separately from the API pods; tokenizer
work inside the mock must not become a load-generator bottleneck.

## Interpret user capacity

A configured user includes request time and think time. It is not an always-active
request. Set `ONYX_WAIT_SECONDS=0` for a separate continuous-demand stress test.
For normal users, report mean pause, active turns, completed turns/minute, p50/p95,
failures, and API CPU/memory/threads together. Collect resources through the existing
Prometheus dashboards and deployment monitoring.

A **plateau** holds a fixed user count for a measurement interval.
Run each chat/search plateau separately after warmup. Export its Locust stats CSV,
then assess explicit acceptance targets:

```bash
uv run --group loadtest python capacity_report.py search_stats.csv \
  --users 100 --think-seconds 15 --p95-seconds 30 \
  --max-failure-ratio 0.01 --minimum-turns 100
```

The report requires both latency and reliability to pass, with enough completed
turns. It does not infer a maximum from one plateau or assess infrastructure health.
Retain the manifest, image digests, CSV, and resource series with the result.

## Test reliability separately

Fault injection is opt-in through explicit model names. It never appears in the
representative mix. Register the exact model and override `ONYX_SEARCH_MODEL` or
`ONYX_CHAT_MODEL` only for the reliability run:

| Suffix | Behavior |
|---|---|
| `-fault429` | Every request returns a rate limit with `Retry-After: 1` |
| `-faultmalformed` | Tool calls contain incomplete JSON arguments |
| `-faultstall` | Stream emits a header, then stalls for 120 seconds; plain responses also wait 120 seconds |

For example, `mock-profile-search-v1-faultmalformed` exercises tool-argument error
handling. Use existing `DisconnectUser` for client disconnects and `ThreadHogUser`
for held connections. Keep fault results separate from ordinary capacity results.
The mock still uses Chat Completions, not a Responses API wire replay.

### Explicit stress profiles

These parameter combinations create controlled stress conditions. They are not
measurements of a named provider. Register each exact model name before use.
Longer simulated responses hold application resources for longer.

| Stress condition | Model name |
|---|---|
| Short initial delay | `mock-ttft300-itl15-len150` |
| Long delay before output | `mock-ttft8000-itl40-len600` |
| Slow response | `mock-ttft20000-itl200-len300` |
| Long answer | `mock-ttft500-itl20-len2000` |

## Diagnostic scenarios

### Question diversity and retrieval

The fallback questions live in `onyx_client/messages.py`. The client assigns a
seeded question order to each user. See [Reproduce the input mix](#reproduce-the-input-mix)
for external question files and comparison controls.

Repeated queries can increase cache reuse. Unrelated questions can change keyword
matches, selected sections, prompt sizes, and embedding work. A real search index
does not make arbitrary questions equivalent to corpus-relevant questions. Use
questions relevant to the indexed documents and record cache conditions.

### Targeted scenarios

Select these classes explicitly to investigate a specific behavior. A scenario
exercises the configured path; it does not establish that a failure occurs in production.

| Scenario | Behavior | Main controls |
|---|---|---|
| `LongConversationUser` | Reuses a session and chains message IDs so history grows | `ONYX_SESSION_TURNS`, default 20 |
| `DisconnectUser` | Closes the client stream at a chosen milestone | `ONYX_DISCONNECT_AFTER`, default `first_answer_token` |
| `CompressionUser` | Sends large messages in a long session to exercise context compression | Default 60 turns and 8,000-character messages; configure a small model input limit |
| `FileAttachmentUser` | Uploads a file and attaches it to turns | `ONYX_FILE_KB`, default 512; `ONYX_SESSION_TURNS` for session reuse |

Compression depends on the context limit and accumulated history. It does not
necessarily occur on every turn. Register `mock-smallctx` with a small input limit,
such as 16,000 tokens, before this example:

```bash
ONYX_LONGCONV_MODEL=mock-smallctx \
  uv run --group loadtest locust --headless -u 25 -r 5 -t 20m \
  --host "$LOCUST_HOST" CompressionUser
```

Targeted scenarios can inherit the deployment's model when their override is unset.
Set `ONYX_LLM_MODEL` or the scenario-specific override to a registered mock model.

### Increase load in stages

Set `ONYX_SHAPE=stepramp` to increase users through configured plateaus. The shape
overrides `-u` and `-r`. Use an explicit class selection:

```bash
ONYX_SHAPE=stepramp ONYX_RAMP_STAGES=25,50,100,200 ONYX_RAMP_DWELL=300 \
  uv run --group loadtest locust --headless \
  --host "$LOCUST_HOST" ChatWithSearchUser
```

Compare each plateau against your latency and failure targets. Record resource
metrics to investigate a slowdown; higher latency alone does not prove CPU saturation.

### Probe health during long streams

Use `ThreadHogUser` and `HealthProbeUser` to investigate resource pressure during
long streams. `ThreadHogUser` defaults to a response lasting about 121 seconds.
`HealthProbeUser` keeps a fixed number of probe users, independent of the weighted
user mix. Its default is one probe user, a one-second interval, and a ten-second
latency threshold.

```bash
ONYX_HEALTH_PATH=/api/health \
  uv run --group loadtest locust --headless -u 50 -r 5 -t 15m \
  --host "$LOCUST_HOST" ThreadHogUser HealthProbeUser
```

This example allocates one probe user and the remaining users to held streams.
Startup delays and pauses mean those users are not continuously active requests.
Measure actual active turns and thread counts. Thread occupancy depends on the
application implementation; do not assume one request always consumes one thread.

Probe failures are diagnostic signals. They do not prove Kubernetes will restart
a pod. Check the deployment's actual probe route, timeout, failure threshold, and
events. Use `/api/health` through the frontend or nginx route. A direct API-service
probe uses `/health` and measures a different network path.

Compare application worker count, thread-pool size, and CPU allocation in separate
runs. Keep the workload fixed and inspect latency, failures, memory, and recovery.
Do not select a production configuration from probe success alone.

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `ONYX_API_KEY` | required | Bearer token for all requests |
| `ONYX_LLM_PROVIDER` | unset | Provider name for `llm_override` (needed when the mock isn't the deployment default) |
| `ONYX_LLM_MODEL` | unset | Fallback model override; `ONYX_CHAT_MODEL` takes precedence for basic chat |
| `ONYX_CHAT_MODEL` | `mock-profile-chat-v1` | Basic chat model when neither override is set |
| `ONYX_SEARCH_MODEL` | `mock-profile-search-v1` | Model for ChatWithSearchUser |
| `ONYX_MULTITOOL_MODEL` | `mock-tools3` | Model for MultiToolUser |
| `ONYX_DR_MODEL` | `mock-profile-research-v1-agents2` | Model for DeepResearchUser |
| `ONYX_HOG_MODEL` | `mock-ttft1000-itl200-len600` | Slow model for ThreadHogUser; controls simulated response duration |
| `ONYX_HOG_WAIT_SECONDS` / `ONYX_HOG_STREAM_READ_TIMEOUT` | 1 / 600 | ThreadHogUser think time / max inter-chunk wait |
| `ONYX_HEALTH_PATH` | `/health` | Health-probe path (`/api/health` via web/nginx host) |
| `ONYX_HEALTH_PROBES` | 1 | Number of HealthProbeUser instances to pin (independent of `-u`) |
| `ONYX_HEALTH_INTERVAL` | 1.0 | Seconds between health probes |
| `ONYX_HEALTH_SLA_MS` | 10000 | Fail a probe slower than this; independent of Kubernetes probe settings |
| `ONYX_LONGCONV_MODEL` | unset | Model for LongConversationUser; falls back to `ONYX_LLM_MODEL`, then the deployment default |
| `ONYX_SESSION_TURNS` | 1 | Turns to keep one session alive (LongConversationUser 20, CompressionUser 60) |
| `ONYX_MSG_CHARS` | 0 | Per-message size in chars (CompressionUser defaults to 8000; 0 = short questions) |
| `ONYX_MESSAGES_FILE` | unset | Text question file or ERAG-style JSONL; replaces the fallback questions |
| `ONYX_DISCONNECT_AFTER` | `first_answer_token` | Milestone after which DisconnectUser drops the stream |
| `ONYX_FILE_KB` | 512 | Uploaded file size (KB) for FileAttachmentUser |
| `ONYX_HOST_HEADER` | unset | `Host` header to send (set when `LOCUST_HOST` targets an internal Service to bypass an external ALB/WAF for high-rps runs) |
| `ONYX_SHAPE` | unset | `stepramp` activates the staged ramp shape |
| `ONYX_RAMP_STAGES` / `ONYX_RAMP_DWELL` / `ONYX_RAMP_SPAWN` | `25,50,100,200` / 300 / 5 | Ramp user plateaus, dwell seconds, spawn rate |
| `ONYX_WAIT_SECONDS` | 15 | Mean pause after each ordinary chat/search turn, excluding request time |
| `ONYX_WAIT_JITTER` | 0.5 | Deterministic pause variation: default range is 7.5–22.5 seconds; 0 means fixed |
| `ONYX_START_STAGGER_SECONDS` | 15 | Initial per-user delay sampled deterministically between zero and this limit |
| `ONYX_SCHEDULE_SEED` | 0 | Reproducible per-user question order, pauses, and startup delay |
| `MOCK_WORKLOAD_SEED` | 0 | Mock-server seed for selecting a question's representative turn plan |
| `ONYX_DR_WAIT_SECONDS` | 30 | Think time for DR users |
| `ONYX_STREAM_READ_TIMEOUT` | 180 | Max seconds between stream chunks |
| `ONYX_DR_STREAM_READ_TIMEOUT` | 300 | Same, for DR turns |
| `MOCK_TTFT_MS` / `MOCK_ITL_MS` / `MOCK_LEN_TOKENS` | 300 / 15 / 150 | Fixed-stress defaults: initial delay, pacing interval, and answer words; profile timing takes precedence |

## Metrics

Each turn fires named pseudo-requests (`<scenario>:<milestone>`) the moment
the milestone packet arrives; Locust aggregates percentiles per name:

- `*:first_packet` — elapsed time to the first stream line
- `*:first_search_doc` — elapsed time from request start to the first document batch; includes earlier model work
- `*:first_answer_token` — elapsed time to first answer content, including earlier searches and model calls
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

The master, or the standalone runner, exposes milestone metrics on a dedicated port
(default `9646`, `LOCUST_PROMETHEUS_PORT` to override) at `/metrics`:

- `locust_users`
- `locust_requests_total{name,method}` / `locust_failures_total{name,method}`
- `locust_response_time_p50_milliseconds` / `..._p95_milliseconds{name,method}`
- `locust_current_rps{name,method}`

For annotation-based scraping, use the pod annotations. Prometheus Operator needs
a ServiceMonitor targeting the `metrics` service port. See `k8s/locust.yaml`.

Import `dashboards/chat-loadtest-correlation.json` into Grafana. Set its namespace
and workload variables to the target deployment. Compare latency and failures
with CPU and memory over the same interval. Correlation helps identify candidates
for investigation; it does not establish the cause of a slowdown.

## Docker

```bash
docker build -f mock_llm/Dockerfile -t onyx-mock-llm .
docker run -p 8001:8000 onyx-mock-llm

# Locust harness image (locustfile + scenarios baked in, for k8s/)
docker build -t onyx-loadtest .
```

## Deploy the test components in Kubernetes

Run the mock and load generator in the target test cluster to reduce external
network variation. Cloud infrastructure and real embedding services can still incur costs.

1. Build and publish the mock and Locust images. Replace the image placeholders in `k8s/` with fixed image versions.
2. Deploy the mock with `kubectl apply -n <onyx-namespace> -f k8s/mock-llm.yaml`.
3. Register `http://onyx-mock-llm:8000` as an `openai_compatible` provider. Restrict it to load-test agents.
4. Create the `onyx-loadtest` secret in that namespace with an `ONYX_API_KEY` value.
5. Configure the frontend host, mock provider, question-file mount, and seeds in `k8s/locust.yaml`.
6. Deploy Locust with `kubectl apply -n <onyx-namespace> -f k8s/locust.yaml`.
7. Forward its web interface with `kubectl port-forward -n <onyx-namespace> svc/onyx-loadtest-master 8089:8089`.
8. Select scenarios and start the run from the web interface.

Use the same image for all Locust workers. Add workers when the generator becomes
a bottleneck. A dedicated node group reduces competition between the generator
and the application. Verify mock and helper routing before collecting results.

## Maintain and test the harness

Keep `onyx.*` imports out of the Locust runtime. Gevent changes networking behavior
and can conflict with backend dependencies. The stream parser is a local copy of
the application protocol and must stay consistent with that protocol.

Run the contract tests from `tools/loadtest`:

```bash
uv run --group loadtest pytest tests/ -q
```

This README uses Google's guidance on [document scope and organization](https://developers.google.com/tech-writing/one/documents)
and [clear sentences](https://developers.google.com/tech-writing/one/clear-sentences).
