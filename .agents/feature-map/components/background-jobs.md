# Background Jobs (Celery)

> The shared asynchronous machinery: worker apps, queues, the beat schedule,
> tenant context on each task, fences and task conventions. It also owns the
> two flows that remove documents, pruning and connector deletion.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE adds worker and beat entries through the versioned-app
mechanism. Cloud fans per-tenant work out through a generator task.

## Callers

The interface is a set of conventions, not one API: tasks on
`background/celery/apps/app_base.py:TenantAwareTask`, beat templates in
`background/celery/tasks/beat_schedule.py`, queues in
`configs/constants.py:OnyxCeleryQueues`, and the checker, generator and monitor
pattern with a fence.

- **Developers** add periodic tasks, queues, workers and fenced flows (see
  Recipes). A mistake here fails with no error: messages wait in a queue until
  they expire, or a task runs against the default schema. They must keep
  [[#queue-needs-worker]], [[#default-acks-late]], [[#fence-needs-validator]],
  [[#beat-interval-stretched]], [[#cloud-timedelta-schedule]],
  [[#task-kwargs-defaults]] and [[multi-tenancy#celery-task-tenant-kwarg]].
- **Components that run their flows here:** [[indexing-pipeline]],
  [[permission-sync]], [[document-index]], [[file-store-and-user-files]],
  [[connector-capability-checks]] and [[craft-scheduled-tasks]]. They rely on
  the tenant context, the ack mode and the signal handlers, and keep
  [[#idempotent-tasks]] and [[#no-session-across-external-call]].
- **[[cc-pairs-and-creds]]** starts pruning and connector deletion from the
  connector page. Architecture gives the deletion flow.

## Scope

This component owns the worker apps and the versioned stubs that workers start
from, the per-worker configs, the beat schedule and its dynamic tenant
scheduler, `TenantAwareTask`, the signal handlers, and the readiness and
liveness probes. It owns the fence and taskset pattern, `SyncRecord`,
`BackgroundError` and `TaskQueueState`. It owns the pruning and connector
deletion task flows and the shared document cleanup task they use.

The backend AGENTS file lists the workers and their roles, and states the task
rules that are not repeated here: `@shared_task`, `expires=` on every send, and
Celery time limits that do nothing in thread pools. The `-Q` flags in the
supervisord config and in the Helm worker templates are the truth for which
worker reads which queue.

Its neighbours own:
- [[indexing-pipeline]]: docfetching and docprocessing.
- [[permission-sync]]: doc and group sync, which use a lease row, not a fence.
- [[document-index]]: the metadata sync, the reindex port and the index reclaim.
- [[connectors]]: the slim listing that pruning reads, and its contract.
- [[multi-tenancy]]: the rule that every task carries a tenant.
- [[observability]]: Prometheus metrics and the monitoring tasks.
- [[fleet-telemetry]]: the collection pass that reads job rows.

## Architecture

**Workers.** Each worker is a Celery app in
`background/celery/apps/<name>.py`. Processes start from
`background/celery/versioned_apps/<name>.py`, which loads the EE app when the
build ships EE code (`fetch_versioned_implementation`). Every app sets
`background/celery/apps/app_base.py:TenantAwareTask` as its task class, and all
workers use thread pools.

**Where Celery does not run.** The Helm chart with `vectorDB.enabled` off and
the Lite compose overlay start no Celery. There, a poller in the API server runs
user-file recovery and a few periodic tasks
(`background/periodic_poller.py:start_periodic_poller`). Celery runs with
`DISABLE_VECTOR_DB` only when an operator starts workers with the flag set
([[#vector-db-beat-tasks]]). A worker that is down or a queue that is backed up
shows only as a stale "last indexed" or "last synced" time; queue depth is in
the monitoring ([[observability]]).

**Beat.** `background/celery/apps/beat.py:DynamicTenantScheduler` generates the
schedule every 60 seconds and replaces it only when it or the multiplier
changed.
- Self-hosted: it adds one entry per template and tenant, with `tenant_id`
  in the kwargs (`background/celery/apps/beat.py:_generate_schedule`).
- Cloud (`MULTI_TENANT`): the per-tenant list is empty. Each template becomes
  one `cloud_beat_task_generator` entry
  (`backend/onyx/background/celery/tasks/beat_schedule.py:make_cloud_generator_task`), which
  sends the real task once per tenant with `tenant_id` set
  (`ee/onyx/background/celery/tasks/cloud/tasks.py:cloud_beat_task_generator`).
  The interval is multiplied by a runtime `beat_multiplier`, so an operator can
  slow every tenant's checks without a deploy ([[#beat-interval-stretched]]).
  Two template options steer the fan-out. `skip_gated` (default true) skips
  gated tenants. `work_gated` (default false) skips tenants with no recent
  activity when tenant work gating is on; such a task reaches an inactive
  tenant only on a full-fanout cycle.
- System-wide cloud tasks (`beat_cloud_tasks`) run once, not per tenant, and
  the multiplier does not stretch them. Their Celery task names start with the
  cloud prefix, so `on_task_postrun` skips its tenant taskset cleanup for them.

**The checker, generator and monitor pattern.** Pruning is the example.

```
check_for_pruning (beat, primary)          takes lock_beat; finds due pairs
  try_creating_prune_generator_task        dispatch lock; skip if prune or delete
                                           fenced, doc perm sync open, or pair
                                           PAUSED/DELETING; insert SyncRecord;
                                           set fence; send generator task
connector_pruning_generator_task (heavy)   slim listing of live IDs, diff against
                                           Postgres, send one cleanup task per
                                           missing ID, record progress
monitor_ccpair_pruning_taskset             called by check_for_pruning per fence
                                           in ACTIVE_FENCES; clears the fence and
                                           SyncRecord when the taskset drains
validate_pruning_fences                    rate-limited; resets a fence whose task
                                           Celery does not hold, and fails its
                                           SyncRecord (fail_orphaned_prune_records)
```

On a self-hosted start, the primary worker runs
`background/celery/tasks/pruning/tasks.py:reset_prune_fences_on_startup`
(under `MULTI_TENANT` it skips the Redis reset). It
fails every running prune record, then clears every prune fence. It holds the
prune dispatch lock throughout, with a longer timeout, and reacquires it
between the two steps. Without the lock, a prune that an API call starts during
the reset is failed before its fence exists, or runs with no fence. Do not split
the function or drop the lock.

**Pruning without a slim listing.** A connector with no slim listing is
pruned by a full load or poll
(`background/celery/celery_utils.py:extract_ids_from_runnable_connector`). It
installs a tracking raw-file callback, so tabular connectors can stage CSVs, and
reaps them in a `finally` block, because no index attempt exists for the normal
staging reapers. Which IDs stay out of the prune set is the connector contract
in [[connectors]].

**Connector deletion.** `background/celery/tasks/connector_deletion/tasks.py:check_for_connector_deletion_task`
handles each pair in `DELETING`. `try_generate_document_cc_pair_cleanup_tasks`
raises `TaskDependencyError` while indexing is in progress, a port attempt is
active (it also asks the port to cancel), a prune is fenced, or a doc
permission sync is open. On the first refusal the beat revokes those tasks and
sets the pair's stop signal. After the stop timeout it resets the prune and
cancels the open doc and group sync attempts. Then it
sends cleanup tasks in batches of `DOCUMENT_INDEX_SYNC_MAX_TASKS`, and
`monitor_connector_deletion_taskset` sends the next batch when one drains. It
fails the deletion when a batch does not lower the linked count.
For a File connector, the route that starts the deletion
(`server/manage/administrative.py:create_deletion_attempt_for_connector_id`)
deletes the uploaded files from the file store at once, before any cleanup task
runs.

**The cleanup task.** `background/celery/tasks/shared/tasks.py:document_by_cc_pair_cleanup_task`
serves both flows. If this pair is the document's last owner and no other
source keeps it, it deletes the chunks from both index generations and the
`Document` row. Otherwise it removes this pair's link, bumps `last_modified`,
and updates the chunks' ACL and cc-pair IDs. On its last retry it removes the
link anyway and marks the document modified, so the metadata sync corrects
the index.

**Other periodic flows.** Each owner documents its flow; this list says where
it runs.
- Craft scheduled tasks ([[craft-scheduled-tasks]]): the dispatcher and the
  stuck-run sweeper run on the primary queue on purpose. Only
  `run_scheduled_task` uses the `scheduled_tasks` queue, so a full executor
  pool cannot stall dispatch.
- Capability checks ([[connector-capability-checks]]): the run tasks, the
  stale-run check, the scheduled check, and the cleanup of stale draft
  credentials and old runs.
- Hierarchy fetch: `check_for_hierarchy_fetching` runs hourly under a beat
  lock and sends a fetch for each active, indexed pair whose
  `last_time_hierarchy_fetch` is older than `HIERARCHY_FETCH_INTERVAL_SECONDS`.
  [[connectors]] owns the hierarchy that the fetch loads.
- License reclaim ([[billing]]): the license middleware schedules
  `reclaim_license_task` when the cache backend is Redis. Otherwise
  `background/periodic_poller.py:_run_license_reclaim` runs it on the poller's
  cadence.

**Signals.** `on_before_task_publish` stamps the enqueue time. `task_prerun`
clears the per-task log context. `task_postrun` removes a finished task from its
Redis taskset by task-ID prefix. Only the light worker also drains the
document-sync taskset on `task_revoked`, because an expired task never reaches
`task_postrun` (`background/celery/apps/app_base.py:on_task_revoked`).

## Contracts and traps

1. `send-expires` **Give each new send `expires=`.** The backend AGENTS file
   requires it, and every beat entry sets it. Many sends at the verified commit
   omit it. Some do so on purpose: the docfetching and docprocessing sends wait
   in queues for hours, and the heartbeat check and batch reissue recover a
   lost one. Others, such as the pruning generator send and several
   API-triggered sends, give no reason. Do not copy a send without checking why
   it omits `expires`.
2. `default-acks-late` **The default ack mode is late.**
   `background/celery/configs/base.py` sets `task_acks_late`, and the broker
   redelivers an unacked task after `visibility_timeout`. A task that can run
   longer must set `acks_late=False`, as docfetching, docprocessing, pruning,
   the permission syncs and the Craft scheduled run do. Otherwise a second
   worker runs the same task while the first is still running.
3. `queue-needs-worker` **A queue must be in some worker's `-Q` list.** A task
   sent to a queue that no worker reads waits until it expires, with no error
   anywhere. Change `backend/supervisord.conf` and every Helm worker template
   (`deployment/helm/charts/onyx/templates/`) together.
4. `no-session-across-external-call` **Do not hold a database session across a
   long external call.** Postgres kills an idle-in-transaction session, and
   under fan-out the held sessions use up the pool. Read, close, call, then
   write in a new session. The cleanup task, the metadata sync and the group
   sync follow this.
5. `fence-needs-validator` **A new fence needs a validator.** Fences carry a
   7-day TTL as a backstop only. A fenced flow must have a validation pass, like
   `background/celery/tasks/pruning/tasks.py:validate_pruning_fences`, or a lost
   task blocks the pair for a week. Add the fence key to `ACTIVE_FENCES`, so
   checkers find it without a key scan.
6. `cloud-skips-gated` **A new cloud template skips gated tenants by default.**
   A cleanup task that must also run for gated tenants sets
   `skip_gated: False` in its template in
   `background/celery/tasks/beat_schedule.py`, as connector deletion, index
   reclaim and the cleanup tasks do.
7. `vector-db-beat-tasks` **A beat entry that needs the vector DB goes in
   `backend/onyx/background/celery/tasks/beat_schedule.py:_VECTOR_DB_BEAT_TASK_NAMES`.**
   With `DISABLE_VECTOR_DB`, the entry is dropped from the schedule and its
   task module from worker autodiscovery
   (`background/celery/apps/app_base.py:filter_task_modules`).
8. `idempotent-tasks` **Tasks must be idempotent.** Late acks, retries and
    revokes can run a task twice or stop it halfway. The cleanup task commits
    the link removal first, so a retry finishes the index write.
9. `beat-interval-stretched` **A long beat interval is not what it says.** On
   cloud, `backend/onyx/background/celery/tasks/beat_schedule.py:generate_cloud_tasks`
   multiplies every template interval by `beat_multiplier`, and
   `CLOUD_BEAT_MULTIPLIER_DEFAULT` is 8. A `timedelta(days=1)` template fires
   about every 8 days unless an operator sets the Redis value. Also,
   `background/celery/apps/beat.py:DynamicTenantScheduler._try_updating_schedule`
   rebuilds every entry with no `last_run_at`, so Celery sets it to the rebuild
   time and each interval starts again. This happens on each beat start (Helm keeps the schedule file
   on an `emptyDir`) and on each schedule change. A task whose interval is
   longer than beat's uptime does not run. For a daily task, use a
   short-interval checker that reads its own last-run time, as
   `background/celery/tasks/hierarchyfetching/tasks.py:_is_hierarchy_fetching_due`
   does. On cloud an hourly checker fires about every 8 hours, so a daily task
   can run up to that much late.
10. `cloud-timedelta-schedule` **A cloud template must use a `timedelta`
    schedule.**
    `backend/onyx/background/celery/tasks/beat_schedule.py:generate_cloud_tasks`
    multiplies each template's schedule by a float. A `crontab` raises
    `TypeError` under `MULTI_TENANT`.
    `background/celery/apps/beat.py:DynamicTenantScheduler.tick` logs and
    swallows the error, so the whole schedule stops updating. The
    `scheduled-eval-pipeline` template uses a `crontab` and is safe only on
    self-hosted.
11. `task-kwargs-defaults` **Add a task kwarg with a default.** Task kwargs have
    no shared schema: each `send_task` call site builds them by hand. During a
    rolling deploy, an old worker can receive a message from a new sender, and
    a new worker can receive a message from an old sender. Give a new kwarg a
    default, and send an optional kwarg only when it is set, as the
    docprocessing send does for `is_backfill`.

## Known issues

- **`backend/onyx/background/README.md` is out of date.** It lists a
  consolidated worker that no file defines, omits the `scheduled_tasks` worker,
  and lists fewer queues than the supervisord config.
- **The Helm primary worker reads a `periodic_tasks` queue** that no task or beat
  entry sends to. It looks like dead configuration.
- **`BackgroundError` has writers but no reader.** Only the EE group sync code
  writes it, and no route returns it. Do not expect an admin to see it.
- **A docstring points to a removed function.**
  `background/celery/tasks/pruning/tasks.py:validate_pruning_fence` refers to
  `validate_indexing_fence`. Indexing replaced its Redis fence with the attempt
  row.

## Dependencies

- [[multi-tenancy]]: the tenant contextvar and tenant-scoped Redis clients.
- [[editions-and-gating]]: the versioned apps and EE beat entries.
- [[document-index]]: workers wait for the index at startup, and the cleanup
  task writes through it.
- [[connectors]]: the slim listing that pruning diffs against.

## Recipes

- `periodic-task` **A periodic task.** Copy the hierarchy-fetch checker
  (`background/celery/tasks/hierarchyfetching/tasks.py`); list the templates in
  `background/celery/tasks/beat_schedule.py`. Add a name to
  `configs/constants.py:OnyxCeleryTask`. Write the task with `@shared_task` and
  a `tenant_id` kwarg ([[multi-tenancy#celery-task-tenant-kwarg]]); a
  system-wide cloud task takes none. Add its module to the `autodiscover_tasks`
  list of the worker app that reads its queue, such as
  `background/celery/apps/primary.py`; a module missing there is never
  registered, and its messages wait until they expire. Add a template with a
  queue, a priority, `expires` and a `timedelta` schedule
  ([[#beat-interval-stretched]], [[#cloud-timedelta-schedule]]). Decide
  `skip_gated` and `work_gated`. Add it to `_VECTOR_DB_BEAT_TASK_NAMES` if it
  needs the index. If it must also run where no Celery runs (see Architecture),
  add a `_PeriodicTaskDef` to
  `background/periodic_poller.py:_build_periodic_tasks` as well, as
  `oauth-provider-cleanup` does. A daily task with no per-row last-run column
  keeps its last-run time in a `KVStore` row, as
  `background/periodic_poller.py:_try_claim_task` does. An EE-only task goes in
  `ee/onyx/background/celery/tasks/beat_schedule.py`: `ee_beat_task_templates`
  for cloud and `ee_tasks_to_schedule` for self-hosted. A system-wide cloud task
  goes in `beat_cloud_tasks`. Copy
  `backend/tests/unit/onyx/background/celery/tasks/test_port_wiring.py` to check
  that the entry is scheduled and a worker registers the task.
- `add-queue` **A queue.** Add it to `OnyxCeleryQueues`, to the `-Q` list in
  `backend/supervisord.conf`, and to the matching Helm worker template.
- `add-worker` **A worker.** Copy the light worker: its app, versioned app and
  config modules, a supervisord program, and a Helm template. Update the worker
  table in the backend AGENTS file.
- `investigate-task-not-running` **Investigate a task that does not run.** Look
  for the "Schedule updated" or "Schedule unchanged" beat log line; it gives the
  task count and the `beat_multiplier`. Read the queue depth with
  `background/celery/celery_redis.py:celery_get_queue_length`; a raw `LLEN`
  undercounts, because the transport splits a queue into one list per priority.
  Check that a worker's `-Q` list holds the queue.
- `investigate-stuck-fence` **Investigate a stuck fence.** Compare the
  `sync_record` rows with status `IN_PROGRESS` against the tenant's Redis
  `active_fences` set. A fence with no live task is what the validator resets; a
  fence that stays means the flow has no validator or the validator is
  rate-limited.
- `investigate-prune` **Investigate documents that a prune removed, or did not
  remove.** Start a prune by hand with
  `POST /api/manage/admin/cc-pair/{id}/prune`. The prune task logs "Pruning set
  collected" with `docs_to_remove` before it deletes.
- `investigate-deletion` **Investigate a deletion that does not finish.** Read
  the pair's `deletion_failure_message`. A deletion waits while indexing, a port
  attempt, a prune or a doc permission sync runs on the pair. A prune fence with
  no live task is a stuck fence.

## Verification

- Unit tests: `backend/tests/unit/onyx/background/`.
- External dependency tests: `backend/tests/external_dependency_unit/celery/`
  (pruning, deletion batches, pause, fence reset) and
  `backend/tests/external_dependency_unit/background/`.
- Integration tests: `backend/tests/integration/tests/pruning/` and
  `backend/tests/integration/tests/connector/`.
