# Permission Sync

> Copies permissions from a source system into Postgres: doc sync records who can
> see each document, and group sync records who is in each external group.
> [[access-control]] turns the data into query-time ACLs, and the metadata sync
> in [[document-index]] pushes it into the index.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** EE only, on the business tier. A CE deployment has no doc sync and
no group sync, and its documents are never narrowed below the access type that
an admin sets.

## User experience

- **An admin sets a connector's access type to Sync** (or Sync restricted) for a
  source that supports it. From then on, the source decides who sees each
  document, and Onyx copies that decision. The admin does not grant or revoke
  access to synced documents in Onyx.
- **A pair that starts to use Sync shows nothing at first.** For a source with
  doc sync, until the first sync writes permissions into the index, the pair
  grants no access and its documents are hidden
  (`ConnectorCredentialPair.perm_sync_pending_since`).
- **Access changes are eventual.** A user who loses access to a Drive folder
  stops seeing its documents after the next successful doc sync and the next
  metadata sync, not at once. The wait is the source's sync interval plus
  queue time.
- **The connector page shows each sync kind.** It shows the newest run, its
  counts and the time of the last success. The admin can start a sync by hand.
  The request fails with a conflict while a sync of that kind is queued or
  running, or, for doc sync, while the pair is paused. It fails with invalid
  input for a pair that is not perm-synced.
- **A source that keeps failing backs off.** After failed attempts, the beat
  waits longer before the next one, up to hours. A manual sync ignores the
  wait.
- **When it fails, access does not widen, but revocation can stall.** A failed
  doc sync leaves each document's last synced ACL. A failed group sync keeps
  last cycle's memberships, including ones the source removed, until the next
  group sync starts ([[#failed-group-sync-keeps-memberships]]).
- **An admin who picks Sync for an unsupported source**, or below the business
  tier, gets an error when saving the connector.
- **A person who has never logged in** can already hold access. Doc sync and
  group sync create a `User` row for an unknown email, so access is ready when
  that person signs up.

## Scope

This component owns the source registry and each source's doc sync and group
sync functions, the doc sync and group sync Celery tasks, the Postgres writes of
document permissions and external groups, and the attempt rows with their lease.

Its neighbours own:
- [[access-control]]: computing a document's ACL and a user's ACL from the
  synced data, the query filter, and post-query censoring
  (`censor_chunks_for_user`).
- [[document-index]]: the `needs_sync` predicate and the metadata sync task that
  writes a changed ACL into the chunks.
- [[connectors]]: the connector interfaces that fetch permissions
  (`SlimConnectorWithPermSync`, `CheckpointedConnectorWithPermSync`).
- [[connector-capability-checks]]: the named perm-sync checks a source
  registers for the connector form.
- [[cc-pairs-and-creds]]: the access type, the pairing rules, and the
  connector page.
- [[billing]]: what the Community downgrade deletes.

## Architecture

**The registry.** `ee/onyx/external_permissions/sync_params.py:_SOURCE_TO_SYNC_CONFIG`
says what each source supports. A `SyncConfig` holds up to three optional
parts. `doc_sync_config` holds the sync function, its frequency, and
`initial_index_should_sync`. When that flag is true, indexing already fetches
permissions, so doc sync waits for the first successful index.
`group_sync_config` holds the group function and whether one run serves every
cc-pair of the source. `censoring_config` filters chunks after retrieval instead
of syncing (Salesforce). The loaders import each source's code on first use, so
importing the registry does not import every SDK. Frequencies live in
`ee/onyx/configs/app_configs.py`. The doc sync interval is multiplied by a
runtime value from Redis (`server/runtime/onyx_runtime.py:OnyxRuntime`,
default 1), which cloud operators set.

**Doc sync.**

```
beat: check_for_doc_permissions_sync          doc_permission_syncing/tasks.py
  fail expired and lost attempts
  is_external_doc_permissions_sync_due, retry-after backoff
  try_create_doc_permission_sync_attempt      NOT_STARTED row = the per-pair lock
  send_task(attempt_id, expires=PERMISSION_SYNC_TASK_EXPIRES)
connector_permission_sync_generator_task      heavy worker
  claim attempt, start LeaseHeartbeat
  doc_sync_func (or checkpointed_doc_sync_func) yields ElementExternalAccess
  update_element_permissions_batch -> element_update_permissions
    document -> upsert_document_external_perms: write and bump last_modified
                only when the value changed
    hierarchy node -> node permissions
  complete attempt, set last_time_perm_sync
then: the metadata sync ([[document-index]]) writes the new ACL into the index
```

Most sources use `ee/onyx/external_permissions/utils.py:generic_doc_sync`. It
streams the source's slim documents with their access. It raises when a
document has no access, so a connector bug stops the sync instead of hiding
one document. Then it diffs the result against the pair's existing document
IDs and yields an empty, private ACL for each ID the source did not return.
SharePoint and OneDrive can report the same document: a SharePoint doc sync
does not overwrite a document that a perm-synced OneDrive pair indexed
(`ee/onyx/db/document.py:upsert_document_external_perms`).

**Group sync.**

```
beat: check_for_external_group_sync           external_group_syncing/tasks.py
  one active cc-pair per source when the source is cc-pair agnostic
connector_external_group_sync_generator_task -> _timed_perform_external_group_sync
  remove_stale_external_groups                rows a previous cycle left stale
  mark_old_external_groups_as_stale           commit at once
  group_sync_func yields ExternalUserGroup -> upsert_external_groups (stale=False)
  remove_stale_external_groups                rows this cycle did not confirm
```

`upsert_external_groups` and `element_update_permissions` create the `User` rows
for unknown emails (`db/users.py:batch_add_ext_perm_user_if_not_exists`). A
group change needs no index write: chunks hold group IDs, and a user's groups
are read at query time.

**Namespacing.** A raw group ID from a source becomes
`build_ext_group_name_for_onyx(raw_id, source)`: the source prefix, lowercased.
`upsert_document_external_perms` applies it to a document's group IDs, and
`upsert_external_groups` to membership rows. Google Drive puts a domain-wide
share on a document as `build_domain_group_id(domain)`, and group sync emits a
group with the same raw ID and the domain roster.

**The lease.** The open attempt row is the per-pair lock. Partial unique indexes
allow one `NOT_STARTED` or `IN_PROGRESS` row per cc-pair for each sync kind.
`background/celery/tasks/shared/lease_heartbeat.py:LeaseHeartbeat` renews
`heartbeat_at` and the progress counts while the row is `IN_PROGRESS`. The beat
reaper fails a row whose lease expired, and a doc sync row with no progress for
`PERMISSION_SYNC_STALL_TIMEOUT`. A worker whose renewal finds no row, or that
could not renew for a while, sees `is_lost()` and stops. Each write takes a
share lock on the attempt row in its own transaction
(`lock_doc_permission_sync_attempt_if_owned`,
`lock_external_group_sync_attempt_if_owned`), so the reaper cannot fail the
attempt mid-write and a write after the reaper is refused.

**Validation.** `ee/onyx/connectors/perm_sync_valid.py:validate_perm_sync`
dispatches through `_VALIDATOR_BY_CONNECTOR_CLASS`. It runs in pairing
validation (`connectors/factory.py:_build_and_validate_connector`) and at the
start of every docfetching attempt of a perm-synced pair
(`background/indexing/run_docfetching.py:_get_connector_runner`, stage
`PERMISSION_VALIDATION`). A failed probe there fails the index attempt and,
unless the error is an `UnexpectedValidationError` or the attempt is a
backfill, pauses the pair. Named capability checks run only in capability-check
runs.

## Contracts and traps

1. `doc-sync-covers-known-docs` **A doc sync must account for every document it
   knew.** `ee/onyx/external_permissions/utils.py:generic_doc_sync` makes a
   document private when the source stops
   returning it. A doc sync that does not use it needs its own rule. GitHub has
   one: it re-checks the existing documents. Slack, Google Drive and Gmail
   ignore the existing-docs functions and have no such rule, so a document that
   left those sources keeps its ACL until pruning removes it. List the doc syncs
   that do not use `generic_doc_sync` with
   `git grep -L generic_doc_sync -- 'backend/ee/onyx/external_permissions/*/doc_sync.py'`.
2. `namespace-group-ids` **Namespace group IDs on both sides with one
   function.** Every write and compare of an external group ID must call
   `onyx/access/utils.py:build_ext_group_name_for_onyx`. It adds the source
   prefix, so "Engineering" in Confluence and in Jira stay apart, and it
   lowercases. An ID built by hand differs only in case or prefix. The match
   then fails closed: the user loses access, and the sync looks healthy. The
   doc sync and group sync writes apply it for you. The indexing write
   (`onyx/db/document.py:upsert_documents`) stores group IDs as the connector
   gives them, so a connector that sets `external_access` during indexing must
   namespace its group IDs itself (see `add_prefix` in
   `ee/onyx/external_permissions/google_drive/doc_sync.py`). A change to the
   namespacing needs a full doc sync and group sync, not a reindex, because the
   Postgres rows hold the old IDs.
3. `never-widen-first` **Never clear or widen access before the new value is
   confirmed.** `ee/onyx/db/document.py:upsert_document_external_perms` commits
   per document. A doc sync that fails halfway leaves each document either
   updated or as it was. That is safe only because no step clears an ACL first.
4. `failed-group-sync-keeps-memberships` **A failed group sync keeps revoked
   memberships for one interval.**
   `ee/onyx/db/external_perm.py:fetch_external_groups_for_user` does not filter
   on `stale`. The end-of-cycle
   `ee/onyx/db/external_perm.py:remove_stale_external_groups` runs only
   when the cycle succeeds, so a user removed from a source group keeps that
   group's access after a failure. The next attempt deletes the stale rows when
   it starts, before it fetches. That delete also drops valid memberships that
   the failed cycle did not confirm, and the user loses them until the new
   cycle writes them again. A change to this order can widen the open window or
   the closed one. Treat a run of `FAILED` group sync attempts as a security
   alert, because backoff delays the next start.
5. `bump-only-on-change` **Bump `last_modified` only on a real change.**
   `ee/onyx/db/document.py:upsert_document_external_perms` compares before it
   writes. An unconditional bump makes every synced document look stale to the
   metadata sync.
6. `registry-gates-sync-choice` **A source must be in the registry before an
   admin can pick Sync.** `connectors/pairing_access.py:validate_pairing_access`
   calls `check_if_valid_sync_source` and requires the business tier for a
   perm-synced access type. The routes in `server/documents/` and the connector
   edit plan call it. A new path that sets the access type must call it too.
7. `only-perm-synced-write-acl` **Only perm-synced pairs may write source
   ACLs.** `indexing/indexing_pipeline.py:_upsert_documents_in_db` drops a
   connector's `external_access` unless the writing pair is perm-synced.
8. `oversized-acl-skipped` **An oversized ACL is skipped, not cut.**
   `ee/onyx/background/celery/tasks/doc_permission_syncing/tasks.py:_write_element_permissions`
   skips an element whose users and groups exceed
   `access/models.py:ExternalAccess.MAX_NUM_ENTRIES` and counts it as an error.
   The document keeps its previous ACL. Repeated `docs_with_permission_errors` is a
   real gap.
9. `guarded-terminal-status` **Write a terminal status only through the guarded
   helpers** in `db/permission_sync_attempt.py`. `complete_*` raises
   `PermissionSyncAttemptLostError` unless the row is still `IN_PROGRESS`, and
   `mark_*_failed` keeps an existing `FAILED` or `CANCELED` reason. Do not set the status directly.
10. `doc-sync-blocks-prune-delete` **An open doc sync blocks pruning and
    connector deletion.** An open group sync blocks neither
    (`background/celery/tasks/pruning/tasks.py:try_creating_prune_generator_task`,
    `background/celery/tasks/connector_deletion/tasks.py:try_generate_document_cc_pair_cleanup_tasks`).
    Deletion revokes both tasks and, after its timeout, cancels both attempts.
11. `checkpoint-after-flush` **A doc sync checkpoint covers only flushed
    writes.** The task writes elements in parallel batches of
    `PERMISSION_WRITE_BATCH_SIZE`.
    `ee/onyx/background/celery/tasks/doc_permission_syncing/checkpointer.py:FileStoreDocSyncCheckpointer`
    flushes the pending batch before it saves. A failed element write freezes
    the checkpointer, so a resume starts before that element and retries it.
    Do not save a checkpoint ahead of unflushed writes.
12. `web-sync-source-list` **The web form keeps its own list of Sync sources.**
    `web/src/lib/connectors/types/source.ts:validAutoSyncSources` decides
    whether the admin form offers Sync, and
    `web/src/lib/connectors/AutoSyncOptionFields.tsx:autoSyncConfigBySource` is
    keyed by it. It mirrors `_SOURCE_TO_SYNC_CONFIG` by hand. A source missing
    from it cannot be set to Sync from the UI, and no test fails.
13. `stub-documents` **Doc sync can create a stub `Document`.** When a source
    reports a document that is not indexed yet,
    `upsert_document_external_perms` creates a row with an empty `semantic_id`,
    so the permission is ready when indexing arrives. Code that lists documents
    must not assume every row was indexed.
14. `lease-timings` **The lease timings bound how long a pair stays locked.**
    Keep them in step: `configs/constants.py:PERMISSION_SYNC_HEARTBEAT_INTERVAL`,
    `configs/constants.py:PERMISSION_SYNC_LEASE_TIMEOUT`,
    `configs/constants.py:PERMISSION_SYNC_LEASE_OVERRUN`,
    `configs/constants.py:PERMISSION_SYNC_LEASE_SELF_EXPIRY`,
    `configs/constants.py:PERMISSION_SYNC_STALL_TIMEOUT`,
    `configs/constants.py:PERMISSION_SYNC_LOST_TASK_GRACE` and
    `backend/onyx/configs/app_configs.py:PERMISSION_SYNC_TIMEOUT`. The beat fails a `NOT_STARTED`
    attempt older than `PERMISSION_SYNC_LOST_TASK_GRACE` whose task is in
    neither the broker queue nor the unacked set, for example after a Redis
    restart
    (`ee/onyx/background/celery/tasks/doc_permission_syncing/tasks.py:fail_lost_queued_doc_permission_sync_attempts`).
    A task that a worker already took also looks lost; its claim then fails and
    the beat dispatches again. A group sync's heartbeat stops renewing
    `PERMISSION_SYNC_LEASE_OVERRUN` after `PERMISSION_SYNC_TIMEOUT`, so a crawl
    thread hung in a source call cannot hold the lease for the life of the
    process. `PERMISSION_SYNC_LEASE_SELF_EXPIRY` is shorter than
    `PERMISSION_SYNC_LEASE_TIMEOUT` on purpose: a worker that cannot reach the
    database stops writing before the reaper can start a replacement. A change
    to these values, or to the reaper order, can let two workers write one
    pair.

## Decisions

- **The attempt row is the lock, not a Redis fence.** The admin page, the
  reaper, pause and deletion all read the same row. Dispatch creates it in the
  transaction that also reads the pair's status under its row lock, so a pause
  either cancels the new attempt or is seen by it. A Redis fence could disagree
  with the row, and it is lost on Redis eviction. Indexing made the same move
  (`db/indexing_coordination.py:IndexingCoordination.try_create_index_attempt`).
- **Salesforce censors after retrieval.** Its documents under a perm-synced pair
  pass the index ACL filter for every user, and
  `ee/onyx/external_permissions/salesforce/postprocessing.py:censor_salesforce_chunks`
  removes what the user cannot see. Salesforce therefore has no sync attempts
  to inspect. A Salesforce access bug is a censoring bug.
- **Long crawls resume.** A source whose doc sync can run for days (Google
  Drive) sets `checkpointed_doc_sync_func`. `FileStoreDocSyncCheckpointer` saves
  a checkpoint per cc-pair in the file store. The next attempt resumes it only
  when the attempt that saved it failed or was canceled, started after any
  requested full refresh, and no later attempt succeeded
  (`db/permission_sync_attempt.py:is_doc_permission_sync_attempt_resumable`),
  and when the file is younger than `NUM_DAYS_TO_KEEP_CHECKPOINTS` and the
  connector config hash did not change (`FileStoreDocSyncCheckpointer`).

## Known issues

- **Two Confluence sites share one attempt history.** Group sync for an agnostic
  source runs once for the source.
  `db/permission_sync_attempt.py:relevant_external_group_sync_attempts_filter`
  widens the run feed to the whole source.
- **Two clocks.** Doc sync, group sync and the metadata sync run on separate
  schedules. A document's group ID and that group's members can update at
  different times.
- **Group sync errors go to `BackgroundError`**, which no API reads
  ([[background-jobs]]).

## Dependencies

- [[connectors]]: the permission-fetching connector interfaces.
- [[google-drive]]: the Drive perm-sync listing does not raise on unreachable
  targets and can resume from a checkpoint.
- [[confluence]]: every Confluence call holds the credential provider's lock.
- [[cc-pairs-and-creds]]: the access type and the sync timestamps on the pair.
- [[document-index]]: the metadata sync that makes a Postgres ACL searchable.
- [[background-jobs]]: beat and the heavy worker.
- [[editions-and-gating]]: the beat entries exist only when EE code ships.

## Recipes

- `doc-sync-source` **A source with doc sync.** Copy the `youtrack` source; list
  the sources with
  `git ls-files 'backend/ee/onyx/external_permissions/*/doc_sync.py'`. First
  implement `SlimConnectorWithPermSync` on the connector ([[connectors]]). Write
  the source's doc sync module, which calls `generic_doc_sync`
  (`ee/onyx/external_permissions/youtrack/doc_sync.py`). It builds the connector
  with `build_connector_kwargs` and a DB credentials provider; youtrack keeps
  that in
  `ee/onyx/external_permissions/youtrack/connector.py:youtrack_connector`, so
  copy that file too. Register it in
  `ee/onyx/external_permissions/sync_params.py`: a `_load_<source>_doc_sync`
  loader and a `_SOURCE_TO_SYNC_CONFIG` entry. Set `initial_index_should_sync`
  to whether the crawl fetches permissions. True requires the connector to
  implement `CheckpointedConnectorWithPermSync`: the first index of a
  perm-synced pair runs with `include_permissions`, and
  `connectors/connector_runner.py:ConnectorRunner` raises for any other
  connector. That crawl must namespace its group IDs ([[#namespace-group-ids]]).
  The CE connector builds its `ExternalAccess` through
  `onyx/connectors/youtrack/access.py`, which reaches
  `ee/onyx/external_permissions/youtrack/access.py` at call time and returns
  None in CE; it never imports `ee.` ([[editions-and-gating]]).
  Add a frequency to `ee/onyx/configs/app_configs.py`. Add the source to the web
  lists ([[#web-sync-source-list]]). Add a validator to
  `ee/onyx/connectors/perm_sync_valid.py:_VALIDATOR_BY_CONNECTOR_CLASS`; copy
  `validate_youtrack_perm_sync`, which runs each mirrored check ID once, so
  scheduled runs validate too.
- `group-sync-source` **A source with groups.** Write a group sync module that
  yields raw group IDs; copy
  `ee/onyx/external_permissions/youtrack/group_sync.py`. Let the write path
  namespace them ([[#namespace-group-ids]]). Register it like doc sync: a
  `_load_<source>_group_sync` loader and a `GroupSyncConfig` in its
  `_SOURCE_TO_SYNC_CONFIG` entry, a `<SOURCE>_PERMISSION_GROUP_SYNC_FREQUENCY` in
  `ee/onyx/configs/app_configs.py`, and group-sync checks in
  `ee/onyx/connectors/capability_checks.py:_EXTERNAL_GROUP_SYNC_CHECKS_BY_SOURCE`.
  Set `group_sync_is_cc_pair_agnostic` when one run serves every cc-pair of the
  source. A source without group sync registers no group-sync
  checks: Slack has none, because channel access resolves user groups to single
  users (`ee/onyx/connectors/capability_checks.py`).
- `investigate-stopped-sync` **Investigate a sync that stopped.** A connector
  stops with a generic "Stop signal detected" error for a stop signal or a lost
  lease. Read the attempt's `error_message` for the cause: a reaper or cancel
  reason stays there ([[#guarded-terminal-status]]).
- `investigate-leak` **Investigate a leak or a missing document.** Read the
  document's `external_user_emails`, `external_user_group_ids` and `is_public`
  in Postgres. If they are right, the fault is later: in the index ACL or in the
  user's ACL. If they are wrong, check the newest doc sync attempt and the group
  rows of the user.
- `reproduce-propagation` **Reproduce propagation with two users.** Share a
  document at the source with user A only. After a doc sync and a metadata sync,
  A sees it and B does not. Share it with B, wait again, and B sees it. For
  groups, remove a user from a source group, make one group sync fail, and check
  that the old access holds until the next group sync starts.

## Verification

- External dependency tests: `backend/tests/external_dependency_unit/permission_sync/`
  (the lease, and session use during a crawl).
- Unit tests: `backend/tests/unit/ee/onyx/external_permissions/` and
  `backend/tests/unit/ee/onyx/connectors/`.
- Integration tests: `backend/tests/integration/connector_job_tests/` (per
  source) and `backend/tests/integration/tests/indexing/`.
