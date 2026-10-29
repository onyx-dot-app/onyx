# Prometheus metrics

All Onyx Prometheus metrics live in this package. The customer reference (endpoints, ports, auth,
metric families, example alerts) is https://docs.onyx.app/deployment/production/monitoring.
Update that page when you add a metric family, a port, or a setting.

## Where metrics are served

- **API server and MCP server:** `prometheus_setup.py` adds `prometheus-fastapi-instrumentator`
  and exposes `GET /metrics`, guarded by `metrics_auth.py:verify_metrics_token`. The guard fails
  closed: no `METRICS_AUTH_TOKEN` and no `DISABLE_METRICS_AUTH` means every scrape gets 401.
- **Celery workers:** `metrics_server.py:start_metrics_server(worker_type)` starts a standalone,
  unauthenticated server from the worker's `worker_ready` handler. Default ports are in
  `_DEFAULT_PORTS`. A worker type with no default port and no `PROMETHEUS_METRICS_PORT` starts
  no server.

## Add a metric

1. Put one metric concept in one module here. Define `prometheus_client` objects at module level.
2. Name it `onyx_<thing>`. Counters end in `_total`. Durations end in `_seconds`, sizes in `_bytes`.
3. Keep label cardinality bounded. Use IDs, enums, and route templates. Never use a free-form user
   string (a connector name, a raw path, an email) on a per-task or per-request series. A pull-based
   collector, which emits one series per object, can carry such a label.
4. Multi-tenant: an HTTP-scoped or connector-scoped metric needs a `tenant_id` label, or an explicit
   single-tenant-only guard (see `connector_state_metrics.py`). Otherwise it mixes tenants.
5. Wire it in:
   - **Per HTTP request:** write a callback that takes `prometheus_fastapi_instrumentator.metrics.Info`
     and register it in `prometheus_setup.py` (see `slow_requests.py`, `per_tenant.py`).
   - **Attached to a resource** (engine, pool, client): add a `setup_*` or `register_*` function and
     call it from the owning process lifespan after the resource exists (see
     `postgres_connection_pool.py`, called from `onyx/main.py`). Keep `setup_prometheus_metrics()`
     limited to shared HTTP instrumentation.
   - **Read at scrape time:** write a collector with a bounded read time, so a slow read cannot
     hang the scrape. `indexing_pipeline.py:_CachedCollector` returns a cached snapshot (see
     `ee/onyx/server/metrics/license_metrics.py`). `connector_state_metrics.py` returns no
     samples on timeout and reports `onyx_connector_state_collection_success`.
   - **Per Celery task:** call the `celery_task_metrics.py` handlers (`on_celery_task_prerun`,
     `_postrun`, `_retry`, `_revoked`, `_rejected`) from the worker's own Celery signal handlers,
     next to the `app_base` calls (see `background/celery/apps/docfetching.py`). For richer labels,
     add a domain module like `indexing_task_metrics.py` whose handlers filter by task name and
     no-op for other tasks.
   - **New worker type:** call `start_metrics_server("<type>")` on `worker_ready` and add a default
     port to `_DEFAULT_PORTS`. Add a ServiceMonitor in
     `deployment/helm/charts/onyx/templates/celery-worker-servicemonitors.yaml`.
6. Test it under `backend/tests/unit/onyx/server/metrics/` or `backend/tests/unit/server/metrics/`.
   Patch the metric objects. Do not increment real global counters in tests.
7. If it needs a panel, edit the dashboards in `deployment/helm/charts/onyx/dashboards/`.
