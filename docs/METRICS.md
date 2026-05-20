# Onyx Prometheus Metrics Reference

## Adding New Metrics

All Prometheus metrics live in the `backend/onyx/server/metrics/` package. Follow these steps to add a new metric.

### 1. Choose the right file (or create a new one)

| File                                  | Purpose                                      |
| ------------------------------------- | -------------------------------------------- |
| `metrics/slow_requests.py`            | Slow request counter + callback              |
| `metrics/postgres_connection_pool.py` | SQLAlchemy connection pool metrics           |
| `metrics/prometheus_setup.py`         | FastAPI instrumentator config (orchestrator) |

If your metric is a standalone concern (e.g. cache hit rates, queue depths), create a new file under `metrics/` and keep one metric concept per file.

### 2. Define the metric

Use `prometheus_client` types directly at module level:

```python
# metrics/my_metric.py
from prometheus_client import Counter

_my_counter = Counter(
    "onyx_my_counter_total",          # Always prefix with onyx_
    "Human-readable description",
    ["label_a", "label_b"],           # Keep label cardinality low
)
```

**Naming conventions:**

- Prefix all metric names with `onyx_`
- Counters: `_total` suffix (e.g. `onyx_api_slow_requests_total`)
- Histograms: `_seconds` or `_bytes` suffix for durations/sizes
- Gauges: no special suffix

**Label cardinality:** Avoid high-cardinality labels (raw user IDs, UUIDs, raw paths). Use route templates like `/api/items/{item_id}` instead of `/api/items/abc-123`.

### 3. Wire it into the instrumentator (if request-scoped)

If your metric needs to run on every HTTP request, write a callback and register it in `prometheus_setup.py`:

```python
# metrics/my_metric.py
from prometheus_fastapi_instrumentator.metrics import Info

def my_metric_callback(info: Info) -> None:
    _my_counter.labels(label_a=info.method, label_b=info.modified_handler).inc()
```

```python
# metrics/prometheus_setup.py
from onyx.server.metrics.my_metric import my_metric_callback

# Inside setup_prometheus_metrics():
instrumentator.add(my_metric_callback)
```

### 4. Wire it into setup_prometheus_metrics (if infrastructure-scoped)

For metrics that attach to engines, pools, or background systems, add a setup function and call it from `setup_prometheus_metrics()` in `metrics/prometheus_setup.py`:

```python
# metrics/my_metric.py
def setup_my_metrics(resource: SomeResource) -> None:
    # Register collectors, attach event listeners, etc.
    ...
```

```python
# metrics/prometheus_setup.py — inside setup_prometheus_metrics()
from onyx.server.metrics.my_metric import setup_my_metrics

def setup_prometheus_metrics(app, engines=None) -> None:
    setup_my_metrics(resource)  # Add your call here
    ...
```

All metrics initialization is funneled through the single `setup_prometheus_metrics()` call in `onyx/main.py:lifespan()`. Do not add separate setup calls to `main.py`.

### 5. Write tests

Add tests in `backend/tests/unit/onyx/server/`. Use `unittest.mock.patch` to mock the prometheus objects — don't increment real global counters in tests.

### 6. Document the metric

Add your metric to the reference tables below in this file. Include the metric name, type, labels, and description.

### 7. Update Grafana dashboards

After deploying, add panels to the relevant Grafana dashboard:

1. Open Grafana and navigate to the Onyx dashboard (or create a new one)
2. Add a new panel — choose the appropriate visualization:
   - **Counters** → use `rate()` in a time series panel (e.g. `rate(onyx_my_counter_total[5m])`)
   - **Histograms** → use `histogram_quantile()` for percentiles, or `_sum/_count` for averages
   - **Gauges** → display directly as a stat or gauge panel
3. Add meaningful thresholds and alerts where appropriate
4. Group related panels into rows (e.g. "API Performance", "Database Pool")

---

## API Server Metrics

These metrics are exposed at `GET /metrics` on the API server.

### Built-in (via `prometheus-fastapi-instrumentator`)

| Metric                                | Type      | Labels                        | Description                                       |
| ------------------------------------- | --------- | ----------------------------- | ------------------------------------------------- |
| `http_requests_total`                 | Counter   | `method`, `status`, `handler` | Total request count                               |
| `http_request_duration_highr_seconds` | Histogram | _(none)_                      | High-resolution latency (many buckets, no labels) |
| `http_request_duration_seconds`       | Histogram | `method`, `handler`           | Latency by handler (custom buckets for P95/P99)   |
| `http_request_size_bytes`             | Summary   | `handler`                     | Incoming request content length                   |
| `http_response_size_bytes`            | Summary   | `handler`                     | Outgoing response content length                  |
| `http_requests_inprogress`            | Gauge     | `method`, `handler`           | Currently in-flight requests                      |

### Custom (via `onyx.server.metrics`)

| Metric                         | Type    | Labels                        | Description                                                      |
| ------------------------------ | ------- | ----------------------------- | ---------------------------------------------------------------- |
| `onyx_api_slow_requests_total` | Counter | `method`, `handler`, `status` | Requests exceeding `SLOW_REQUEST_THRESHOLD_SECONDS` (default 1s) |

### Configuration

| Env Var                          | Default | Description                                  |
| -------------------------------- | ------- | -------------------------------------------- |
| `SLOW_REQUEST_THRESHOLD_SECONDS` | `1.0`   | Duration threshold for slow request counting |

### Instrumentator Settings

- `should_group_status_codes=False` — Reports exact HTTP status codes (e.g. 401, 403, 500)
- `should_instrument_requests_inprogress=True` — Enables the in-progress request gauge
- `inprogress_labels=True` — Breaks down in-progress gauge by `method` and `handler`
- `excluded_handlers=["/health", "/metrics", "/openapi.json"]` — Excludes noisy endpoints from metrics

## Database Pool Metrics

These metrics provide visibility into SQLAlchemy connection pool state across all three engines (`sync`, `async`, `readonly`). Collected via `onyx.server.metrics.postgres_connection_pool`.

### Pool State (via custom Prometheus collector — snapshot on each scrape)

| Metric                     | Type  | Labels   | Description                                     |
| -------------------------- | ----- | -------- | ----------------------------------------------- |
| `onyx_db_pool_checked_out` | Gauge | `engine` | Currently checked-out connections               |
| `onyx_db_pool_checked_in`  | Gauge | `engine` | Idle connections available in the pool          |
| `onyx_db_pool_overflow`    | Gauge | `engine` | Current overflow connections beyond `pool_size` |
| `onyx_db_pool_size`        | Gauge | `engine` | Configured pool size (constant)                 |

### Pool Lifecycle (via SQLAlchemy pool event listeners)

| Metric                                   | Type    | Labels   | Description                              |
| ---------------------------------------- | ------- | -------- | ---------------------------------------- |
| `onyx_db_pool_checkout_total`            | Counter | `engine` | Total connection checkouts from the pool |
| `onyx_db_pool_checkin_total`             | Counter | `engine` | Total connection checkins to the pool    |
| `onyx_db_pool_connections_created_total` | Counter | `engine` | Total new database connections created   |
| `onyx_db_pool_invalidations_total`       | Counter | `engine` | Total connection invalidations           |
| `onyx_db_pool_checkout_timeout_total`    | Counter | `engine` | Total connection checkout timeouts       |

### Per-Endpoint Attribution (via pool events + endpoint context middleware)

| Metric                                 | Type      | Labels              | Description                                     |
| -------------------------------------- | --------- | ------------------- | ----------------------------------------------- |
| `onyx_db_connections_held_by_endpoint` | Gauge     | `handler`, `engine` | DB connections currently held, by endpoint      |
| `onyx_db_connection_hold_seconds`      | Histogram | `handler`, `engine` | Duration a DB connection is held by an endpoint |

Engine label values: `sync` (main read-write), `async` (async sessions), `readonly` (read-only user).

Connections from background tasks (Celery) or boot-time warmup appear as `handler="unknown"`.

## Celery Worker Metrics

Celery workers expose metrics via a standalone Prometheus HTTP server (separate from the API server's `/metrics` endpoint). Each worker type runs its own server on a dedicated port.

### Metrics Server (`onyx.server.metrics.metrics_server`)

| Env Var                      | Default             | Description                                           |
| ---------------------------- | ------------------- | ----------------------------------------------------- |
| `PROMETHEUS_METRICS_PORT`    | _(per worker type)_ | Override the default port for this worker             |
| `PROMETHEUS_METRICS_ENABLED` | `true`              | Set to `false` to disable the metrics server entirely |

Default ports:

| Worker          | Port |
| --------------- | ---- |
| `docfetching`   | 9092 |
| `docprocessing` | 9093 |
| `monitoring`    | 9096 |

Workers without a default port and no `PROMETHEUS_METRICS_PORT` env var will skip starting the server.

### Generic Task Lifecycle Metrics (`onyx.server.metrics.celery_task_metrics`)

Push-based metrics that fire on Celery signals for all tasks on the worker.

| Metric                              | Type      | Labels                          | Description                                                                   |
| ----------------------------------- | --------- | ------------------------------- | ----------------------------------------------------------------------------- |
| `onyx_celery_task_started_total`    | Counter   | `task_name`, `queue`            | Total tasks started                                                           |
| `onyx_celery_task_completed_total`  | Counter   | `task_name`, `queue`, `outcome` | Total tasks completed (`outcome`: `success` or `failure`)                     |
| `onyx_celery_task_duration_seconds` | Histogram | `task_name`, `queue`            | Task execution duration. Buckets: 1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600 |
| `onyx_celery_tasks_active`          | Gauge     | `task_name`, `queue`            | Currently executing tasks                                                     |
| `onyx_celery_task_retried_total`    | Counter   | `task_name`, `queue`            | Total task retries                                                            |
| `onyx_celery_task_revoked_total`    | Counter   | `task_name`                     | Total tasks revoked (cancelled)                                               |
| `onyx_celery_task_rejected_total`   | Counter   | `task_name`                     | Total tasks rejected by worker                                                |

Stale start-time entries (tasks killed via SIGTERM/OOM where `task_postrun` never fires) are evicted after 1 hour.

### Per-Connector Indexing Metrics (`onyx.server.metrics.indexing_task_metrics`)

Enriches docfetching and docprocessing tasks with connector-level labels. Silently no-ops for all other tasks.

| Metric                                | Type      | Labels                                                      | Description                              |
| ------------------------------------- | --------- | ----------------------------------------------------------- | ---------------------------------------- |
| `onyx_indexing_task_started_total`    | Counter   | `task_name`, `source`, `tenant_id`, `cc_pair_id`            | Indexing tasks started per connector     |
| `onyx_indexing_task_completed_total`  | Counter   | `task_name`, `source`, `tenant_id`, `cc_pair_id`, `outcome` | Indexing tasks completed per connector   |
| `onyx_indexing_task_duration_seconds` | Histogram | `task_name`, `source`, `tenant_id`                          | Indexing task duration by connector type |

`connector_name` is intentionally excluded from these per-task counters to avoid unbounded cardinality (it's a free-form user string).

### Connector Health Metrics (`onyx.server.metrics.connector_health_metrics`)

Push-based metrics emitted by docfetching and docprocessing workers at the point where connector state changes occur. Scales to any number of tenants (no schema iteration). Unlike the per-task counters above, these include `connector_name` because their cardinality is bounded by the number of connectors (one series per connector), not by the number of task executions.

| Metric                                          | Type    | Labels                                                          | Description                                                   |
| ----------------------------------------------- | ------- | --------------------------------------------------------------- | ------------------------------------------------------------- |
| `onyx_index_attempt_transitions_total`          | Counter | `tenant_id`, `source`, `cc_pair_id`, `connector_name`, `status` | Index attempt status transitions (in_progress, success, etc.) |
| `onyx_connector_in_error_state`                 | Gauge   | `tenant_id`, `source`, `cc_pair_id`, `connector_name`           | Whether connector is in repeated error state (1=yes, 0=no)    |
| `onyx_connector_last_success_timestamp_seconds` | Gauge   | `tenant_id`, `source`, `cc_pair_id`, `connector_name`           | Unix timestamp of last successful indexing                    |
| `onyx_connector_docs_indexed_total`             | Counter | `tenant_id`, `source`, `cc_pair_id`, `connector_name`           | Total documents indexed per connector (monotonic)             |
| `onyx_connector_indexing_errors_total`          | Counter | `tenant_id`, `source`, `cc_pair_id`, `connector_name`           | Total failed index attempts per connector (monotonic)         |

### Pull-Based Collectors (`onyx.server.metrics.indexing_pipeline`)

Registered only in the **Monitoring** worker. Collectors query Redis at scrape time with a 30-second TTL cache and a 120-second timeout to prevent the `/metrics` endpoint from hanging.

| Metric                               | Type  | Labels  | Description                         |
| ------------------------------------ | ----- | ------- | ----------------------------------- |
| `onyx_queue_depth`                   | Gauge | `queue` | Celery queue length                 |
| `onyx_queue_unacked`                 | Gauge | `queue` | Unacknowledged messages per queue   |
| `onyx_queue_oldest_task_age_seconds` | Gauge | `queue` | Age of the oldest task in the queue |

### Adding Metrics to a Worker

Currently only the docfetching and docprocessing workers have push-based task metrics wired up. To add metrics to another worker (e.g. heavy, light, primary):

**1. Import and call the generic handlers from the worker's signal handlers:**

```python
from onyx.server.metrics.celery_task_metrics import (
    on_celery_task_prerun,
    on_celery_task_postrun,
    on_celery_task_retry,
    on_celery_task_revoked,
    on_celery_task_rejected,
)

@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **kwds):
    app_base.on_task_prerun(sender, task_id, task, args, kwargs, **kwds)
    on_celery_task_prerun(task_id, task)
```

Do the same for `task_postrun`, `task_retry`, `task_revoked`, and `task_rejected` — see `apps/docfetching.py` for the complete example.

**2. Start the metrics server on `worker_ready`:**

```python
from onyx.server.metrics.metrics_server import start_metrics_server

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    start_metrics_server("your_worker_type")
    app_base.on_worker_ready(sender, **kwargs)
```

Add a default port for your worker type in `metrics_server.py`'s `_DEFAULT_PORTS` dict, or set `PROMETHEUS_METRICS_PORT` in the environment.

**3. (Optional) Add domain-specific enrichment:**

If your tasks need richer labels beyond `task_name`/`queue`, create a new module in `server/metrics/` following `indexing_task_metrics.py`:

- Define Counters/Histograms with your domain labels
- Write `on_<domain>_task_prerun` / `on_<domain>_task_postrun` handlers that filter by task name and no-op for others
- Call them from the worker's signal handlers alongside the generic ones

**Cardinality warning:** Never use user-defined free-form strings as metric labels — they create unbounded cardinality. Use IDs or enum values. If you need free-form labels, use pull-based collectors (monitoring worker) where cardinality is naturally bounded.

### Current Worker Integration Status

| Worker               | Generic Task Metrics | Domain Metrics | Metrics Server                       |
| -------------------- | -------------------- | -------------- | ------------------------------------ |
| Docfetching          | ✓                    | ✓ (indexing)   | ✓ (port 9092)                        |
| Docprocessing        | ✓                    | ✓ (indexing)   | ✓ (port 9093)                        |
| Monitoring           | —                    | —              | ✓ (port 9096, pull-based collectors) |
| Primary              | —                    | —              | —                                    |
| Light                | —                    | —              | —                                    |
| Heavy                | —                    | —              | —                                    |
| User File Processing | —                    | —              | —                                    |
| KG Processing        | —                    | —              | —                                    |

### Example PromQL Queries (Celery)

```promql
# Task completion rate by worker queue
sum by (queue) (rate(onyx_celery_task_completed_total[5m]))

# P95 task duration for pruning tasks
histogram_quantile(0.95,
  sum by (le) (rate(onyx_celery_task_duration_seconds_bucket{task_name=~".*pruning.*"}[5m])))

# Task failure rate
sum by (task_name) (rate(onyx_celery_task_completed_total{outcome="failure"}[5m]))
  / sum by (task_name) (rate(onyx_celery_task_completed_total[5m]))

# Active tasks per queue
sum by (queue) (onyx_celery_tasks_active)

# Indexing throughput by source type
sum by (source) (rate(onyx_indexing_task_completed_total{outcome="success"}[5m]))

# Queue depth — are tasks backing up?
onyx_queue_depth > 100
```

## OpenSearch Search Metrics

These metrics track OpenSearch search latency and throughput. Collected via `onyx.server.metrics.opensearch_search`.

| Metric                                           | Type      | Labels        | Description                                                                 |
| ------------------------------------------------ | --------- | ------------- | --------------------------------------------------------------------------- |
| `onyx_opensearch_search_client_duration_seconds` | Histogram | `search_type` | Client-side end-to-end latency (network + serialization + server execution) |
| `onyx_opensearch_search_server_duration_seconds` | Histogram | `search_type` | Server-side execution time from OpenSearch `took` field                     |
| `onyx_opensearch_search_total`                   | Counter   | `search_type` | Total search requests sent to OpenSearch                                    |
| `onyx_opensearch_searches_in_progress`           | Gauge     | `search_type` | Currently in-flight OpenSearch searches                                     |

Search type label values: See `OpenSearchSearchType`.

---

## Example PromQL Queries

### Which endpoints are saturated right now?

```promql
# Top 10 endpoints by in-progress requests
topk(10, http_requests_inprogress)
```

### What's the P99 latency per endpoint?

```promql
# P99 latency by handler over the last 5 minutes
histogram_quantile(0.99, sum by (handler, le) (rate(http_request_duration_seconds_bucket[5m])))
```

### Which endpoints have the highest request rate?

```promql
# Requests per second by handler, top 10
topk(10, sum by (handler) (rate(http_requests_total[5m])))
```

### Which endpoints are returning errors?

```promql
# 5xx error rate by handler
sum by (handler) (rate(http_requests_total{status=~"5.."}[5m]))
```

### Slow request hotspots

```promql
# Slow requests per minute by handler
sum by (handler) (rate(onyx_api_slow_requests_total[5m])) * 60
```

### Latency trending up?

```promql
# Compare P50 latency now vs 1 hour ago
histogram_quantile(0.5, sum by (le) (rate(http_request_duration_highr_seconds_bucket[5m])))
  -
histogram_quantile(0.5, sum by (le) (rate(http_request_duration_highr_seconds_bucket[5m] offset 1h)))
```

### Overall request throughput

```promql
# Total requests per second across all endpoints
sum(rate(http_requests_total[5m]))
```

### Pool utilization (% of capacity in use)

```promql
# Sync pool utilization: checked-out / (pool_size + max_overflow)
# NOTE: Replace 10 with your actual POSTGRES_API_SERVER_POOL_OVERFLOW value.
onyx_db_pool_checked_out{engine="sync"} / (onyx_db_pool_size{engine="sync"} + 10) * 100
```

### Pool approaching exhaustion?

```promql
# Alert when checked-out connections exceed 80% of pool capacity
# NOTE: Replace 10 with your actual POSTGRES_API_SERVER_POOL_OVERFLOW value.
onyx_db_pool_checked_out{engine="sync"} > 0.8 * (onyx_db_pool_size{engine="sync"} + 10)
```

### Which endpoints are hogging DB connections?

```promql
# Top 10 endpoints by connections currently held
topk(10, onyx_db_connections_held_by_endpoint{engine="sync"})
```

### Which endpoints hold connections the longest?

```promql
# P99 connection hold time by endpoint
histogram_quantile(0.99, sum by (handler, le) (rate(onyx_db_connection_hold_seconds_bucket{engine="sync"}[5m])))
```

### Connection checkout/checkin rate

```promql
# Checkouts per second by engine
sum by (engine) (rate(onyx_db_pool_checkout_total[5m]))
```

### OpenSearch P99 search latency by type

```promql
# P99 client-side latency by search type
histogram_quantile(0.99, sum by (search_type, le) (rate(onyx_opensearch_search_client_duration_seconds_bucket[5m])))
```

### OpenSearch search throughput

```promql
# Searches per second by type
sum by (search_type) (rate(onyx_opensearch_search_total[5m]))
```

### OpenSearch concurrent searches

```promql
# Total in-flight searches across all instances
sum(onyx_opensearch_searches_in_progress)
```

### OpenSearch network overhead

```promql
# Difference between client and server P50 reveals network/serialization cost.
histogram_quantile(0.5, sum by (le) (rate(onyx_opensearch_search_client_duration_seconds_bucket[5m])))
  -
histogram_quantile(0.5, sum by (le) (rate(onyx_opensearch_search_server_duration_seconds_bucket[5m])))
```
