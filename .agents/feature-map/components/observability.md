# Observability

> How Onyx is watched: Prometheus metrics, LLM tracing, audit logging, usage
> and cost accounting, fleet telemetry, and outbound hooks. This component
> watches the system; it does not run the system.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** observability
**Edition:** CE for metrics, tracing, audit logging, and fleet telemetry. EE for
hooks, usage export/reporting, log export, and query history.
**Owns:**
`backend/onyx/server/metrics/` (all files), `backend/onyx/tracing/` (all files,
including `framework/` and `processors/`), `backend/onyx/server/manage/tracing/api.py`,
`backend/onyx/db/tracing.py`, `backend/onyx/db/usage.py`, `db/user_usage.py`,
`db/system_usage.py`, `db/llm_usage.py`, `backend/onyx/server/features/usage/`,
`backend/onyx/hooks/`, `backend/ee/onyx/hooks/`, `backend/onyx/db/hook.py`,
`backend/onyx/server/features/hooks/`, `backend/ee/onyx/server/features/hooks/`,
`backend/onyx/server/middleware/latency_logging.py`,
`backend/onyx/utils/audit.py`, `backend/onyx/utils/credential_audit.py`,
`backend/onyx/utils/fleet_telemetry.py`, `fleet_query_telemetry.py`,
`fleet_telemetry_collector.py`, `fleet_telemetry_resources.py`, `telemetry.py`,
`timing.py`, `backend/onyx/db/fleet_telemetry.py`, `db/fleet_enrollment.py`,
`deployment/fleet-telemetry.md`,
`backend/ee/onyx/server/query_history/`, `backend/ee/onyx/server/log_export/`,
`backend/ee/onyx/background/celery/tasks/usage_reporting/`,
`backend/ee/onyx/background/celery/tasks/log_export/`,
`web/src/app/admin/tracing/`, `web/src/app/admin/systeminfo/`

**Read first:** `docs/METRICS.md` and `docs/AUDIT_LOGGING.md`, plus
`deployment/fleet-telemetry.md` for fleet telemetry. They are the primary specs;
this document maps them to code and adds verification guidance.

---

## 1. What the user experiences

An operator scrapes `GET /metrics` on the API server, the MCP server, and each
Celery worker's standalone metrics port, and wires the results into Grafana.
No dashboard ships in-product; `docs/METRICS.md` documents every metric and
gives PromQL starting points.

An admin connects Braintrust or Langfuse under **Admin > Tracing**
(`web/src/app/admin/tracing/page.tsx`), pastes an API key, and sees every
tagged LLM call as a trace with model, provider, tokens, and (unless masked or
incognito) the actual prompt and response. `Admin > System Info`
(`web/src/app/admin/systeminfo/page.tsx`) shows only build versions, not
metrics.

A user sees their own token/cost usage on a Usage tab
(`GET /user/usage`, `server/features/usage/api.py:get_my_usage`). An admin sees
company-wide usage broken out by user (`GET /admin/usage/export`) and by
non-user system flows such as contextual RAG (`GET /admin/usage/system`), can
reset a user's usage window, and can request a downloadable usage report ZIP
(`ee/onyx/background/celery/tasks/usage_reporting/tasks.py:generate_usage_report_task`)
containing per-user and per-system CSVs plus a PDF summary (see
`docs/usage/usage-reports.md`).

An admin with the right permission also reviews **Query History**
(`ee/onyx/server/query_history/api.py`) for chat-session-level audit and
exports it, downloads a **log export** bundle of raw log files for support or
compliance (`ee/onyx/server/log_export/api.py`), and reads security-relevant
events (login, permission changes, credential access) as JSON lines on the
`onyx.audit` logger tree, shipped to whatever SIEM the operator points a log
shipper at (`docs/AUDIT_LOGGING.md`).

An admin can also register an **outbound hook**: an HTTPS endpoint Onyx calls
synchronously at a fixed point in a pipeline (document ingestion, document
push, or query processing) and waits on for a response, configurable at
**Admin > Hooks** (`ee/onyx/server/features/hooks/api.py`).

By default, every installation also sends fleet telemetry to the Onyx fleet
service. It sends approved health, version, connector, indexing, query-timing,
license-presence, and signup-domain values. It never sends document content,
names, credentials, or full email addresses. The operator does not need to
configure it, and one deployment setting turns it off (see §2). Onyx continues to
operate when the fleet service is not available.

---

## 2. Surfaces

### Metrics

| Surface | Auth | Notes |
|---|---|---|
| `GET /metrics` (API server) | Bearer token | `server/metrics/prometheus_setup.py:expose_prometheus_metrics`, guarded by `metrics_auth.py:verify_metrics_token`. |
| `GET /metrics` (MCP server) | Bearer token | Same auth dependency, separate process. |
| Celery worker metrics port | None (network-level only) | `metrics_server.py:start_metrics_server`; per-worker default ports (docfetching 9092, docprocessing 9093, monitoring 9096, heavy 9094, light 9095, primary 9097, scheduled_tasks 9098). |

### Tracing admin endpoints (`server/manage/tracing/api.py`, prefix `/admin/tracing`)

| Method | Path | Handler |
|---|---|---|
| GET | `/admin/tracing/providers` | `list_tracing_providers` |
| POST | `/admin/tracing/providers` | `upsert_tracing_provider_endpoint` |
| DELETE | `/admin/tracing/providers/{provider_type}` | `disconnect_tracing_provider` |
| POST | `/admin/tracing/providers/test` | `test_tracing_provider` |
| POST | `/admin/tracing/providers/{provider_type}/adopt-env` | `adopt_env_tracing_provider` |

Every route in this router carries `Depends(_reject_if_multi_tenant)`
(`server/manage/tracing/api.py`); see §5 and §9.

### Usage endpoints (`server/features/usage/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/user/usage` | `get_my_usage` | Caller's own token/cost usage and budget; `scope_exempt` so a scoped PAT can read its owner's usage. |
| GET | `/admin/usage/export` | `export_usage` | Company-wide usage by user email. |
| GET | `/admin/usage/system` | `get_system_usage` | Non-user (system-attributed) usage, e.g. contextual RAG. |
| POST | `/admin/usage/reset` | `reset_usage` | Clears one user's usage across every active rate-limit window. |
| GET/PUT/DELETE | `/admin/cost-overrides` | `list_cost_overrides`, `upsert_cost_override`, `delete_cost_override` | Per-model price overrides used by cost computation. |

### Hooks endpoints (`ee/onyx/server/features/hooks/api.py`, prefix `/admin/hooks`)

`GET /admin/hooks/specs`, `GET|POST /admin/hooks`, `GET|PATCH|DELETE /admin/hooks/{hook_id}`,
`POST /admin/hooks/{hook_id}/activate`, `.../deactivate`, `.../validate`,
`GET /admin/hooks/{hook_id}/execution-logs`.

### Query history and log export (EE)

`ee/onyx/server/query_history/api.py`: `GET /admin/chat-sessions`,
`GET /admin/chat-session-history`, `GET /admin/chat-session-history/{id}`,
`GET /admin/query-history/list`, `POST /admin/query-history/start-export`,
`GET /admin/query-history/export-status`, `GET /admin/query-history/download`.

`ee/onyx/server/log_export/api.py`: `POST /admin/log-export`,
`GET /admin/log-export/{export_id}`, `GET /admin/log-export/{export_id}/download`.

### Fleet telemetry

| Surface | Code | Notes |
|---|---|---|
| Collection task | `background/celery/tasks/monitoring/tasks.py:collect_fleet_telemetry` | Per-tenant beat task (`collect-fleet-telemetry`) on the `monitoring` queue, every five minutes. Onyx Lite runs the same pass from `background/periodic_poller.py:_run_fleet_telemetry`. |
| Outbound `POST /v1/enroll` and `POST /v1/events` | `utils/fleet_telemetry.py:BoundedTelemetry` | Calls to the fleet service at `ONYX_TELEMETRY_ENDPOINT`. Onyx has no inbound fleet route. |

### Environment configuration

| Variable | Default | Effect |
|---|---|---|
| `METRICS_AUTH_TOKEN` | unset | Required bearer token for `/metrics`. |
| `DISABLE_METRICS_AUTH` | `false` | Deliberately exposes `/metrics` with no auth. |
| `PROMETHEUS_METRICS_ENABLED` | `true` | Set `false` to disable a worker's standalone metrics server. |
| `PROMETHEUS_METRICS_PORT` | per-worker default | Overrides the worker's metrics port. |
| `SLOW_REQUEST_THRESHOLD_SECONDS` | `1.0` | Threshold for `onyx_api_slow_requests_total`. |
| `BRAINTRUST_API_KEY`, `BRAINTRUST_PROJECT`, `BRAINTRUST_API_URL` | `""`, `"Onyx"`, `""` | Env fallback for Braintrust when no DB row exists. |
| `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST` | `""` | Env fallback for Langfuse. |
| `TRACING_CONFIG_CACHE_TTL_SECONDS` | `30` | Re-read interval for the effective tracing config. |
| `USER_USAGE_TRACKING_ENABLED` | `true` | Gates the per-user usage recording processor. Independent of Braintrust/Langfuse. |
| `MULTI_TENANT` | | Forces tracing config to env-only and blocks `/admin/tracing/*`. |
| `DISABLE_TELEMETRY` | `false` | `true` stops fleet enrollment, sending, and collection (`utils/fleet_telemetry.py:start_telemetry`, the `collect-fleet-telemetry` beat entry, the Lite poller entry). Set it on every service. Prometheus metrics, tracing, and the other `monitoring` tasks do not change. |
| `ONYX_TELEMETRY_ENDPOINT` | `https://telemetry.onyx.app` | Fleet service base URL (`utils/fleet_telemetry.py:_ENDPOINT`). For tests only. |

---

## 3. Data model

- **`TracingProviderConfig`** (`db/models.py`, via `db/tracing.py`): one row per
  tracing provider (`provider_type`, `enabled`, encrypted `api_key`, `config`
  JSONB). Read/written by `db/tracing.py:fetch_tracing_provider`,
  `upsert_tracing_provider`, `delete_tracing_provider`.
- **`UserUsage`** (`db/models.py`): the per-actor, per-day, per-model/flow/provider
  usage rollup. `user_id` is nullable; `actor_kind` (`UsageActorKind`) and
  `system_attribution` (`SystemUsageAttribution`) distinguish a real user row
  from a system-attributed row (e.g. contextual RAG). `incognito` is a
  dedicated boolean column: an incognito turn's spend accumulates in its own
  row so reporting can separate it, per `db/models.py:UserUsage`.
- **`TenantUsage`** (`db/models.py`, via `db/usage.py`): the cloud usage-limit
  ledger, one row per rolling window (`llm_cost_cents`, `chunks_indexed`,
  `api_calls`, `non_streaming_api_calls`). This is a different concern from
  `UserUsage`: see §4.6.
- **`LLMUsageRecord`** (`db/llm_usage.py`): a Pydantic value object, not a
  table. It carries one aggregated usage sample (`model`, `flow`, `provider`,
  token counts, `cost_cents`, `window_start`) into `record_user_usage` /
  `record_system_usage`, which upsert it into `UserUsage` via
  `db/llm_usage.py:build_usage_upsert_values` (additive merge on conflict, not
  overwrite).
- **`Hook`** and **`HookExecutionLog`** (`db/models.py`): a hook row (`name`,
  `hook_point`, `endpoint_url`, encrypted `api_key`, `fail_strategy`,
  `timeout_seconds`, `is_active`, `is_reachable`, soft-deleted via `deleted`)
  and its failure log (`db/hook.py`). At most one non-deleted hook per
  `HookPoint` (`db/hook.py:create_hook__no_commit`).
- **Fleet telemetry storage.** No table holds fleet events; the sender queue is in
  memory. `db/fleet_enrollment.py:get_or_create_deployment_key` keeps one random
  key in `KVStore` (`key_value_store`) under `fleet_telemetry_deployment_key`.
  The collector keeps its read cursor and its inventory signature in the cache
  backend (`fleet_telemetry_last_run`, `fleet_telemetry_inventory`).
- Audit events are **not** a table. They are JSON-serialized log lines on the
  `onyx.audit` logger tree (`utils/audit.py`); there is no `audit_event` table
  yet (`docs/AUDIT_LOGGING.md` calls this a planned follow-up).

---

## 4. How it works

### 4.1 Prometheus metrics

`server/metrics/prometheus_setup.py:setup_prometheus_metrics` is called during
API-server startup. It registers `prometheus-fastapi-instrumentator` request
metrics (count, latency, in-progress gauge), the slow-request callback
(`slow_requests.py:slow_request_callback`), and the per-tenant callback
(`per_tenant.py:per_tenant_request_callback`), then exposes `/metrics` gated by
`metrics_auth.py:verify_metrics_token` as a FastAPI dependency. SQLAlchemy pool
metrics are registered separately, after the engines exist, via
`postgres_connection_pool.py:setup_postgres_connection_pool_metrics`.

Celery workers do not share the API server's `/metrics`. Each worker that
wants metrics calls `metrics_server.py:start_metrics_server(worker_type)` from
its `worker_ready` signal handler, which starts a standalone WSGI server on a
per-worker-type port (dual-stack IPv4/IPv6, no auth: it is meant to be scraped
inside the cluster network, not exposed externally). Generic per-task lifecycle
metrics come from `celery_task_metrics.py:on_celery_task_prerun` /
`on_celery_task_postrun` / `on_celery_task_retry` / `on_celery_task_revoked` /
`on_celery_task_rejected`, wired manually into each worker's own Celery signal
handlers; only `docfetching` and `docprocessing` currently do this
(`docs/METRICS.md` "Current Worker Integration Status").

### 4.2 Per-tenant labelling

`per_tenant.py:per_tenant_request_callback` reads
`shared_configs.contextvars.CURRENT_TENANT_ID_CONTEXTVAR` and increments
`onyx_api_requests_by_tenant_total{tenant_id,...}` on every request. This is
the model for any new HTTP-scoped metric in a multi-tenant deployment: without
a `tenant_id` label, a metric aggregates across every customer on the shared
cluster. Connector-state metrics take a different approach for the same
reason: `docs/METRICS.md` "Connector State Metrics" states that collection is
skipped entirely under multi-tenant, to avoid a cross-tenant snapshot read.

### 4.3 Tracing framework

`onyx/tracing/framework/` (`create.py`, `spans.py`, `traces.py`,
`span_data.py`, `provider.py`) is the underlying span/trace primitive:
`generation_span`, `agent_span`, `function_span` context managers, a
`TracingProcessor` interface (`processor_interface.py`), and a pluggable
processor list set via `set_trace_processors` / `add_trace_processor`.

`tracing/setup.py:setup_tracing()` registers exactly one processor at
startup, `dynamic_processor.py:DynamicTracingProcessor`, which is itself a
fan-out: on a TTL (`TRACING_CONFIG_CACHE_TTL_SECONDS`), it calls
`provider_config.py:resolve_effective_tracing_config()` and rebuilds Braintrust
/ Langfuse delegate processors (`dynamic_processor.py:build_delegates`) if the
config's fingerprint changed. A delegate set is captured per in-flight trace
(`_trace_delegates`) so a config change never disrupts a trace already in
progress. If `USER_USAGE_TRACKING_ENABLED` is true, `setup_tracing` also
registers `tracing/processors/user_usage_processor.py:UserUsageTracingProcessor`
directly via `add_trace_processor`, independent of Braintrust/Langfuse.

### 4.4 The two instrumentation entry points

- `tracing/llm_utils.py:llm_generation_span(llm, flow, ...)`: for any call that
  goes through an `LLM` subclass. Pulls model and provider off `llm.config`.
- `tracing/llm_utils.py:traced_llm_call(flow, model, provider, ...)`: for
  direct provider-SDK or cross-process calls (image generation, voice,
  embeddings/rerank to `model_server`) that bypass `LLM` entirely.

Both build a `model_config` dict tagging `flow` (an `LLMFlow` value,
`tracing/flows.py`) and `model_provider`; `flows.py:LLMFlow` enumerates every
tagged operation, grouped by area (chat/agent, secondary LLM flows, Craft,
`LLM_GATEWAY`, indexing, image, voice, embeddings/rerank).
`[[llm-providers]]` covers the LLM-provider-side detail of resolution and
retries; this file covers what happens to a span once it is opened.

Chat generation spans also record the prompt-cache flag, prefix message count,
estimated prefix tokens, and history message count in `model_config`. On span
end, Langfuse exports these fields as generation metadata. This accepts any
non-null mapping, including read-only mappings.

### 4.5 The untagged fallback flows

`LitellmLLM.invoke` and `LitellmLLM.stream` (`onyx/llm/multi_llm.py`) open their
own generation span with `llm_generation_span`. The flow comes from
`GenerationContext.flow`. If the caller sets none, the span uses
`LLMFlow.UNTAGGED_INVOKE` or `LLMFlow.UNTAGGED_STREAM`. This is a safety net
so untagged calls still get *some* observability, not a substitute for
instrumentation: a dashboard showing either sentinel means a call site did
not set `GenerationContext.flow`. Direct callers of `invoke_raw`/`stream_raw`
open no span, so they must call `llm_generation_span` or `traced_llm_call`.
A span error goes through `LitellmLLM.redact_error` first, so credentials do not reach the trace backend.

### 4.6 Masking and incognito

**Masking** (`tracing/masking.py:mask_sensitive_data`) runs inside the
Braintrust delegate before content leaves the process:
`dynamic_processor.py:_build_braintrust_processor` calls
`braintrust.set_masking_function(mask_sensitive_data)`. It recursively:
redacts any dict key containing `"private_key"` or `"authorization"` to
`"***REDACTED***"`; redacts a string containing `"private_key"` entirely, or
an `Authorization: Bearer <token>` substring within a longer string (the token
only, via regex substitution); and truncates any string longer than
`MASKING_LENGTH` (default 500,000 chars, `TRACING_MASKING_LENGTH` env),
keeping the head and a small tail with a `[TRUNCATED ... ]` marker. Langfuse
has no equivalent masking hook in `langfuse_tracing_processor.py`: masking
today is Braintrust-specific.

**Incognito** is a separate, orthogonal guarantee.
`tracing/incognito.py:suppresses_external_traces()` reads the current
`IncognitoRecordMode` from `shared_configs.contextvars` and returns true when
that mode does not permit external traces. Both
`braintrust_tracing_processor.py` and `langfuse_tracing_processor.py` call
this at trace start and drop the whole trace (spans included) when true, so
**incognito content cannot reach Braintrust or Langfuse**. The per-user usage
processor is different again: `processors/user_usage_processor.py:_capture`
still records an incognito span's token counts and cost (labeled
`incognito=True` on the `UserUsage` row), because usage accounting is not an
external trace backend. See `[[chat-persistence]]` for how incognito content
is (not) persisted to `ChatMessage`.

### 4.7 Provider config resolution and cloud gating

`provider_config.py:resolve_effective_tracing_config()` prefers a DB
`TracingProviderConfig` row per provider (`_braintrust_from_row`,
`_langfuse_from_row`); a provider with no row, or a disabled row, falls back
to that provider's env vars. Under `MULTI_TENANT`, the DB is never read: only
env vars apply. `server/manage/tracing/api.py:_reject_if_multi_tenant` enforces
the same boundary at the endpoint level, rejecting every route under
`/admin/tracing` with `OnyxErrorCode.SINGLE_TENANT_ONLY` on cloud. Cloud
tracing configuration is therefore env-only end to end.

### 4.8 Audit logging

Audit events are emitted by `utils/audit.py:emit_audit_event` (and the older
`utils/credential_audit.py:emit_credential_access` for credential-decrypt
events) as `INFO` records on the `onyx.audit.*` logger tree, with the event
serialized to JSON in the message body so the line is byte-identical
regardless of `LOG_FORMAT`. Field shape and the `action` taxonomy (a stable,
append-only `<domain>.<verb>` contract) are defined in `docs/AUDIT_LOGGING.md`;
emission is fail-safe (never raises into the caller) and deduped via Redis for
high-volume classes, degrading to always-emit if Redis is unavailable. There is
no read API in Onyx today: the documented consumption path is an external log
shipper filtering on the `onyx.audit` logger prefix.

### 4.9 Usage and cost accounting

Two independent systems both live under "usage", and they answer different
questions:

- **LLM cost tracking** (`onyx/llm/cost.py`, surfaced via `UserUsage`): what a
  specific model call cost, computed per-token from the vendored price table (`llm/price_table/`), with
  admin-configurable overrides (`server/features/usage/api.py:upsert_cost_override`,
  backed by `llm/cost_overrides.py`). This is what `UserUsageTracingProcessor`
  writes on every priced generation span.
- **Tenant usage limiting** (`db/usage.py`, `TenantUsage`): a cloud-only
  rolling-window counter (LLM cost, chunks indexed, API calls) checked against
  a hard limit via `db/usage.py:check_usage_limit`, independent of the
  per-user ledger. See `[[rate-and-usage-limits]]`.

The EE usage-report pipeline
(`ee/onyx/background/celery/tasks/usage_reporting/tasks.py:generate_usage_report_task`)
runs as a Celery task and calls
`ee/onyx/server/reporting/usage_export_generation.py:create_new_usage_report`,
which builds the CSV+PDF ZIP described in `docs/usage/usage-reports.md`.

### 4.10 Hooks

A hook is a customer-owned HTTPS endpoint Onyx calls synchronously at one of
three fixed points (`db/enums.py:HookPoint`: `DOCUMENT_INGESTION`,
`DOCUMENT_PUSH`, `QUERY_PROCESSING`), each described by a `HookPointSpec`
registered in `hooks/registry.py:_REGISTRY`. The CE entry point,
`hooks/executor.py:execute_hook`, dispatches through
`fetch_versioned_implementation` to a CE no-op (`HookSkipped`) or, on EE, to
`ee/onyx/hooks/executor.py:_execute_hook_impl`, which looks up the active hook,
posts the payload via `utils/external_endpoint.py:post_json_to_endpoint`, and
applies the hook's `fail_strategy` (`HARD` raises `OnyxError`, aborting the
pipeline; `SOFT` logs and returns `HookSoftFailed`, letting the caller fall
back to default behavior). Execution is logged only on failure
(`db/hook.py:create_hook_execution_log__no_commit`); `is_reachable` is updated
best-effort in its own session so a concurrent hook deletion cannot block the
failure log write. At most one non-deleted hook exists per `HookPoint`.
Hooks are unavailable under `MULTI_TENANT` (`ee/onyx/hooks/executor.py:_lookup_hook`).
The Community downgrade soft-deletes every hook (`deleted=True`, `is_active=False`)
in `ee/onyx/db/community_downgrade.py:disable_paid_features__no_commit` (see [[billing]] §4.5).
`QUERY_PROCESSING` fires only for chat queries submitted through the Onyx
app; it never fires for `/gateway/*` requests, so a hook cannot inspect or
reject content an external tool sends to a model provider through
[[llm-gateway]] (`hooks/points/query_processing.py`).

### 4.11 Fleet telemetry

Fleet telemetry has two parts: one sender in each instrumented process, and a
collection pass that reads the database. `deployment/fleet-telemetry.md` is the
operator reference.

**Sender.** `utils/fleet_telemetry.py:start_telemetry` starts one `BoundedTelemetry`
for the process and returns at once. `onyx/main.py:lifespan` calls it for the API
server, `app_base.py:on_worker_ready` for each Celery worker, and
`onyxbot/slack/listener.py` for the Slack listener, because Slack answers run in
that process. A spawned docfetching process starts its own sender in
`background/indexing/job_client.py:_initializer` and waits at most
`EXIT_FLUSH_SECONDS` at exit for its last counters. `BoundedTelemetry.emit` checks
the event (`sanitize_data`) and appends it to a bounded in-memory queue. It takes
no lock and does no I/O. A full queue drops the event. A daemon thread sends gzip
batches and backs off during an outage. The reply of the fleet service settles each
batch: the sender does not send rejected events again. It sends the events that
the service could not store yet again, at most `_MAX_RETRIES` times. Unless `report_process` is
false, the thread also reports `runtime` and `version` events at start, and
process resources (`utils/fleet_telemetry_resources.py`) and a delivery heartbeat
every five minutes.

**Hooks.** Application code emits events from these places:

- Query timing: `utils/fleet_query_telemetry.py:telemetry_chat` wraps
  `chat/process_message.py:handle_stream_message_objects` and
  `handle_multi_model_stream`. `telemetry_query` wraps
  `server/features/search/api.py:search` and
  `ee/onyx/search/process_search_query.py:stream_search_query`. A request that
  fails with a 4xx `OnyxError` sends no event. This includes a chat that a
  query-processing hook rejects (`QUERY_REJECTED`): the chat stream sends the
  error as a `StreamingError` packet, and `QueryObservation.error_packet` reads
  only its code.
- Indexing counters: the fetch, embed, and write steps call `emit_stage_counter`
  ([[indexing-pipeline]] §4.10). The sender thread sums the deltas for one
  attempt and stage over at most 30 seconds.
- Queue depths: `background/celery/tasks/monitoring/tasks.py:_report_queue_depths`,
  at most every ten minutes.
- OpenSearch health: `document_index/opensearch/resource_health.py:_report_to_fleet`,
  after each resource check.

**Collection.** `utils/fleet_telemetry_collector.py:collect_snapshots` runs every
five minutes for each tenant. It reads connectors, signup email domains, license
presence, index attempts, stage summaries, and background jobs through the
statement-limited queries in `db/fleet_telemetry.py`. It reads only the rows that
changed since its previous pass, plus work that is still running. Each read
returns the oldest changes first. When the sender refuses a row (a full queue or
a closed sender), the next pass resumes at that row. When a read reaches
`ROW_LIMIT`, the next pass resumes at the time of its last row, and always moves
forward (`_send_in_order`). The inventory (connectors, domains, license) goes out after
the work, when it changes and at least every six hours. Event IDs come from the
row identity and update time, so the fleet service drops repeated events. Index attempt and job state reach the fleet only from these
reads. The intervals are constants in `utils/fleet_telemetry.py`
(`COLLECTION_INTERVAL_SECONDS` and the others); the fleet service cannot change
them.

**Identity.** `utils/fleet_telemetry.py:deployment_key` returns the stored key
(`db/fleet_enrollment.py:get_or_create_deployment_key`). Under `MULTI_TENANT`, it
derives the key from `WEB_DOMAIN`, and each tenant reports as a separate customer
(`BoundedTelemetry._envelope`). The sender thread reads the key and enrolls at
`/v1/enroll` before its first batch (`BoundedTelemetry._enroll`), so startup never
waits for the database or the network.

**Other mechanisms.** `utils/telemetry.py` holds Cloud PostHog analytics
(`mt_cloud_telemetry`) and `get_or_generate_uuid`, the installation UUID that
`configs/sentry.py:_add_instance_tags` sends to Sentry. Neither is fleet telemetry.
`utils/timing.py:log_function_time` writes local logs only.

---

## 5. Contracts and invariants

1. **Every new LLM, embedding, rerank, image-generation, or voice call site
   needs an explicit `LLMFlow` tag** via `llm_generation_span` or
   `traced_llm_call`. `UNTAGGED_INVOKE` / `UNTAGGED_STREAM` in a dashboard
   means missing instrumentation at that call site, not a tracing bug.
2. **Masking must run before content leaves the process.** Any new external
   trace destination needs its own `mask_sensitive_data` wiring; adding a
   provider without it is a silent data-exposure regression (see §9).
3. **Incognito content must never reach an external trace backend.** Both
   `braintrust_tracing_processor.py` and `langfuse_tracing_processor.py` check
   `suppresses_external_traces()` before emitting; a new tracing processor
   must add the same check.
4. **`/metrics` must stay authenticated by default.** `metrics_auth.py:verify_metrics_token`
   fails closed: if neither `METRICS_AUTH_TOKEN` nor `DISABLE_METRICS_AUTH` is
   set, every request gets 401. Do not weaken this default.
5. **A new HTTP-scoped or connector-scoped metric needs a `tenant_id` label
   (or an explicit single-tenant-only decision) in a multi-tenant
   deployment**, or it silently aggregates across every customer on the
   shared cluster.
6. **Tracing admin config is unavailable under `MULTI_TENANT`.**
   `_reject_if_multi_tenant` blocks every `/admin/tracing/*` route; cloud
   configuration is env-var only.
7. **Metric label cardinality stays bounded.** Never label with a raw
   user/document ID or a free-form connector name on a per-task counter
   (`docs/METRICS.md` "Cardinality warning"); use IDs/enums, or move the field
   to a pull-based collector where cardinality is naturally bounded.
8. **The audit `action` taxonomy is append-only.** Consumers filter on
   specific `action` strings; renaming or removing one breaks every existing
   SIEM rule (`docs/AUDIT_LOGGING.md`).
9. **At most one non-deleted hook exists per `HookPoint`**, enforced by
   `db/hook.py:create_hook__no_commit` and a DB partial unique index.
10. **A `HookFailStrategy.HARD` hook failure must abort the calling
    pipeline; `SOFT` must fall back to default behavior**, never silently
    succeed with no data.
11. **Fleet telemetry never blocks or fails the caller.** `BoundedTelemetry.emit`
    takes no lock and does no I/O, and `utils/fleet_telemetry.py:emit_telemetry`
    catches every exception. A new hook must not read the database or call the
    network on an application or indexing thread; the collector does all source
    reads.
12. **Only allowlisted fields leave the process.** `sanitize_data` drops an event
    that has an unknown key, or a value that is not a number, a boolean, or one
    short token. A new key needs an entry in `utils/fleet_telemetry.py:_FIELDS`.
    Never send names, email addresses, URLs, paths, document content, or raw
    error text.

---

## 6. Relationships

**Depends on**
- [[llm-providers]]: `LitellmLLM.invoke`/`stream` (`multi_llm.py`), which open
  the generation span and fall back to the untagged flows, and the cost computation
  (`llm/cost.py:compute_cost_cents`) that usage accounting calls.
- [[multi-tenancy]]: `MULTI_TENANT` gates tracing admin config, per-tenant
  metric labelling, and connector-state metric collection.
- [[editions-and-gating]]: hooks, usage export/reporting, log export, and
  query history are EE-only.
- [[chat-persistence]]: incognito's persistence contract (`persist_content`)
  is the sibling of the incognito tracing suppression described here.
- [[background-jobs]]: the usage-report Celery task, the log-export Celery
  collector, and per-worker Celery signal handlers that emit task metrics.
  `app_base.py:on_worker_ready` starts each worker's fleet sender. The
  `monitoring` worker runs `collect_fleet_telemetry` and reports Celery queue
  depths; the collection pass reads `SyncRecord` rows.
- [[rate-and-usage-limits]]: `TenantUsage` and `db/usage.py:check_usage_limit`
  are the cloud usage-limit ledger this component also touches.
- [[indexing-pipeline]], [[cc-pairs-and-credentials]], [[permission-sync]],
  [[auth-and-identity]], [[billing]]: the fleet collection pass reads their
  tables (`db/fleet_telemetry.py`). A column change there can break the pass and
  fail no application test (§7).
- [[document-index]]: `opensearch/resource_health.py:refresh_resource_health`
  reports cluster health to the fleet sender.

**Depended on by**
- [[core-chat-loop]]: every chat turn opens tagged generation spans and
  produces usage records through this component.
- [[indexing-pipeline]]: contextual RAG summarization and connector-state
  metrics are emitted from here. Its fetch, prepare, embed, and write steps send
  fleet stage counters through `emit_stage_counter`.
- [[slack-bot]]: `listener.py` starts the fleet sender that Slack answers use
  for query events.
- [[llm-providers]]: cost tracking and the tracing admin endpoints live in
  this component even though `llm-providers.md` documents the LLM-side
  factory that calls into them.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds an LLM call site | Tag it with an `LLMFlow` (add the enum value first); verify no new `UNTAGGED_*` span appears (§8) |
| adds a Prometheus metric | `docs/METRICS.md` reference tables; label cardinality; a `tenant_id` label if the metric is HTTP- or connector-scoped and multi-tenant applies; a unit test under `backend/tests/unit/server/metrics/` or `backend/tests/unit/onyx/server/metrics/` |
| changes masking (`tracing/masking.py`) | Both Braintrust and Langfuse paths; confirm the redaction still fires before `braintrust.set_masking_function` / any equivalent Langfuse hook is added |
| changes a trace processor (`braintrust_tracing_processor.py`, `langfuse_tracing_processor.py`, or a new one) | The incognito check (`suppresses_external_traces`) must still gate it; `dynamic_processor.py`'s delegate rebuild and drain-on-retire logic |
| adds a usage-recorded action (a new `LLMFlow`, a new system attribution) | `tracing/flows.py:SYSTEM_TEXT_GENERATION_FLOWS` if it should count as system usage; `processors/user_usage_processor.py:_system_attribution`; the usage export/report pipeline that reads `UserUsage` |
| adds a new `HookPoint` | `hooks/registry.py:_REGISTRY` (validated at startup by `validate_registry`); a new `HookPointSpec`; the EE UI's hook-point catalogue |
| changes the audit action taxonomy | `docs/AUDIT_LOGGING.md`; every downstream SIEM filter rule depends on the exact string |
| adds a fleet telemetry field or hook | the allow-lists that `sanitize_data` uses (§5 item 12); no lock or I/O on the calling thread (§5 item 11); the fleet service's ingestion contract, which lives in a separate repository (`deployment/fleet-telemetry.md`) |
| renames or drops a table or column that the fleet collection pass reads | the queries in `db/fleet_telemetry.py` and `backend/tests/external_dependency_unit/telemetry/test_fleet_collector.py`. A broken query fails no application path: the pass only counts the error in the heartbeat. |

---

## 8. How to verify a change

### Confirming a new call site is tagged

1. Connect Braintrust or Langfuse (`PUT`/`POST /admin/tracing/providers`, or
   set `BRAINTRUST_*`/`LANGFUSE_*` env vars) and confirm it shows in
   `GET /admin/tracing/providers`.
2. Exercise the new call site.
3. In the tracing dashboard, confirm the span's `model_config.flow` is the new
   `LLMFlow` value, not `untagged_invoke` / `untagged_stream`.

### Scraping `/metrics` locally

```bash
curl -H "Authorization: Bearer $METRICS_AUTH_TOKEN" http://localhost:8080/metrics
```

Without a token configured, expect a 401 unless `DISABLE_METRICS_AUTH=true` is
set. Celery worker metrics have no auth; scrape the worker's own port
(e.g. `curl http://localhost:9093/metrics` for docprocessing).

### Tests

```bash
# Metrics
cd backend && uv run pytest -xv tests/unit/server/metrics tests/unit/onyx/server/metrics
cd backend && uv run pytest -xv tests/external_dependency_unit/db/test_index_attempt_stage_metrics.py

# Tracing
cd backend && uv run pytest -xv tests/unit/onyx/tracing tests/unit/onyx/llm/test_client_tracing.py
uv run --env-file .vscode/.env pytest -xv backend/tests/external_dependency_unit/tracing

# Hooks
cd backend && uv run pytest -k hook tests/unit tests/external_dependency_unit

# Fleet telemetry
cd backend && uv run pytest -xv tests/unit/onyx/utils/test_fleet_*.py \
  tests/unit/onyx/chat/test_stream_chat_telemetry.py
uv run --env-file .vscode/.env pytest -xv backend/tests/external_dependency_unit/telemetry
```

Notable existing tests: `tests/unit/onyx/tracing/test_flows_registry.py`,
`test_dynamic_processor.py`, `test_braintrust_incognito_suppression.py`,
`test_langfuse_incognito_suppression.py`, `test_metadata_only_tracing.py`,
`test_user_usage_processor.py`, and
`tests/external_dependency_unit/tracing/test_tracing_admin_api.py`,
`test_tracing_provider_config.py`, `test_llm_span_recording.py`.

See `backend/AGENTS.md` for authoritative commands and required env.

### What "working" looks like

- No unexpected `UNTAGGED_INVOKE`/`UNTAGGED_STREAM` spans from the code path
  you touched.
- `/metrics` returns 401 with no token, and the expected series with a valid
  one.
- A trace produced under incognito never appears in Braintrust/Langfuse, but
  its tokens still land in `UserUsage` with `incognito=true`.
- A `HARD` hook failure aborts the pipeline; a `SOFT` failure logs and the
  pipeline continues with default behavior.

---

## 9. Footguns

- **`UNTAGGED_INVOKE` / `UNTAGGED_STREAM` in a dashboard means missing
  instrumentation**, not a tracing bug. Add an explicit
  `llm_generation_span`/`traced_llm_call` at the call site.
- **`/metrics` is locked by default.** If neither `METRICS_AUTH_TOKEN` nor
  `DISABLE_METRICS_AUTH=true` is set, every scrape gets 401. This surprises
  people setting up a fresh deployment; it is intentional
  (`metrics_auth.py`: "fail secure").
- **Cloud (`MULTI_TENANT`) is env-only for tracing.** The tracing admin
  endpoints are rejected outright, and `resolve_effective_tracing_config`
  never reads the DB, so there is no way to configure Braintrust/Langfuse
  per-tenant on cloud today.
- **Masking is Braintrust-specific today.** `mask_sensitive_data` is wired
  through `braintrust.set_masking_function`; `langfuse_tracing_processor.py`
  has no equivalent call, so a Langfuse-only deployment does not get the same
  redaction pass before data leaves the process.
- **Incognito suppression and incognito usage accounting are different
  guarantees.** External traces are dropped entirely for an incognito turn;
  its token/cost usage is still recorded in `UserUsage`, just labeled
  `incognito=true`. Do not assume "incognito" means "invisible everywhere."
- **Audit logging has no DB table or read API yet.** The only supported
  consumption path is an external log shipper on the `onyx.audit` logger
  prefix (`docs/AUDIT_LOGGING.md` "Roadmap").
- **`UserUsage` and `TenantUsage` are unrelated tables that both mean
  "usage."** `UserUsage` is per-actor LLM cost/token accounting;
  `TenantUsage` is the cloud usage-limit ledger checked by
  `db/usage.py:check_usage_limit`. Writing to one does not affect the other.
- **A hook's `is_reachable` update and its failure log are written in
  separate sessions on purpose**, so a concurrent hook deletion (which makes
  the `is_reachable` write raise `NOT_FOUND`) cannot suppress the failure log.
- **`utils/telemetry.py` is not fleet telemetry.** It holds the Cloud PostHog
  analytics calls (`mt_cloud_telemetry`, `mt_cloud_identify_user`), which run only
  under `MULTI_TENANT`. `DISABLE_TELEMETRY` does not affect them.
- **`telemetry_chat` reads the channel from a keyword argument.** It reads
  `new_msg_req` from the call's keywords (`utils/fleet_query_telemetry.py:_channel`).
  If a caller passes it by position, the query event reports the channel `web`.
  Nothing fails.
- **Discord queries report the channel `api`.** The send-message endpoint sets
  the origin to `api` for an API key or PAT caller
  (`server/query_and_chat/chat_backend.py:handle_send_chat_message`), and the
  Discord bot calls it with an API key.

---

Related: [[llm-providers]], [[multi-tenancy]], [[editions-and-gating]],
[[background-jobs]], [[chat-persistence]], [[rate-and-usage-limits]],
[[core-chat-loop]], [[indexing-pipeline]].
