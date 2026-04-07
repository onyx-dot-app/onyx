# Overview of Onyx Background Jobs

The background jobs take care of:

1. Pulling/Indexing documents (from connectors)
2. Updating document metadata (from connectors)
3. Cleaning up checkpoints and logic around indexing work (indexing indexing checkpoints and index attempt metadata)
4. Handling user uploaded files and deletions (from the Projects feature and uploads via the Chat)
5. Reporting metrics on things like queue length for monitoring purposes

## Worker → Queue Mapping

| Worker                    | File                           | Queues                                                                                                               |
| ------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Primary                   | `apps/primary.py`              | `celery`                                                                                                             |
| Light                     | `apps/light.py`                | `vespa_metadata_sync`, `connector_deletion`, `doc_permissions_upsert`, `checkpoint_cleanup`, `index_attempt_cleanup` |
| Heavy                     | `apps/heavy.py`                | `connector_pruning`, `connector_doc_permissions_sync`, `connector_external_group_sync`, `csv_generation`, `sandbox`  |
| Docprocessing             | `apps/docprocessing.py`        | `docprocessing`                                                                                                      |
| Docfetching               | `apps/docfetching.py`          | `connector_doc_fetching`                                                                                             |
| User File Processing      | `apps/user_file_processing.py` | `user_file_processing`, `user_file_project_sync`, `user_file_delete`                                                 |
| Monitoring                | `apps/monitoring.py`           | `monitoring`                                                                                                         |
| Background (consolidated) | `apps/background.py`           | All queues above except `celery`                                                                                     |

## Non-Worker Apps

| App        | File        | Purpose                                                                                               |
| ---------- | ----------- | ----------------------------------------------------------------------------------------------------- |
| **Beat**   | `beat.py`   | Celery beat scheduler with `DynamicTenantScheduler` that generates per-tenant periodic task schedules |
| **Client** | `client.py` | Minimal app for task submission from non-worker processes (e.g., API server)                          |

### Shared Module

`app_base.py` provides:

- `TenantAwareTask` - Base task class that sets tenant context
- Signal handlers for logging, cleanup, and lifecycle events
- Readiness probes and health checks

## Worker Details

### Primary (Coordinator and task dispatcher)

It is the single worker which handles tasks from the default celery queue. It is a singleton worker ensured by the `PRIMARY_WORKER` Redis lock
which it touches every `CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 8` seconds (using Celery Bootsteps)

On startup:

- waits for redis, postgres, document index to all be healthy
- acquires the singleton lock
- cleans all the redis states associated with background jobs
- mark orphaned index attempts failed

Then it cycles through its tasks as scheduled by Celery Beat:

| Task                              | Frequency | Description                                                                                |
| --------------------------------- | --------- | ------------------------------------------------------------------------------------------ |
| `check_for_indexing`              | 15s       | Scans for connectors needing indexing → dispatches to `DOCFETCHING` queue                  |
| `check_for_vespa_sync_task`       | 20s       | Finds stale documents/document sets → dispatches sync tasks to `VESPA_METADATA_SYNC` queue |
| `check_for_pruning`               | 20s       | Finds connectors due for pruning → dispatches to `CONNECTOR_PRUNING` queue                 |
| `check_for_connector_deletion`    | 20s       | Processes deletion requests → dispatches to `CONNECTOR_DELETION` queue                     |
| `check_for_user_file_processing`  | 20s       | Checks for user uploads → dispatches to `USER_FILE_PROCESSING` queue                       |
| `check_for_checkpoint_cleanup`    | 1h        | Cleans up old indexing checkpoints                                                         |
| `check_for_index_attempt_cleanup` | 30m       | Cleans up old index attempts                                                               |
| `celery_beat_heartbeat`           | 1m        | Heartbeat for Beat watchdog                                                                |

Watchdog is a separate Python process managed by supervisord which runs alongside celery workers. It checks the ONYX_CELERY_BEAT_HEARTBEAT_KEY in
Redis to ensure Celery Beat is not dead. Beat schedules the celery_beat_heartbeat for Primary to touch the key and share that it's still alive.
See supervisord.conf for watchdog config.

### Light

Fast and short living tasks that are not resource intensive. High concurrency:
Can have 24 concurrent workers, each with a prefetch of 8 for a total of 192 tasks in flight at once.

Tasks it handles:

- Syncs access/permissions, document sets, boosts, hidden state
- Deletes documents that are marked for deletion in Postgres
- Cleanup of checkpoints and index attempts

### Heavy

Long running, resource intensive tasks, handles pruning and sandbox operations. Low concurrency - max concurrency of 4 with 1 prefetch.

Does not interact with the Document Index, it handles the syncs with external systems. Large volume API calls to handle pruning and fetching permissions, etc.

Generates CSV exports which may take a long time with significant data in Postgres.

Sandbox (new feature) for running Next.js, Python virtual env, OpenCode AI Agent, and access to knowledge files

### Docprocessing, Docfetching, User File Processing

Docprocessing and Docfetching are for indexing documents:

- Docfetching runs connectors to pull documents from external APIs (Google Drive, Confluence, etc.), stores batches to file storage, and dispatches docprocessing tasks
- Docprocessing retrieves batches, runs the indexing pipeline (chunking, embedding), and indexes into the Document Index
  User Files come from uploads directly via the input bar

### Monitoring

Observability and metrics collections:

- Queue lengths, connector success/failure, connector latencies
- Memory of supervisor managed processes (workers, beat, slack)
- Cloud and multitenant specific monitorings

## Prometheus Metrics

Workers expose Prometheus metrics via a standalone HTTP server on a dedicated port. The metrics system has two layers:

### Generic Task Metrics (`server/metrics/celery_task_metrics.py`)

Tracks lifecycle events for **all** tasks on a worker — started, completed, active, duration, retries, revocations, rejections. Labels: `task_name`, `queue`, and `outcome` (for completions).

These are **push-based**: signal handlers fire on Celery signals (`task_prerun`, `task_postrun`, `task_retry`, etc.) and update Prometheus counters/gauges/histograms in-process.

### Domain-Specific Task Metrics (e.g. `server/metrics/indexing_task_metrics.py`)

Enriches specific tasks with domain-level labels. For example, `indexing_task_metrics.py` adds `source`, `tenant_id`, and `cc_pair_id` labels to docfetching/docprocessing tasks.

These modules filter by task name and silently no-op for tasks they don't handle, so they're safe to wire up broadly.

### Pull-Based Collectors (`server/metrics/indexing_pipeline.py`)

Registered only in the **Monitoring** worker. Collectors query Redis/Postgres at scrape time to produce queue depth, connector health, index attempt state, and worker heartbeat metrics. These use a 30-second TTL cache to avoid hammering data stores on frequent scrapes.

### Integrating Metrics Into a Worker

To add metrics to a worker, follow the pattern in `apps/docfetching.py` (which has full metrics) vs `apps/heavy.py` (which currently does not):

**1. Import the metrics handlers and metrics server:**

```python
from onyx.server.metrics.celery_task_metrics import (
    on_celery_task_prerun,
    on_celery_task_postrun,
    on_celery_task_retry,
    on_celery_task_revoked,
    on_celery_task_rejected,
)
from onyx.server.metrics.metrics_server import start_metrics_server
```

**2. Call the generic handlers from the worker's signal handlers:**

```python
@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **kwds):
    app_base.on_task_prerun(sender, task_id, task, args, kwargs, **kwds)
    on_celery_task_prerun(task_id, task)  # ← add this

@signals.task_postrun.connect
def on_task_postrun(sender, task_id, task, args, kwargs, retval, state, **kwds):
    app_base.on_task_postrun(sender, task_id, task, args, kwargs, retval, state, **kwds)
    on_celery_task_postrun(task_id, task, state)  # ← add this
```

Add `task_retry`, `task_revoked`, and `task_rejected` handlers as well — see `apps/docfetching.py` for the exact signatures.

**3. Start the metrics server on worker ready:**

```python
@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    start_metrics_server("your_worker_type")  # ← add this
    app_base.on_worker_ready(sender, **kwargs)
```

The port is resolved from `PROMETHEUS_METRICS_PORT` env var, or a default in `metrics_server.py`'s `_DEFAULT_PORTS` dict. Add a default port for your worker type there if it doesn't have one.

**4. (Optional) Add domain-specific metrics:**

If your tasks need richer labels beyond `task_name`/`queue` (e.g. per-connector, per-tenant breakdowns), create a new module in `server/metrics/` following the pattern in `indexing_task_metrics.py`:

- Define Counters/Histograms with your domain labels
- Write `on_<domain>_task_prerun` / `on_<domain>_task_postrun` handlers that filter by task name
- Call them from the worker's signal handlers alongside the generic ones

**Cardinality warning:** Avoid using user-defined free-form strings (like connector names) as metric labels — they create unbounded cardinality. Use IDs or enum values instead. If you need free-form labels, put them in pull-based collectors (like the monitoring worker) where cardinality is naturally bounded.

### Current Integration Status

| Worker               | Generic Task Metrics | Domain Metrics | Metrics Server                       |
| -------------------- | -------------------- | -------------- | ------------------------------------ |
| Docfetching          | ✓                    | ✓ (indexing)   | ✓ (port 9092)                        |
| Docprocessing        | ✓                    | ✓ (indexing)   | ✓ (port 9093)                        |
| Monitoring           | —                    | —              | ✓ (port 9096, pull-based collectors) |
| Primary              | —                    | —              | —                                    |
| Light                | —                    | —              | —                                    |
| Heavy                | —                    | —              | —                                    |
| User File Processing | —                    | —              | —                                    |
