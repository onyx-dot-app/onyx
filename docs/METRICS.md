# Onyx Prometheus Metrics Reference

## API Server Metrics

These metrics are exposed at `GET /metrics` on the API server.

### Built-in (via `prometheus-fastapi-instrumentator`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `status`, `handler` | Total request count |
| `http_request_duration_highr_seconds` | Histogram | _(none)_ | High-resolution latency (many buckets, no labels) |
| `http_request_duration_seconds` | Histogram | `method`, `handler` | Latency by handler (few buckets for aggregation) |
| `http_request_size_bytes` | Summary | `handler` | Incoming request content length |
| `http_response_size_bytes` | Summary | `handler` | Outgoing response content length |
| `http_requests_inprogress` | Gauge | `method`, `handler` | Currently in-flight requests |

### Custom (via `onyx.server.prometheus_instrumentation`)

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
