# Onyx Prometheus Metrics Reference

## Adding New Metrics

All Prometheus metrics live in the `backend/onyx/server/metrics/` package. Follow these steps to add a new metric.

### 1. Choose the right file (or create a new one)

| File | Purpose |
|------|---------|
| `metrics/slow_requests.py` | Slow request counter + callback |
| `metrics/postgres_connection_pool.py` | SQLAlchemy connection pool metrics |
| `metrics/prometheus_setup.py` | FastAPI instrumentator config (orchestrator) |

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

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `status`, `handler` | Total request count |
| `http_request_duration_highr_seconds` | Histogram | _(none)_ | High-resolution latency (many buckets, no labels) |
| `http_request_duration_seconds` | Histogram | `method`, `handler` | Latency by handler (custom buckets for P95/P99) |
| `http_request_size_bytes` | Summary | `handler` | Incoming request content length |
| `http_response_size_bytes` | Summary | `handler` | Outgoing response content length |
| `http_requests_inprogress` | Gauge | `method`, `handler` | Currently in-flight requests |

### Custom (via `onyx.server.metrics`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_api_slow_requests_total` | Counter | `method`, `handler`, `status` | Requests exceeding `SLOW_REQUEST_THRESHOLD_SECONDS` (default 1s) |

### Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `SLOW_REQUEST_THRESHOLD_SECONDS` | `1.0` | Duration threshold for slow request counting |

### Instrumentator Settings

- `should_group_status_codes=False` — Reports exact HTTP status codes (e.g. 401, 403, 500)
- `should_instrument_requests_inprogress=True` — Enables the in-progress request gauge
- `inprogress_labels=True` — Breaks down in-progress gauge by `method` and `handler`
- `excluded_handlers=["/health", "/metrics", "/openapi.json"]` — Excludes noisy endpoints from metrics

## Database Pool Metrics

These metrics provide visibility into SQLAlchemy connection pool state across all three engines (`sync`, `async`, `readonly`). Collected via `onyx.server.metrics.postgres_connection_pool`.

### Pool State (via custom Prometheus collector — snapshot on each scrape)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_db_pool_checked_out` | Gauge | `engine` | Currently checked-out connections |
| `onyx_db_pool_checked_in` | Gauge | `engine` | Idle connections available in the pool |
| `onyx_db_pool_overflow` | Gauge | `engine` | Current overflow connections beyond `pool_size` |
| `onyx_db_pool_size` | Gauge | `engine` | Configured pool size (constant) |

### Pool Lifecycle (via SQLAlchemy pool event listeners)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_db_pool_checkout_total` | Counter | `engine` | Total connection checkouts from the pool |
| `onyx_db_pool_checkin_total` | Counter | `engine` | Total connection checkins to the pool |
| `onyx_db_pool_connections_created_total` | Counter | `engine` | Total new database connections created |
| `onyx_db_pool_invalidations_total` | Counter | `engine` | Total connection invalidations |
| `onyx_db_pool_checkout_timeout_total` | Counter | `engine` | Total connection checkout timeouts |

### Per-Endpoint Attribution (via pool events + endpoint context middleware)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_db_connections_held_by_endpoint` | Gauge | `handler`, `engine` | DB connections currently held, by endpoint |
| `onyx_db_connection_hold_seconds` | Histogram | `handler`, `engine` | Duration a DB connection is held by an endpoint |

Engine label values: `sync` (main read-write), `async` (async sessions), `readonly` (read-only user).

Connections from background tasks (Celery) or boot-time warmup appear as `handler="unknown"`.

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
