# API Server Prometheus Metrics

All metrics are exported via the `/metrics` endpoint (Prometheus exposition format).

## Feature Flags

| Env Var | Default | Description |
|---------|---------|-------------|
| `ENABLE_MEMORY_DELTA_METRICS` | `true` | Per-endpoint RSS delta tracking |
| `ENABLE_EVENT_LOOP_LAG_PROBE` | `true` | Asyncio event loop lag measurement |
| `ENABLE_REDIS_POOL_METRICS` | `true` | Redis connection pool visibility |
| `ENABLE_THREADPOOL_METRICS` | `true` | Thread pool task instrumentation |
| `ENABLE_DEEP_PROFILING` | `false` | tracemalloc + GC + object counting (10-20% overhead) |
| `DEEP_PROFILING_SNAPSHOT_INTERVAL_SECONDS` | `60.0` | Interval between tracemalloc snapshots |
| `DEEP_PROFILING_TOP_N_ALLOCATIONS` | `20` | Number of top allocation sites to export |
| `DEEP_PROFILING_TOP_N_TYPES` | `30` | Number of top object types to export |
| `ENABLE_ADMIN_DEBUG_ENDPOINTS` | `false` | JSON debug endpoints at `/admin/debug/*` |
| `EVENT_LOOP_LAG_PROBE_INTERVAL_SECONDS` | `2.0` | Lag probe sleep interval |

## Memory Metrics

### Per-Endpoint RSS Delta

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_api_request_rss_delta_bytes` | Histogram | `handler` | RSS change in bytes during a request |
| `onyx_api_process_rss_bytes` | Gauge | — | Current process RSS |

**Useful queries:**
```promql
# Top 5 endpoints by average memory delta
topk(5, avg by (handler)(
  rate(onyx_api_request_rss_delta_bytes_sum[5m])
  / rate(onyx_api_request_rss_delta_bytes_count[5m])
))

# RSS growth rate (sustained positive = leak)
deriv(process_resident_memory_bytes[5m])
```

## Event Loop Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_api_event_loop_lag_seconds` | Gauge | — | Current scheduling lag |
| `onyx_api_event_loop_lag_max_seconds` | Gauge | — | Max lag since process start |

**Alert rule:**
```promql
onyx_api_event_loop_lag_seconds > 0.1  # >100ms = blocked loop
```

## Redis Pool Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_redis_pool_in_use` | Gauge | `pool` | Checked-out connections |
| `onyx_redis_pool_available` | Gauge | `pool` | Idle connections |
| `onyx_redis_pool_max` | Gauge | `pool` | Configured max |
| `onyx_redis_pool_created` | Gauge | `pool` | Lifetime connections created |

Pool label values: `primary`, `replica`.

**Alert rule:**
```promql
onyx_redis_pool_in_use{pool="primary"} / onyx_redis_pool_max{pool="primary"} > 0.8
```

## Thread Pool Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_threadpool_tasks_submitted_total` | Counter | — | Total tasks submitted |
| `onyx_threadpool_tasks_active` | Gauge | — | Currently executing tasks |
| `onyx_threadpool_task_duration_seconds` | Histogram | — | Task execution duration |
| `onyx_process_thread_count` | Gauge | — | OS threads in the process |

## Deep Profiling Metrics (opt-in)

Requires `ENABLE_DEEP_PROFILING=true`. Adds ~10-20% allocation overhead.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `onyx_tracemalloc_top_bytes` | Gauge | `source` | Bytes by top allocation sites |
| `onyx_tracemalloc_top_count` | Gauge | `source` | Allocation count by source |
| `onyx_tracemalloc_delta_bytes` | Gauge | `source` | Growth since previous snapshot |
| `onyx_tracemalloc_total_bytes` | Gauge | — | Total traced memory |
| `onyx_gc_collections_total` | Counter | `generation` | GC runs per generation |
| `onyx_gc_collected_total` | Counter | `generation` | Objects collected |
| `onyx_gc_uncollectable_total` | Counter | `generation` | Uncollectable objects |
| `onyx_object_type_count` | Gauge | `type` | Live objects by type (top N) |

**Useful queries:**
```promql
# Top leaking code locations
topk(10, onyx_tracemalloc_delta_bytes > 0)

# GC uncollectable (true leaks)
rate(onyx_gc_uncollectable_total[5m])

# Object type accumulation
topk(10, onyx_object_type_count)
```

## Existing Metrics (already active)

| Metric | Type | Description |
|--------|------|-------------|
| `http_requests_total` | Counter | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | Request latency |
| `http_requests_inprogress` | Gauge | In-flight requests |
| `onyx_api_slow_requests_total` | Counter | Requests above threshold |
| `onyx_db_pool_checked_out` | Gauge | DB pool checked-out connections |
| `onyx_db_pool_checked_in` | Gauge | DB pool idle connections |
| `onyx_db_pool_overflow` | Gauge | DB pool overflow connections |
| `onyx_db_pool_size` | Gauge | DB pool configured size |
| `onyx_db_connections_held_by_endpoint` | Gauge | DB connections per endpoint |
| `process_resident_memory_bytes` | Gauge | Process RSS (default collector) |
| `process_cpu_seconds_total` | Counter | Process CPU time (default collector) |

## Admin Debug Endpoints

Requires `ENABLE_ADMIN_DEBUG_ENDPOINTS=true`. All require admin auth.

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/admin/debug/process-info` | GET | RSS, VMS, CPU%, FD count, threads, uptime |
| `/admin/debug/pool-state` | GET | Postgres + Redis pool state as JSON |
| `/admin/debug/threads` | GET | All threads (name, daemon, ident) |
| `/admin/debug/event-loop-lag` | GET | Current + max event loop lag |
