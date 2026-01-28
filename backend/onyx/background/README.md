# Overview of Onyx Background Jobs

The background jobs take care of:
1. Pulling/Indexing documents (from connectors)
2. Updating document metadata (from connectors)
3. Cleaning up checkpoints and logic around indexing work (indexing indexing checkpoints and index attempt metadata)
4. Handling user uploaded files and deletions (from the Projects feature and uploads via the Chat)
5. Reporting metrics on things like queue length for monitoring purposes

## Worker → Queue Mapping

| Worker | File | Queues |
|--------|------|--------|
| Primary | `apps/primary.py` | `celery` |
| Light | `apps/light.py` | `vespa_metadata_sync`, `connector_deletion`, `doc_permissions_upsert`, `checkpoint_cleanup`, `index_attempt_cleanup` |
| Heavy | `apps/heavy.py` | `connector_pruning`, `connector_doc_permissions_sync`, `connector_external_group_sync`, `csv_generation`, `sandbox` |
| Docprocessing | `apps/docprocessing.py` | `docprocessing` |
| Docfetching | `apps/docfetching.py` | `connector_doc_fetching` |
| User File Processing | `apps/user_file_processing.py` | `user_file_processing`, `user_file_project_sync`, `user_file_delete` |
| Monitoring | `apps/monitoring.py` | `monitoring` |
| Background (consolidated) | `apps/background.py` | All queues above except `celery` |

## Non-Worker Apps
| App | File | Purpose |
|-----|------|---------|
| **Beat** | `beat.py` | Celery beat scheduler with `DynamicTenantScheduler` that generates per-tenant periodic task schedules |
| **Client** | `client.py` | Minimal app for task submission from non-worker processes (e.g., API server) |

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

| Task | Frequency | Description |
|------|-----------|-------------|
| `check_for_indexing` | 15s | Scans for connectors needing indexing → dispatches to `DOCFETCHING` queue |
| `check_for_vespa_sync_task` | 20s | Finds stale documents/document sets → dispatches sync tasks to `VESPA_METADATA_SYNC` queue |
| `check_for_pruning` | 20s | Finds connectors due for pruning → dispatches to `CONNECTOR_PRUNING` queue |
| `check_for_connector_deletion` | 20s | Processes deletion requests → dispatches to `CONNECTOR_DELETION` queue |
| `check_for_user_file_processing` | 20s | Checks for user uploads → dispatches to `USER_FILE_PROCESSING` queue |
| `check_for_checkpoint_cleanup` | 1h | Cleans up old indexing checkpoints |
| `check_for_index_attempt_cleanup` | 30m | Cleans up old index attempts |
| `kombu_message_cleanup_task` | periodic | Cleans orphaned Kombu messages from DB (Kombu being the messaging framework used by Celery) |
| `celery_beat_heartbeat` | 1m | Heartbeat for Beat watchdog |

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
- Queue lengths, connector success/failure, lconnector latencies
- Memory of supervisor managed processes (workers, beat, slack)
- Cloud and multitenant specific monitorings
