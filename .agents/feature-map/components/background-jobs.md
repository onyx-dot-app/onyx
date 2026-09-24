# Background Jobs (Celery)

> The shared asynchronous machinery. It does not decide what to index, prune, or
> sync; it decides when a task runs, which worker runs it, how tenant context
> travels with it, and how a stuck task is detected and recovered.

**Domain:** background-jobs
**Edition:** CE, with EE additions dispatched through the same versioned-app
mechanism as the rest of the codebase
**Owns:**
`backend/onyx/background/celery/apps/` (`app_base.py`, `primary.py`, `beat.py`,
`light.py`, `heavy.py`, `docfetching.py`, `docprocessing.py`,
`user_file_processing.py`, `monitoring.py`, `scheduled_tasks.py`, `client.py`),
`backend/onyx/background/celery/versioned_apps/`,
`backend/onyx/background/celery/configs/`,
`backend/onyx/background/celery/celery_redis.py`, `celery_utils.py`,
`celery_k8s_probe.py`, `memory_monitoring.py`,
`backend/onyx/background/celery/tasks/beat_schedule.py`,
`backend/onyx/background/celery/tasks/monitoring/`,
`backend/onyx/background/task_utils.py`, `periodic_poller.py`, `error_logging.py`,
`backend/onyx/db/tasks.py`, `db/sync_record.py`, `db/background_error.py`,
`backend/ee/onyx/background/celery/apps/`, `ee/onyx/background/celery/tasks/beat_schedule.py`

**Read first:** `backend/onyx/background/README.md`. It is the design overview
written by the team that built this layer. This document maps it to code, adds
verification guidance, and corrects a few places where the README and the code
have drifted apart (see §9).

---

## 1. What the admin experiences

A connector configured with a refresh interval indexes on that schedule without
anyone triggering it by hand. Pruning removes documents deleted at the source on
its own cadence. Permission and group syncs pick up ACL changes from the external
system without a user action. A user-uploaded file starts processing within
seconds of the upload finishing.

None of this is instant. Every one of these paths is a periodic scan (run by
Celery Beat) that notices work is due and hands it to a worker, so there is
always some delay, typically single-digit seconds to tens of seconds, between a
change becoming eligible and a task picking it up. If a worker is down or a
queue is backed up, the delay grows and nothing else in the product tells the
admin directly; the signal is a stale "last indexed" or "last synced" timestamp
on the connector.

---

## 2. Surfaces

### Worker apps

Each worker is a `celery.Celery` app built in `onyx/background/celery/apps/*.py`
and re-exported through a "factory stub" in
`onyx/background/celery/versioned_apps/*.py`. The versioned-app file calls
`fetch_versioned_implementation("onyx.background.celery.apps.<name>", "celery_app")`
(`versioned_apps/primary.py:app`), which is the same EE/CE dispatch mechanism
described in `[[editions-and-gating]]`: with `ENTERPRISE_EDITION_ENABLED` set,
the loader resolves to `ee/onyx/background/celery/apps/<name>.py` instead of the
CE file. `onyx/background/celery/versioned_apps/light.py` is the one exception;
its docstring states there is no EE variant, so it imports the CE app directly.
Workers are started against the `versioned_apps` module (`supervisord.conf` and
the Helm worker templates both use `celery -A onyx.background.celery.versioned_apps.<name>`),
never the bare `apps` module.

Verified worker-to-queue mapping, cross-checked against
`backend/supervisord.conf` and `deployment/helm/charts/onyx/templates/celery-worker-*.yaml`
(both agree with each other):

| Worker | App file | Queues (`-Q`) |
|---|---|---|
| Primary | `apps/primary.py` | `celery` (local); the Helm chart additionally passes `celery,periodic_tasks` for the primary deployment, but no task or beat entry in this codebase routes to a `periodic_tasks` queue (see §9). |
| Light | `apps/light.py` | `vespa_metadata_sync, connector_deletion, doc_permissions_upsert, checkpoint_cleanup, index_attempt_cleanup, index_reclaim, opensearch_migration, chat_ttl_deletion` |
| Heavy | `apps/heavy.py` | `connector_pruning, connector_doc_permissions_sync, connector_external_group_sync, csv_generation, sandbox, connector_hierarchy_fetching, capability_checks` |
| Docprocessing | `apps/docprocessing.py` | `docprocessing, port` |
| Docfetching | `apps/docfetching.py` | `connector_doc_fetching` |
| User File Processing | `apps/user_file_processing.py` | `user_file_processing, user_file_project_sync, user_file_delete, user_file_port` |
| Monitoring | `apps/monitoring.py` | `monitoring` |
| Scheduled Tasks | `apps/scheduled_tasks.py` | `scheduled_tasks` (Craft scheduled-task dispatch; see `apps/scheduled_tasks.py` docstring) |

`background/README.md`'s worker table lists a "Background (consolidated)" worker
at `apps/background.py` that runs every queue except `celery`. **That file does
not exist** (`ls backend/onyx/background/celery/apps/` has no `background.py`,
and none of `supervisord.conf`, the Helm templates, or `versioned_apps/` reference
it). The README's table also omits the `scheduled_tasks` worker entirely, and
understates the Light and Heavy queue lists (missing `index_reclaim`,
`opensearch_migration`, `chat_ttl_deletion` on Light, and
`connector_hierarchy_fetching`, `capability_checks` on Heavy). Treat the table
above, not the README's, as current. `backend/AGENTS.md`'s worker table matches
this document.

### Non-worker apps

- **Beat** (`apps/beat.py`): the scheduler process, started as
  `celery -A onyx.background.celery.versioned_apps.beat beat`. Runs
  `DynamicTenantScheduler` (`apps/beat.py:DynamicTenantScheduler`), a
  `celery.beat.PersistentScheduler` subclass. See §4.
- **Client** (`apps/client.py`): a minimal `Celery` app with no worker or beat
  role, used by non-worker processes (the API server) to call `send_task`.

### `app_base.py`: shared task class and lifecycle hooks

- `TenantAwareTask` (`app_base.py:TenantAwareTask`) is the base `Task` class every
  worker installs (`celery_app.Task = app_base.TenantAwareTask` in each app
  module, and `celery_app.conf.task_default_base = app_base.TenantAwareTask` in
  `beat.py`). Its `__call__` reads `tenant_id` out of the task's kwargs and sets
  `CURRENT_TENANT_ID_CONTEXTVAR` before running the task body, then resets the
  contextvar in a `finally` block. **If `tenant_id` is absent from kwargs, it
  silently falls back to `POSTGRES_DEFAULT_SCHEMA`** rather than raising. See
  [[multi-tenancy]] and §5.
- Signal handlers registered per app (each app file wires the same functions to
  its own `celery.signals`): `on_task_prerun` resets per-task logging context
  (`app_base.py:on_task_prerun`); `on_task_postrun` removes the task's id from
  whichever Redis taskset it belongs to, keyed by task-id prefix
  (`app_base.py:on_task_postrun`); `on_task_revoked` does the same cleanup for the
  document-sync taskset specifically, because a revoked/expired task never runs
  `task_postrun` (`app_base.py:on_task_revoked`); `reset_tenant_id` clears the
  tenant contextvar back to the default schema after every task
  (`app_base.py:reset_tenant_id`).
- Readiness and liveness: `wait_for_redis`, `wait_for_db`, and
  `wait_for_document_index_or_shutdown` (`app_base.py`) block worker startup,
  raising `WorkerShutdown` on timeout. `on_worker_ready` and `on_worker_shutdown`
  touch/remove a file-based readiness probe (`app_base.py:make_probe_path`,
  checked by `celery_k8s_probe.py`'s `main_readiness`/`main_liveness`).
  `LivenessProbe` (`app_base.py:LivenessProbe`) is a Celery bootstep that
  refreshes the liveness file every 15 seconds.
- The primary worker additionally holds a singleton Redis lock,
  `OnyxRedisLocks.PRIMARY_WORKER` (`onyx/configs/constants.py`), touched every
  `CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 8` seconds and released in
  `on_worker_shutdown` (`app_base.py:on_worker_shutdown`).

### Beat schedules

`onyx/background/celery/tasks/beat_schedule.py` defines three lists, resolved
through `fetch_versioned_implementation` so EE can extend them
(`ee/onyx/background/celery/tasks/beat_schedule.py` imports and re-exports the CE
lists plus its own additions):

- `beat_task_templates`: self-hosted-or-cloud task templates (`check-for-indexing`,
  `check-for-vespa-sync`, `check-for-pruning`, `check-for-connector-deletion`,
  `check-for-user-file-processing`, `check-for-checkpoint-cleanup`,
  `check-for-index-attempt-cleanup`, and more). Filtered by
  `_VECTOR_DB_BEAT_TASK_NAMES` when `DISABLE_VECTOR_DB` is set.
  `beat_schedule.py:beat_task_templates`
- `beat_cloud_tasks`: system-wide tasks that exist once regardless of tenant
  count (`monitor-celery-queues`, `monitor-alembic`, `check-available-tenants`,
  `monitor-celery-pidbox`), always routed to `OnyxCeleryQueues.MONITORING`.
  `beat_schedule.py:beat_cloud_tasks`
- `tasks_to_schedule`: the self-hosted (non-`MULTI_TENANT`) schedule, built by
  taking `beat_task_templates` (with the cloud-only `skip_gated`/`work_gated`
  option keys stripped) and adding self-hosted-only entries
  (`monitor-celery-queues`, `monitor-process-memory`, `celery-beat-heartbeat`,
  `emit-version-telemetry`). `beat_schedule.py:tasks_to_schedule`

Every schedule entry sets `expires` (default `BEAT_EXPIRES_DEFAULT = 15 * 60`
seconds, `beat_schedule.py:BEAT_EXPIRES_DEFAULT`), matching the
`backend/AGENTS.md` rule that no task may be enqueued without an expiration.

### Environment configuration

| Variable | Effect |
|---|---|
| `MULTI_TENANT` | Switches Beat between per-tenant schedule generation and a single self-hosted schedule; gates which task lists apply (`shared_configs.configs.MULTI_TENANT`). |
| `DISABLE_VECTOR_DB` | Drops vector-DB-dependent task modules from worker autodiscovery (`app_base.py:_VECTOR_DB_TASK_MODULES`, `filter_task_modules`) and drops the matching beat entries (`beat_schedule.py:_VECTOR_DB_BEAT_TASK_NAMES`). |
| `CELERY_PRIMARY_WORKER_LOCK_TIMEOUT` | TTL cadence for the primary-worker singleton lock. |
| `CELERY_WORKER_PRIMARY_CONCURRENCY`, `CELERY_WORKER_SCHEDULED_TASKS_CONCURRENCY`, etc. | Per-worker thread-pool sizes, read into each `configs/<worker>.py` (e.g. `configs/scheduled_tasks.py:worker_concurrency`). |
| `LOG_LEVEL` | Global worker log level, overridable per-process by an explicit `--loglevel` CLI flag (`app_base.py:_resolve_effective_loglevel`). |
| `IGNORED_SYNCING_TENANT_LIST` | Tenants Beat skips when generating the self-hosted-style per-tenant schedule (`apps/beat.py:_generate_schedule`). |
| `ENABLE_OPENSEARCH_INDEXING_FOR_ONYX`, `ONYX_DISABLE_VESPA` | Gate which document-index readiness probe workers wait on at startup (`app_base.py:wait_for_document_index_or_shutdown`). |

---

## 3. Data model

### Postgres tables

- `TaskQueueState` (`onyx/db/models.py`, accessed through `onyx/db/tasks.py`):
  one row per submitted task, tracked by `task_name`/`task_id`/`status`
  (`TaskStatus.PENDING/STARTED/SUCCESS/FAILURE`). `db/tasks.py:register_task`,
  `mark_task_as_started_with_id`, `mark_task_as_finished_with_id`,
  `check_task_is_live_and_not_timed_out`.
- `SyncRecord` (`onyx/db/models.py`, via `onyx/db/sync_record.py`): one row per
  sync attempt against an entity (`entity_id` + `SyncType`, e.g. `PRUNING`).
  `insert_sync_record` cancels any prior `IN_PROGRESS` record for the same
  entity/type before creating the new one (`db/sync_record.py:insert_sync_record`).
- `BackgroundError` (`onyx/db/models.py:BackgroundError`, via
  `onyx/db/background_error.py:create_background_error`): a message plus an
  optional `cc_pair_id`. Written through
  `onyx/background/error_logging.py:emit_background_error`, which swallows
  `IntegrityError` (e.g. the `cc_pair_id` was deleted concurrently) by retrying
  the insert with `cc_pair_id=None`. `emit_background_error`
  is called from exactly two places: `ee/onyx/background/celery/tasks/external_group_syncing/tasks.py`
  and `ee/onyx/external_permissions/confluence/group_sync.py`. No admin API or
  frontend route reads `BackgroundError` back out (unverified further; a search
  of `onyx/server` and `ee/onyx/server` found none). See §9.

### Redis key patterns

Every connector-scoped key is namespaced per tenant through the standard Redis
client factory and, within a tenant, per `cc_pair_id` via the `RedisConnector`
family in `onyx/redis/` (`redis_connector_prune.py`, `redis_connector_delete.py`,
`redis_connector_doc_perm_sync.py`, `redis_connector_ext_group_sync.py`,
`redis_document_set.py`, `redis_usergroup.py`).

| Pattern | Example owner | TTL | Meaning |
|---|---|---|---|
| `<prefix>_fence_<id>` | `RedisConnectorPrune.FENCE_PREFIX` (`redis_connector_prune.py`) | 7 days (`FENCE_TTL`) | The task is in progress. Holds a JSON payload (submitted time, celery task id, progress). Presence is the source of truth for "is this running". |
| `<prefix>_generator_progress_<id>` | `redis_connector_prune.py:GENERATOR_PROGRESS_PREFIX` | tied to fence lifecycle | Running count of work items produced by the generator task. |
| `<prefix>_generator_complete_<id>` | `redis_connector_prune.py:GENERATOR_COMPLETE_PREFIX` | tied to fence lifecycle | Set once the generator finishes fanning out; its int payload is the starting item count. |
| `active_fences` (a Redis set) | `OnyxRedisConstants.ACTIVE_FENCES` (`onyx/configs/constants.py`) | n/a (set membership) | A lookup table of every fence key currently believed active, across pruning, deletion, doc-permission sync, external-group sync, document sync, and docprocessing. Beat-driven checker tasks (`check_for_pruning`, its siblings) scan this set instead of doing a `KEYS`/`SCAN` over the whole keyspace, then re-verify each key still exists before trusting it. |
| `da_lock:primary_worker` | `OnyxRedisLocks.PRIMARY_WORKER` | touched every `CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 8`s | Singleton lock so only one primary worker instance is active. |
| `da_lock:check_prune_beat`, `da_lock:check_vespa_sync_beat`, etc. | `OnyxRedisLocks.*` | short | Per-checker-task locks (`lock_beat` in `check_for_pruning`) so overlapping beat firings of the same checker don't run concurrently. |
| `signal:block_validate_indexing_fences`, `signal:block_validate_pruning_fences` | `OnyxRedisSignals.*` | a few minutes | Rate-limits the (expensive) fence-validation pass to run less often than the checker task itself. |
| `onyx:celery:beat:heartbeat` | `ONYX_CELERY_BEAT_HEARTBEAT_KEY` | short | Touched by the `celery_beat_heartbeat` task (dispatched by Beat, run on Primary) so an external watchdog can detect a dead Beat process. |
| `da_lock:try_creating_prune_generator_task` (via `DANSWER_REDIS_FUNCTION_LOCK_PREFIX`) | `pruning/tasks.py:try_creating_prune_generator_task` | 30s | A short-lived mutual-exclusion lock (not a fence) guarding the create-generator-task critical section, since pruning can be triggered by both Beat and a direct API call. |

---

## 4. How it works

### 4.1 Beat: turning "what should run" into a schedule

`DynamicTenantScheduler` (`apps/beat.py:DynamicTenantScheduler`) is a
`PersistentScheduler` whose `tick()` (`apps/beat.py:tick`) checks every
`RELOAD_INTERVAL` (60s) whether the schedule needs regenerating, via
`_try_updating_schedule` (`apps/beat.py:_try_updating_schedule`):

1. Read all tenant ids (`get_all_tenant_ids`).
2. Read the current `beat_multiplier` from `OnyxRuntime.get_beat_multiplier()`,
   falling back to `CLOUD_BEAT_MULTIPLIER_DEFAULT = 8.0` on error
   (`beat_schedule.py:CLOUD_BEAT_MULTIPLIER_DEFAULT`).
3. Call `_generate_schedule(tenant_ids, beat_multiplier)`
   (`apps/beat.py:_generate_schedule`):
   - Under `MULTI_TENANT`, add the cloud-only system-wide tasks from
     `get_cloud_tasks_to_schedule(beat_multiplier)`, which multiplies each
     per-tenant *template*'s schedule interval by `beat_multiplier`
     (`beat_schedule.py:generate_cloud_tasks`). This is the throttle: raising the
     multiplier slows down how often each tenant's checker tasks fire, without a
     deploy, because `OnyxRuntime.get_beat_multiplier()` reads a runtime-adjustable
     value.
   - For every tenant, add one schedule entry per task in
     `get_tasks_to_schedule()`, named `f"{task_name}-{tenant_id}"`, with
     `tenant_id` stamped into the entry's `kwargs`
     (`apps/beat.py:_generate_schedule`, the per-tenant loop). This is the one
     place that guarantees `tenant_id` reaches `TenantAwareTask`; a direct
     `send_task` call elsewhere must set it explicitly (see §5).
4. Compare the new schedule's task names against the current one
   (`_compare_schedules`); if unchanged and the multiplier is unchanged, skip the
   update.

Under `MULTI_TENANT`, per-tenant checker tasks are **not** scheduled individually
per tenant in the cloud; only the cloud-wide, fixed set in `beat_cloud_tasks` and
the *cloud generator task* pattern (`make_cloud_generator_task`,
`OnyxCeleryTask.CLOUD_BEAT_TASK_GENERATOR`) fan a single templated beat entry out
per tenant at task-dispatch time rather than at schedule-generation time. This
detail is in `beat_schedule.py` and is why `beat_multiplier` matters even though
the self-hosted path (`tasks_to_schedule`) does not multiply anything.

### 4.2 The generator-task pattern (pruning as the worked example)

Most "sync this whole cc_pair" tasks split into a cheap dispatcher, a heavier
generator, and a set of lightweight fan-out subtasks, tied together by a fence:

1. **Checker task** (`check_for_pruning`, run on Primary, beat-scheduled every
   20s per `background/README.md`): acquires `lock_beat`
   (`OnyxRedisLocks.CHECK_PRUNE_BEAT_LOCK`), scans due cc_pairs, and for each one
   calls `try_creating_prune_generator_task`.
2. **Dispatcher** (`pruning/tasks.py:try_creating_prune_generator_task`): takes
   a short-lived mutual-exclusion lock, checks that no fence, deletion, or
   permission sync is already active for the cc_pair, inserts a `SyncRecord`,
   sets the fence (`redis_connector.prune.set_fence(payload)`), and only then
   calls `celery_app.send_task(OnyxCeleryTask.CONNECTOR_PRUNING_GENERATOR_TASK, ...)`
   onto the `connector_pruning` queue (Heavy worker). The fence is set *before*
   the task is confirmed sent, and the task id is written back into the fence
   payload once `send_task` returns.
3. **Generator task** (`connector_pruning_generator_task`, runs on Heavy):
   does the actual work of walking the connector and fanning out lightweight
   deletion subtasks (queue `connector_deletion`, Light worker), updating
   `generator_progress`/`generator_complete` as it goes.
4. **Monitor** (`monitor_ccpair_pruning_taskset`, invoked from inside
   `check_for_pruning` for every key found in `ACTIVE_FENCES` that matches the
   prune fence prefix): reads progress/completion state and, once every
   fanned-out subtask has drained from the taskset, clears the fence and the
   `SyncRecord`.
5. **Fence validation** (`validate_pruning_fences` /
   `validate_pruning_fence`, rate-limited by
   `signal:block_validate_pruning_fences`): cross-checks each active fence
   against what Celery itself reports as queued/reserved/unacked for the
   relevant queues (`celery_get_unacked_task_ids`, `celery_get_queued_task_ids`
   in `celery_redis.py`). If a fence's payload fails to parse (schema drift), it
   is reset rather than left stuck. This is the mechanism by which a fence whose
   generator task died without cleaning up gets recovered without manual
   intervention; `pruning/tasks.py:validate_pruning_fence` has a comment
   pointing at `validate_indexing_fence` as the canonical description of the
   flow. `[[indexing-pipeline]]` documents the indexing-specific version of this
   same pattern; `[[permission-sync]]` documents the doc-permission and
   external-group-sync versions.

### 4.3 Task startup and teardown, mechanically

`before_task_publish` stamps `enqueued_at` into the message headers
(`app_base.py:on_before_task_publish`), which lets a worker compute queue wait
time. `TenantAwareTask.__call__` sets the tenant contextvar, runs the task, and
resets it. `task_prerun` clears per-task logging context vars so a pruning
task's `[CC Pair:]` log prefix cannot leak into the next task run on the same
thread. `task_postrun` removes the task id from whichever Redis taskset it
belongs to (matched by id prefix); `task_revoked` does the equivalent cleanup for
tasks that never ran at all (expired before execution).

### 4.4 Craft scheduled tasks

The `scheduled_tasks` worker (`apps/scheduled_tasks.py`) autodiscovers only
`onyx.background.celery.tasks.scheduled_tasks` and is deliberately isolated onto
its own queue and app: the docstring in `apps/scheduled_tasks.py` explains this
is so long-running headless-agent task runs do not compete for Heavy's slots
(pruning, permission sync, CSV export). It uses `worker_pool = "threads"` and
`worker_prefetch_multiplier = 1` like every other worker
(`configs/scheduled_tasks.py`).

---

## 5. Contracts and invariants

1. **Every task that reaches a worker must carry `tenant_id` in its kwargs.**
   `TenantAwareTask.__call__` falls back to `POSTGRES_DEFAULT_SCHEMA` when it is
   missing, which is not an error, it is a silent wrong-tenant execution risk.
   Beat's per-tenant schedule stamps this automatically
   (`apps/beat.py:_generate_schedule`); any task sent directly with
   `celery_app.send_task` or `.apply_async` from application code must pass it
   explicitly. See `backend/AGENTS.md`: "direct task sends must propagate it
   themselves (`TenantAwareTask` silently falls back to the default schema when
   it's absent)."
2. **Tasks must be idempotent.** Celery can redeliver a task (worker crash,
   `acks_late`, requeue on connection loss). Nothing in this layer deduplicates
   at the broker level; idempotency is the task author's responsibility.
3. **Never enqueue a task without an expiration.** Quoting `backend/AGENTS.md`:
   "Never enqueue a task without an expiration. Always supply `expires=` when
   sending tasks, either from the beat schedule or directly from another task."
   Every entry in `beat_schedule.py` sets `expires` via `BEAT_EXPIRES_DEFAULT`;
   a new direct `send_task` call needs the same.
4. **A fence must always be released or expire.** Every `FENCE_TTL` in this
   codebase is 7 days, a defensive backstop, not the intended recovery path.
   The intended path is the checker task's fence-validation pass (§4.2). A
   change that adds a new fenced flow without wiring it into a `check_for_*`
   validation loop leaves that fence with only the 7-day TTL as a safety net.
5. **A task must not hold a DB session across a long external call.** The
   concrete example is in `ee/onyx/background/celery/tasks/external_group_syncing/tasks.py`:
   a comment there explains that a DB connection can be killed by Postgres's
   `idle_in_transaction_session_timeout` during a long external API call, and
   the fix was to move stale-row cleanup to the *start* of the next cycle
   instead of depending on the *end* of a cycle that might never finish. Prefer
   short-lived sessions opened right before a commit over one session held for
   the duration of a task.
6. **A worker's `-Q` queue list must match every queue name callers send to.**
   There is no assertion enforcing this; a mismatch means tasks queue in Redis
   and are never picked up by any worker, with no error raised anywhere. See §9.
7. **Always use `@shared_task`, not `@celery_app.task`,** so a task is
   registered on whichever app imports its module rather than bound to one app
   at definition time (`backend/AGENTS.md`).
8. **Task time limits do not work.** All workers run thread pools, not
   processes, and Celery's `time_limit`/`soft_time_limit` machinery depends on
   process-level signals. `backend/AGENTS.md`: "Since all tasks are executed in
   thread pools, the time limit features of Celery are silently disabled and
   won't work. Timeout logic must be implemented within the task itself." (Some
   tasks, e.g. `check_for_pruning`, still catch `SoftTimeLimitExceeded`
   defensively, but nothing raises it under the thread-pool executor.)
9. **DB operations belong under `onyx/db/` or `ee/onyx/db/`.** Task modules
   call into `onyx/db/tasks.py`, `db/sync_record.py`, `db/background_error.py`,
   etc.; they do not run ad hoc queries inline (`backend/AGENTS.md`).

---

## 6. Relationships

**Depends on**
- [[multi-tenancy]]: `TenantAwareTask`, `CURRENT_TENANT_ID_CONTEXTVAR`, and
  `DynamicTenantScheduler`'s per-tenant fan-out are the tenant-isolation
  mechanism every background task runs inside.
- [[editions-and-gating]]: `versioned_apps/*.py` and
  `fetch_versioned_implementation` are how EE worker/task variants replace CE
  ones at import time.
- [[document-index]]: `wait_for_document_index_or_shutdown` gates worker
  startup; `DISABLE_VECTOR_DB` changes which task modules and beat entries even
  exist.

**Depended on by**
- [[indexing-pipeline]]: docfetching/docprocessing queues, the indexing fence
  and generator-task pattern this document generalizes.
- [[permission-sync]]: doc-permission and external-group-sync fences, run on
  Heavy, monitored the same way as pruning.
- [[connectors]] and [[cc-pairs-and-credentials]]: pruning, deletion, and
  hierarchy-fetching all run as Celery tasks scoped to a cc_pair.
- [[file-store-and-user-files]]: the `user_file_processing` worker and its three
  queues; `task_utils.py`'s claim-and-mark helpers back the `NO_VECTOR_DB` synchronous
  fallback path.
- [[chat-persistence]]: `chat_ttl_deletion` queue (Light worker).
- [[observability]]: `monitoring` worker, Prometheus metrics, `BackgroundError`
  rows.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new task | which worker's `-Q` list (supervisord.conf and every relevant Helm `celery-worker-*.yaml`) includes its queue; whether it needs an `expires=`; whether it needs `tenant_id` propagated explicitly if not beat-scheduled |
| changes a queue name (an `OnyxCeleryQueues` constant) | every `-Q` list in `backend/supervisord.conf` and `deployment/helm/charts/onyx/templates/celery-worker-*.yaml`; every `send_task`/`apply_async` call that references the old name; the queue-length metric mapping in `tasks/monitoring/tasks.py:_collect_queue_metrics` |
| changes the beat schedule (`beat_schedule.py` or the EE equivalent) | whether the task is per-tenant or cloud-wide (wrong list changes whether `beat_multiplier` applies); the `expires` value; whether `DISABLE_VECTOR_DB` filtering needs the task name added to `_VECTOR_DB_BEAT_TASK_NAMES` |
| changes a fence or lock (key name, TTL, payload schema) | the checker task's fence-validation pass for that fence family (mirror `validate_pruning_fences`); `on_task_postrun`/`on_task_revoked` taskset cleanup, which matches on key prefix; `ACTIVE_FENCES` membership add/remove sites |
| adds a worker | its `apps/<name>.py`, `versioned_apps/<name>.py`, `configs/<name>.py`; an entry in `backend/supervisord.conf`; a Helm `celery-worker-<name>.yaml` (plus HPA/ScaledObject if it should autoscale); an entry in `background/README.md`'s worker table (keep it truthful, see §9); whether it needs an EE counterpart under `ee/onyx/background/celery/apps/` |
| touches `TenantAwareTask` or the tenant contextvar | every worker, since all of them install it as `celery_app.Task`; [[multi-tenancy]] |
| touches `app_base.py` signal handlers | logging prefixes leaking across tasks, taskset cleanup correctness for every fenced flow, not just the one you're testing |

---

## 8. How to verify a change

### Tests

```bash
# Unit tests for scheduling / beat-adjacent logic
cd backend && uv run pytest tests/unit -k "beat or periodic_poller or celery"
# Integration tests exercise the fence/generator pattern end to end for a
# specific feature (indexing, pruning, permission sync); see those components'
# own §8 for the concrete paths, e.g. tests/integration -k pruning
```

`backend/tests/unit/onyx/background/test_periodic_poller_license_reclaim.py`
exercises `periodic_poller.py:_build_periodic_tasks` directly and is a concrete,
existing example of testing this layer's scheduling logic in isolation from
Celery itself.

Prefer an integration test at the owning component (indexing, pruning,
permission sync) over a new generic Celery test; this document's job is the
shared machinery, not feature correctness.

### Manual reproduction

1. Confirm workers are up: `tail -f backend/log/celery_primary_debug.log`,
   substituting `celery_light`, `celery_heavy`, `celery_beat`, etc. for the
   worker you care about (root `AGENTS.md`: "All Onyx services... will be
   tailing their logs to this file").
2. To inspect a queue's backlog, use the same Redis primitives the monitoring
   task uses: `celery_get_queue_length` / `celery_get_unacked_task_ids`
   (`celery_redis.py`) are the sanctioned way to read queue depth; a raw
   `redis-cli LLEN <queue>` undercounts because Celery's Redis transport splits
   a queue across multiple priority-suffixed lists.
3. To check whether beat picked up a schedule change, watch for the
   `_try_updating_schedule - Schedule updated` log line (or, unchanged, the
   `Schedule unchanged` line) in the beat log.
4. To find a stuck fence by hand:
   `PGPASSWORD=... psql ... -c "select * from sync_record where sync_status='IN_PROGRESS' order by id desc limit 20;"`
   cross-referenced with `SMEMBERS active_fences` in Redis for the same tenant.

### What "working" looks like

- A newly due connector's `check_for_indexing` (or `_pruning`, etc.) run picks it
  up within one beat cycle plus queue latency.
- The fence for a completed sync is gone from `active_fences` and its
  `SyncRecord` is no longer `IN_PROGRESS`.
- No task silently vanishes: every `send_task` call's queue is consumed by at
  least one running worker (cross-check against the table in §2).

---

## 9. Footguns

- **`apps/background.py` does not exist**, despite `background/README.md`
  describing a "Background (consolidated)" worker that runs every queue except
  `celery`. There is no such file in `onyx/background/celery/apps/`, nothing
  references it in `supervisord.conf`, the Helm templates, or
  `versioned_apps/`. Do not build against that README entry; it does not
  reflect the current deployment topology.
- **The README's worker-to-queue table is out of date in three ways**: it is
  missing the `scheduled_tasks` worker, and it understates both Light's queues
  (missing `index_reclaim`, `opensearch_migration`, `chat_ttl_deletion`) and
  Heavy's queues (missing `connector_hierarchy_fetching`, `capability_checks`).
  `backend/AGENTS.md`'s worker table is closer to correct (it does list
  `scheduled_tasks`) but doesn't enumerate queues per worker either. Trust
  `supervisord.conf` and the Helm chart's `-Q` flags, not either markdown table,
  when queue membership matters.
- **The Helm chart's primary worker passes `-Q celery,periodic_tasks`**, but no
  `OnyxCeleryQueues` constant, beat entry, or `send_task` call in this codebase
  targets a `periodic_tasks` queue. Either it is dead configuration left over
  from a prior design, or something routes to it outside what a code search
  surfaces; this document could not verify which. Do not assume tasks sent to
  `periodic_tasks` will be silently dropped or silently consumed; check before
  relying on it either way.
- **A queue name typo is invisible.** If a task is sent to a queue no running
  worker's `-Q` list includes, it queues in Redis forever (or until its
  `expires`) with no error, no log on the sending side, and no exception
  anywhere. The only symptom is "this never happened." Cross-check §2's table
  whenever you touch a queue name.
- **`monitoring`'s queue-length metrics do not cover every queue.** `_collect_queue_metrics`
  (`tasks/monitoring/tasks.py`) maps roughly twenty queues to Prometheus
  metrics, but `scheduled_tasks` is not among them, so a backlog on that queue
  produces no queue-length signal today.
- **`BackgroundError` is not a general failure-surfacing mechanism.** It is
  written from exactly two call sites (both under `ee/onyx`, both in
  external-group/permission-sync code), and nothing reads it back through an
  API or the frontend. A new task that calls
  `emit_background_error` expecting an admin to see it should verify there is
  in fact a consumer, rather than assuming one exists because the table does.
- **Time limits are decorative.** `soft_time_limit`/`time_limit` kwargs on
  `@shared_task` do not fire under the thread-pool executor every worker uses;
  a task that needs a hard timeout must implement it itself (watchdog pattern,
  deadline check inside a loop, etc.).
- **Worker code changes need a manual restart.** There is no file-watcher
  auto-reload for Celery workers; `backend/AGENTS.md` says to ask the user to
  restart the worker after any change to task or app code.
