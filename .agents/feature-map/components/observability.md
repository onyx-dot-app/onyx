# Observability

> How operators and admins watch Onyx: Prometheus metrics, LLM tracing to
> Braintrust or Langfuse, the per-user usage and cost ledger, the audit log
> stream, the support log export and query history.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE for metrics, tracing, usage accounting and audit logging. EE
for the usage report, log export, query history and workspace analytics.

---

## User experience

- **An operator** scrapes `/metrics` on the API server and the MCP server with
  a bearer token, and each Celery worker type that has a metrics port on that
  port. A new deployment returns 401 until the operator sets a token or turns
  auth off on purpose. The customer reference is
  `documentation/deployment/production/monitoring.mdx`.
- **A self-hosted admin** connects Braintrust or Langfuse at Admin > Tracing.
  Each LLM call then shows as a trace with model and tokens. A call in full
  content mode, such as a chat turn, also shows the prompt and response, with
  secrets masked. Indexing calls, such as contextual RAG and image
  summarization, use `TraceContentMode.METADATA_ONLY` and show no content. An incognito turn never shows. On cloud, env vars set
  tracing, and the admin page refuses changes.
- **A user** sees their own token and cost usage, and their budget, in
  Settings > Usage. **An admin** sees usage per user and for system work such
  as contextual RAG, resets a user's usage, and sets per-model prices. On EE,
  an admin downloads a usage report ZIP with CSVs and a PDF.
- **A security team** reads audit events (logins, permission changes,
  credential access, denied scoped writes) as JSON lines on the `onyx.audit`
  logger and ships them to a SIEM. Onyx has no page or API to read them
  (schema: `documentation/admins/auditing/audit_logs.mdx`).
- **A self-hosted EE admin** downloads a log export bundle for support: log
  files from one replica of each worker type and, when enabled on Kubernetes,
  the stdout and events of every pod. A second start during an export gets a
  429.
- **An EE admin with query-history permission** reads and exports chat
  sessions. The `query_history_type` setting can hide user emails or turn the
  feature off.
- **An EE admin** sees workspace analytics: query, active-user, Slack bot and
  per-agent counts. A user with agent-analytics permission sees the stats of
  an agent.

When a call site opens no root trace, nothing fails for the user. The call
has no trace, and its usage does not count toward token budgets
([[#root-trace-required]]).

---

## Scope

This component holds the metrics endpoints and worker metric servers, the
tracing framework and its processors, the tracing admin settings, the
`user_usage` ledger and its API, the audit emitter, the EE usage report, the
log export, query history and the EE workspace analytics.

Neighbours own:
- [[rate-and-usage-limits]]: budgets that read the `user_usage` ledger, and
  the cloud `tenant_usage` counters. Both tables say "usage". They are
  unrelated: this component writes `user_usage`, and limits own `tenant_usage`.
- [[fleet-telemetry]]: events sent to the Onyx fleet service. Cloud PostHog
  product analytics (`mt_cloud_telemetry`) stay with this component. They
  run only under `MULTI_TENANT`.
- [[hooks]]: customer HTTPS endpoints that Onyx calls in the pipeline.
- [[llm-providers]]: `LitellmLLM` and the price table.
- [[chat-persistence]]: what an incognito turn stores in Postgres.

---

## Architecture

```
LLM call ──> generation span ──> DynamicTracingProcessor ──> Braintrust / Langfuse
  (inside a root trace)      │      (rebuilt from DB or env on a TTL)   (mask, drop incognito)
                             └──> UserUsageTracingProcessor ──> user_usage (batched)
                                                                   │
                       budgets ([[rate-and-usage-limits]]) <───────┤
                       /user/usage, /admin/usage, usage report <───┘
```

**Tracing.** `tracing/setup.py:setup_tracing` registers one
`tracing/dynamic_processor.py:DynamicTracingProcessor`. On a short TTL it calls
`tracing/provider_config.py:resolve_effective_tracing_config` and rebuilds the
Braintrust and Langfuse delegates when the config changes. Each trace keeps
the delegate set it started with, so an admin change does not split a trace in
flight. A DB row wins over env vars for each provider. A disabled row turns
that provider off even when its env vars are set. Under `MULTI_TENANT` the
DB is never read, and `server/manage/tracing/api.py:_reject_if_multi_tenant`
refuses every `/admin/tracing` route. When `USER_USAGE_TRACKING_ENABLED` is
on, `setup_tracing` also adds
`tracing/processors/user_usage_processor.py:UserUsageTracingProcessor`, apart
from Braintrust and Langfuse.

**Root traces.** `tracing/framework/create.py:trace` and `ensure_trace` open
the root. Use `ChatTraceMetadata` when a chat session exists and
`SearchTraceMetadata` when none does.

**Spans.** `LitellmLLM.invoke` and `stream` open their own generation span,
tagged with the `LLMFlow` (`tracing/flows.py`) in `GenerationContext.flow`.
With no flow set, they tag `UNTAGGED_INVOKE` or `UNTAGGED_STREAM`.
`invoke_raw` and `stream_raw` open no span. Two helpers in
`tracing/llm_utils.py` open a span for other callers.
`llm_generation_span` is for a raw-layer call through an `LLM` object, such as
the gateway's. `traced_llm_call` is for a direct SDK call or a call to the
model server, such as image generation, voice, embedding and rerank. A span in
`TraceContentMode.METADATA_ONLY` records tokens and model but no prompt or
response. Indexing work, such as contextual RAG, uses it.

**Usage and cost.** `UserUsageTracingProcessor` takes each generation span with
token usage, and each image generation span. It prices the span with `llm/cost.py:compute_cost_cents`, and upserts additive
rows in `user_usage` from a background drain thread. A span with
`routed_model` set (a router such as `openrouter/auto`) is priced by the served
model, and the row keeps the router name. A call with no user in the request
context writes a system row. If its flow is in
`tracing/flows.py:SYSTEM_TEXT_GENERATION_FLOWS`, the row is `ATTRIBUTED` and
the admin system view shows it under that flow. Otherwise it is `UNATTRIBUTED`
(`tracing/processors/user_usage_processor.py:_system_attribution`). An admin
price override applies per model configuration (`db/cost_override.py`). A call
outside `LLM` gets it only when it passes `model_configuration_id` to
`traced_llm_call`.

**Metrics.** `backend/onyx/server/metrics/README.md` explains how each process
serves metrics and how to add one. Workers start an unauthenticated server
from `server/metrics/metrics_server.py:start_metrics_server`. Task lifecycle
metrics come from `server/metrics/celery_task_metrics.py`, called from each
worker app's own signal handlers. The monitoring worker serves metrics but does
not wire these handlers.

**Audit.** `utils/audit.py:emit_audit_event` writes one JSON line to the child
logger `onyx.audit.<ocsf_class>`. The module owns its stdout handler, set at
import, because root-logger propagation drops the events under uvicorn.
High-volume actions pass a `dedup_key`, which a Redis `SET NX` checks.

**Log export.** `ee/onyx/server/log_export/api.py:start_log_export` sends a
collect task to the queue of each worker type, collects its own logs inline,
and starts the Kubernetes collection in a thread. Each piece has 90 s.

---

## Contracts and traps

1. `root-trace-required` **Every entry point that runs LLM work must open a
   root trace first.** A span with no trace in scope becomes a `NoOpSpan`
   (`tracing/framework/provider.py:create_span`) and reaches no processor. The
   call then has no trace and writes no `user_usage` row, so token and cost
   budgets do not count it. A new Celery task or endpoint that calls an LLM
   must wrap its work in `tracing/framework/create.py:trace` or
   `tracing/framework/create.py:ensure_trace`.
2. `tag-llm-flow` **Tag each new LLM, embedding, rerank, image or voice call
   with an `LLMFlow`.** Set `GenerationContext.flow` on `invoke` or `stream`,
   or use `tracing/llm_utils.py:llm_generation_span` or
   `tracing/llm_utils.py:traced_llm_call`. Add the enum value first. `UNTAGGED_*` in a dashboard means a call site with no
   flow, not a tracing bug. A direct `invoke_raw` or `stream_raw` caller
   opens no span at all and needs one of the helpers.
3. `external-processor-mask-and-drop-incognito` **Each external trace
   processor must mask and must drop incognito traces.** Braintrust masks
   through `tracing/dynamic_processor.py:_build_braintrust_processor`, which
   calls `braintrust.set_masking_function`. Langfuse masks in
   `tracing/langfuse_tracing_processor.py:LangfuseTracingProcessor._mask_if_enabled`,
   on by default. Both call
   `tracing/incognito.py:suppresses_external_traces` at trace start and drop
   the whole trace. A new destination must do both.
4. `incognito-counted-in-usage` **Incognito is dropped from traces but counted
   in usage.**
   `tracing/processors/user_usage_processor.py:UserUsageTracingProcessor._capture`
   records an incognito span
   with `incognito=True`. Budgets and the usage report still see it. Do not
   make the usage processor honour the incognito check.
5. `metrics-fail-closed` **`/metrics` fails closed.**
   `server/metrics/metrics_auth.py:verify_metrics_token` returns 401 to every
   request when neither `METRICS_AUTH_TOKEN` nor `DISABLE_METRICS_AUTH` is
   set. Do not change this default. Worker metric ports have no auth. Keep them
   inside the cluster network.
6. `metric-tenant-and-cardinality` **A metric must not mix tenants, grow labels
   without bound, or hang the scrape.** An HTTP-scoped or connector-scoped
   metric needs a `tenant_id` label or a single-tenant guard
   (`server/metrics/per_tenant.py`, `server/metrics/connector_state_metrics.py`).
   Never label a per-task series with a user string such as a connector name.
   A scrape-time collector must bound its read
   (`server/metrics/indexing_pipeline.py:_CachedCollector`). The metrics README
   gives the detail.
7. `audit-actions-append-only` **The audit `utils/audit.py:AuditAction`
   values are append-only.** SIEM rules match the exact string. Moving an action to
   another OCSF class changes its logger name, which also breaks a shipper
   filter. Update `audit_logs.mdx` with any schema change.
8. `audit-never-raises` **Audit emission never raises and never logs a
   secret.** `utils/audit.py:emit_audit_event` catches every exception, and dedup emits when
   Redis is down. Do not put a secret in `extra`.
   `auth/scoped_permissions.py:_emit_denial` passes no dedup key, so each
   denied attempt emits its own event.
9. `log-export-lock-per-process` **The log export lock is per process.**
   `ee/onyx/server/log_export/api.py:_ASYNC_EXPORT_LOCK` is in memory. With
   more than one API server replica, two exports can run at once. A worker
   with no free thread misses the 90 s deadline, and its piece is missing.
10. `log-export-k8s-rbac` **Kubernetes log collection needs the Helm RBAC.**
    It runs only when `LOG_EXPORT_KUBERNETES_ENABLED` is true (default false)
    inside Kubernetes. The chart value `logExport.kubernetes.enabled` binds the
    Role in `deployment/helm/charts/onyx/templates/log-export-rbac.yaml` to the
    API server's own service account, which the chart creates. If the API
    server uses IRSA or Workload Identity, that new service account name must
    be in the IAM trust policy. Without access, only that piece fails.
11. `usage-report-same-rows` **The usage CSVs and the PDF of the usage report
    read the same rows.**
    `ee/onyx/server/reporting/usage_export_generation.py:create_new_usage_report`
    queries the user and system usage rows once and passes them to the usage
    CSV writers and to
    `ee/onyx/server/reporting/usage_report_data.py:build_usage_report_data` for
    the PDF, so the totals agree. A new output must take those rows, not query
    again. A failed PDF render is logged, and the ZIP ships without it.
12. `redact-span-errors` **Redact a span error first.**
    `llm/multi_llm.py:LitellmLLM.invoke` and `stream` pass the error through
    `redact_error` before `span.set_error`, so no provider credential reaches a
    trace backend. Do the same in a new span.

---

## Decisions

- **Tracing config on cloud is env-only.** `DynamicTracingProcessor` holds
  one delegate set for the process, which serves every tenant on cloud. A
  config saved by one tenant would receive the prompts of every tenant.
- **Usage is read from tracing spans, not counted at each call site.** One
  processor sees every priced LLM call. The cost is the dependency in
  [[#root-trace-required]] and a short write lag, which
  [[rate-and-usage-limits]] describes.

---

## Known issues

- **The request latency log does not measure a stream.**
  `server/middleware/latency_logging.py:latency_logging_middleware` logs the
  time to `http.response.start`, before the body. For a streamed chat response
  it records the time to the first byte, not the length of the stream. It must
  stay pure ASGI ([[streaming-protocol#pure-asgi-middleware]]).

---

## Dependencies

- [[llm-providers]]: `LitellmLLM` opens spans, and `llm/cost.py` prices them.
- [[multi-tenancy]]: `MULTI_TENANT` gates tracing config, log export and metric collection; the tenant contextvar labels metrics and usage rows.
- [[editions-and-gating]]: the usage report, log export and query history mount only in the EE app.
- [[background-jobs]]: the worker apps wire task metrics, and the log export fans out to their queues.

---

## Recipes

- `add-metric` **Add a metric.** Follow `backend/onyx/server/metrics/README.md`. Copy
  `server/metrics/slow_requests.py` for an API-server metric, or
  `server/metrics/per_tenant.py` for a tenant-labelled one. List the current
  families with `git ls-files backend/onyx/server/metrics/`. Then add the
  family to `documentation/deployment/production/monitoring.mdx`, and a panel
  in `deployment/helm/charts/onyx/dashboards/` if it needs one.
- `add-llm-call-site` **Add an LLM call site.** Add an `LLMFlow` value. Copy how
  `secondary_llm_flows/chat_session_naming.py:generate_chat_session_name` sets
  `GenerationContext.flow` on `llm.invoke`, or how `image_gen/providers/openai_img_gen.py` uses `traced_llm_call`
  for a direct SDK call. List the call sites with
  `git grep -lE "flow=LLMFlow|traced_llm_call|llm_generation_span" backend`. Open the span
  inside a root trace ([[#root-trace-required]], [[#tag-llm-flow]]). If no
  user starts the call, add the flow to `SYSTEM_TEXT_GENERATION_FLOWS`. A raw-layer caller owns its span
  ([[llm-providers#raw-caller-owns-span]]). The gateway rules are
  [[llm-gateway#generating-path-opens-span]] and
  [[llm-gateway#trace-inside-stream-worker]].
- `add-trace-destination` **Add a trace destination.** Copy `tracing/langfuse_tracing_processor.py`.
  Add a builder to `tracing/dynamic_processor.py:build_delegates`, a row parser
  to `tracing/provider_config.py`, and the checks in
  [[#external-processor-mask-and-drop-incognito]].
- `add-audit-action` **Add an audit action.** Append to `utils/audit.py:AuditAction`, map it to an
  OCSF class in `utils/audit.py:_OCSF_CLASS_BY_ACTION`, and document it in
  `audit_logs.mdx`. The module raises at import when an action has no class. Copy the
  `PERMISSION_DENIED` emit in `auth/scoped_permissions.py:_emit_denial`. List
  the emit sites with `git grep -l emit_audit_event backend`.
- `investigate-missing-usage` **Investigate a call that is missing from usage
  or shows as `untagged_*`.**
  Find the entry points that open a root trace with
  `git grep -lE "(^|[^_a-z])(ensure_)?trace\(" -- backend/onyx backend/ee ':!backend/onyx/tracing'`.
  If the caller is not under one, the span is a `NoOpSpan`
  ([[#root-trace-required]]). If the flow is `untagged_*`, the call site sets
  no `LLMFlow` ([[#tag-llm-flow]]). If the call uses `invoke_raw` or
  `stream_raw`, it opens no span.

---

## Verification

- Tracing: `backend/tests/unit/onyx/tracing/` and
  `backend/tests/external_dependency_unit/tracing/`.
- Metrics: `backend/tests/unit/onyx/server/metrics/` and
  `backend/tests/unit/server/metrics/`.
- Log export: `backend/tests/unit/ee/onyx/server/log_export/`,
  `backend/tests/integration/tests/log_export/` and the Helm render tests in
  `backend/tests/external_dependency_unit/craft_helm/`.
- By hand: connect Langfuse and run the call site. The flow is not
  `untagged_*`. An incognito chat makes no trace but an `incognito` usage row.
