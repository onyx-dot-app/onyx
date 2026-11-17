# Google Drive

> The Google Drive connector indexes files from shared drives, My Drives,
> folders and files shared with a user, as one OAuth user or as a service
> account that impersonates every user in the domain. Its checkpoint holds the
> open shards of one sharded listing, not a cursor.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE syncs file permissions and Google groups
(`ee/onyx/external_permissions/google_drive/`).

---

## User experience

An admin connects a Google account with an OAuth sign-in, or a service-account
key plus the admin email it impersonates. They then pick what to index: all
shared drives, all My Drives, files shared with the account, or specific shared
drive URLs, folder URLs or user emails. A user who pastes a Drive or Docs link
into chat gets the indexed file.

When the service account lacks a domain-wide scope, the run fails with a message
that points to the scope setup docs. When a requested drive or folder is
visible to no user, the prune refuses to run.

---

## Scope

This document holds the Google Drive rules: the two credential kinds, the
sharded listing, document ids and URL candidates, and the prune guards. It also
covers the shared Google helpers, which the Gmail connector and the Google OAuth
endpoints use too, so a change there reaches them. Its neighbours own:
- [[connectors]]: the interfaces, binding, gateway and prune contracts.
- [[connector-capability-checks]]: the check runner. Google Drive registers
  named checks, some only for one credential kind.
- [[permission-sync]]: the EE doc and group sync, which use the perm-sync slim
  listing.

---

## Architecture

**Credential kind.** `connectors/google_utils/shared_constants.py:google_credential_kind`
reads the kind from the credential's keys: a service-account key or an OAuth
token. The config field `credential_kind` copies it so that checks for one kind
can apply before a run reads the credential. It is a credential-derived binding
field, and `GoogleDriveCredentialBinding.validate_credential` rejects a
credential of the other kind.

**Crawl.** Indexing, the stub listing, pruning and permission sync share one
listing, the shard engine (see **Shard engine**), for a service account and
for OAuth. `GoogleDriveConnector._plan_listing` plans it on the first call of
an attempt, and `_fetch_drive_items` runs one call. The listing state grows
with drives, users and open shards, and with folders: `folder_names` keeps the
name and parent of each listed folder, so a stub's folder path needs no read.
Only the dedup set grows with files ([[#dedup-set-capped]]).

**Checkpointed slim listing.**
`GoogleDriveConnector.retrieve_slim_docs_from_checkpoint` runs one call of the
slim listing and returns the checkpoint. It yields `SlimDocumentStub`s with a
`DriveListingPayload` (the user who listed the file). It asks Drive for no
permissions; `resolve_targets` reads every permission of a file before the
link-only filter and permission sync use them. With permission sync, each
folder node still gets its permissions (`_listed_folder_node`), so a private
folder is never a public node. Without permission sync, a folder node has
`external_access=None`, so the stored access stays. Inline indexing and pruning ask for permissions
when `exclude_domain_link_only` is on, because they filter at the listing.

**Indexability.** `connectors/google_drive/doc_conversion.py:drive_file_skip_reason` is the metadata
check: shortcut or folder, `exclude_domain_link_only`, size, images and the
tabular rule. It reads `_MIME_HANDLERS`, the mime type to handler table that
conversion dispatches through, and calls `file_processing/file_types.py:is_indexable_file_type`
for other types. Every listing applies it (indexing, stubs, pruning, permission
sync), so pruning removes documents of files that indexing skips. Conversion
runs it first. `_post_download_skip_reason` covers what only the content shows
(export over the size cap, Forms API off, no text).

**Shard engine.** `connectors/google_drive/parallel_listing.py:ParallelDriveLister`.
Every partition (shared drive, My Drive, files shared with a user, requested
folder) lists in one
`AdaptiveTaskPool`, one page per task, at `pageSize=1000`. A partition with
many files splits into `modifiedTime` shards by probe and split
(`plan_split`): the sub-ranges are query filters, so no step depends on page
order. The split thresholds count files, not pages, because permission fields
shrink a page to about 100 files. Each page checks the split again, and the
estimate takes the larger of the page density and the density of the pages the
shard kept. `GoogleDriveCheckpoint.listing` (`DriveListingState`) holds the
open shards, the coverage sets, the learned worker limit and the count of the
files that pass the metadata check, by `DocumentTypeLabel`. One lock guards
each page step, and a call drains the pool before it returns, so the
checkpoint covers exactly what the call yielded. The entry points:
- `load_from_checkpoint` converts inline: one page in flight, and a call stops
  before it passes `INLINE_CALL_BUDGET_FILES`.
- `retrieve_slim_docs_from_checkpoint`: full concurrency, stubs only.
- Pruning and permission sync loop the calls in their task. Permission sync
  stores the state through `on_checkpoint`. With no `end` from the caller, the
  loop ends with a pass that has no upper bound (`open_window_end`): every
  file modified at the window end or later. A file edited during the listing
  moves past the end. Pruning would read it as deleted, and permission sync
  would keep its old permissions.

A requested folder (`shared_folder_urls`, or a requested drive id that is a
folder) is a folder subtree partition. Its walk lists one folder at a time with
`'<id>' in parents`: one `SUBTREE` shard lists the folder's files in the time
range and all its subfolders and shortcuts, and each subfolder becomes a new
shard. A folder with more than one page becomes a `FILES` shard, which splits
by time, and a `FOLDERS` shard. The walk follows shortcuts to folders and stops
at a shortcut back up its path (`shortcut_path`). A folder in a shared drive
that an organizer lists in full is walked too: the walk follows the folder
shortcuts, and `_admit` drops the files that the drive listing covers. If no
usable user can walk it, the drive listing is its only cover
(`folders_covered_by_drive`). When that listing fails, the folder is planned
again: a new full listing of the drive covers it again, and with no cover the
folder is unreachable.

A listing drops a shortcut target that another started listing covers. When
that listing fails, the started listings list the failed owner's or drive's
files again: shared-with-user listings and folder walks with an owner or drive
filter. My Drive listings, and for a failed drive also shared drive
listings, list their shortcuts again (`shortcuts_only`).

OAuth uses the same partition kinds with the OAuth user as the only principal:
its member shared drives (from its own `drives.list`), its own files, and the
files shared with it, as the include settings select. With all three, that is
the `corpora=allDrives` corpus. Nothing is impersonated. A token refresh
failure fails the listing, because no other principal can list the files.

**Hierarchy.** On the shard engine, each partition also has a `FOLDERS` shard:
a folder-only query with no time range, which does not split. Listed folders
become hierarchy nodes. A parent that no folder listing returned goes into
`DriveListingState.unresolved_parents`, with every user who saw a child (as
indexes into `reader_emails`). When the listing is done, those parents are read
one tree level at a time, up to a folder already yielded or a drive root. The
first read is as the user who listed the child's shared drive, or as the
in-domain owner of a My Drive child; then as each user who saw a child. A read
that shows the folder with no parent (that user cannot see the parent) goes on
to the next user. If no read shows the parent, the folder is yielded with no
parent and is not marked as seen, so a later child can add a reader. A
document that arrives before its folder gets a STUB parent in docfetching, so
the connector yields children and parents in any order. A folder subtree gets
no `FOLDERS` shard: the folders it walks are the nodes. `reindex` reads the
parents of its files the same way.

A checkpoint with no listing state starts the listing again from the window
start. A checkpoint of the serial crawl that came before (`phase_progress`,
`completion_map`) parses with those keys ignored, so it does the same. That
restart also clears `seen_hierarchy_node_raw_ids`: the serial crawl could send
a folder with no parent, so each folder node is sent again.

**Document id.** The id comes from the file's web view link
(`connectors/google_drive/doc_conversion.py:onyx_document_id_from_drive_file`).
`GoogleDriveConnector.normalize_url` returns several candidate ids for a pasted
URL, because the URL often does not say the file type.

**Conversion.** Each connector call converts what it lists on a pool of
`DRIVE_CONVERSION_WORKERS` threads (`BoundedParallelRunner`, default 32,
`GOOGLE_DRIVE_CONVERSION_WORKERS`) while the listing goes on. A call converts
everything it lists before it returns, so the order does not change what the
checkpoint records. Files go to the pool round-robin by the user who listed
them (`_interleave_by_user`), so conversions spread over per-user quotas. A
file does not wait for its folder: docfetching gives a document a STUB parent
until the folder's node arrives.

**Shared API budget.** With `ENABLE_SOURCE_API_LIMITER` (off by default),
`connectors/factory.py:instantiate_connector` passes the connector a
`SourceApiLimiter` (`connectors/source_api_limiter.py`). The gateway
spends from it before each Drive and Docs request
(`connectors/google_drive/source_operations.py:attach_source_api_limiter`) and
reports a rate-limit answer with its scope
(`connectors/google_drive/source_operations.py:_is_user_rate_limit`): 403
`userRateLimitExceeded`, or a 429 whose `quota_limit` names a per-user quota
(for example `ReadRequestsPerMinutePerUser`), cuts that user's budget; any
other 429 is the project's. A batch of N files spends N requests under the
requests quota model, and reports each refused file. The budgets live in Redis
(`redis/redis_rate_window.py`), so every worker that uses the credential shares
them. Connector code does not import Redis. Each per-minute budget is enforced
in a 10 s window at the same rate, so a full minute cannot go in one burst. A
second window of the full minute holds the configured budget. The budgets are
not a hard quota cap: one request always fits an empty window, so a single
batch larger than a budget goes through. A call goes on with no slot when
Redis cannot be reached, and takes its slot over the budget after it waited
300 s (`MAX_WAIT_SECONDS`, counted in `onyx_source_api_limiter_overdrafts_total`).
Waiting calls take turns in a queue for each window: the content reads of
conversion (`_spend(..., bulk=True)`: downloads, exports, Docs API reads) go
after every other call, such as listing and permission sync, and leave 5 % of
each window to them (`PRIORITY_RESERVE`). Calls of one class go in the order
they came, and a waiter that stops trying for 20 s leaves the queue. A window
cuts only when the refused share of its requests in the current epoch is at
least 2 % with at least 10 refusals: by 0.8, or in a storm (10 % or more) by
the accepted share, at most 0.5. A cut does not go below 90 % of the share
that Google accepted (the share of the window that the recent requests used,
less the refused share), and takes at least 5 % off. Each cut starts a new
epoch. A refusal of a request that took its slot before the cut is late and
does not count, so one burst gives one cut. The limiter keeps the epoch of
each window per thread, so a refusal must be reported from the thread that
took the slot. A cut holds for 60 s, but a storm of refusals in the new epoch
can cut again after 10 s. The ceiling is the accepted share, or 80 % of the
last ceiling when that is higher. After the hold the share grows by 0.05 each
10 s up to 80 % of the ceiling, then by 0.005; above the ceiling it moves the
ceiling up. EE group sync and doc permission sync
(`ee/onyx/external_permissions/google_drive/`) spend from the same budgets.

**Request and back-off metrics.** The gateway counts each request it sends,
each try of a retry included, in `onyx_source_api_requests_total{source, api,
outcome}` (`server/metrics/source_api_metrics.py`). A media download retries in
googleapiclient, so `_CountingHttp` counts each of its HTTP requests. The
limiter sets `onyx_source_api_limiter_budget{scope}` from the shares that the
Redis scripts return, `onyx_source_api_limiter_ceiling` at each project cut,
and counts cuts, late refusals and waits. The listing pool
(`AdaptiveConcurrency(metrics_name="drive_listing")`) records its limit,
in-flight tasks, cuts and growth (`server/metrics/adaptive_pool_metrics.py`).
docfetching runs the connector in a spawned process, so
`server/metrics/child_process_relay.py` relays these metrics to the worker's
metrics server. A sampler can also read the shared budget in Redis:
`<tenant>:source_api_limit:google_drive:<credential id>:<api>:all:meta` (and
`:user:<email>:meta`) holds `factor`, the share of the limit, as of the last
request, and `ceiling` and `epoch`. The `:queue` sorted set of the same window
holds its waiters.

**Clients.** `connectors/google_utils/resources.py:get_google_service` builds the Docs,
Drive, Admin and Gmail clients from a `GoogleService` member, and impersonates
the given user with a service-account key. The gateway impersonates each user
once and shares that credential across threads, so each user's token is fetched
once (`GoogleDriveSourceOperations._impersonated`). It keeps the Drive and
directory clients and the Docs API sessions per thread (`threading.local`),
because `googleapiclient` over `httplib2` and a `requests` session are not
thread safe. A thread keeps only its most recent Docs sessions.

---

## Contracts and traps

1. `specific-request-overrides-toggles` **A specific request turns off the
   general toggles.** When any of `shared_drive_urls`, `my_drive_emails` or
   `shared_folder_urls` is set, the constructor ignores
   `include_shared_drives`, `include_my_drives` and
   `include_files_shared_with_me`. The toggles' field policies declare this
   with `depends_on`: a toggle change in the same edit as a specific-request
   change has an unknown direction, and the admin picks the reconciliation.
2. `unreachable-target-fails-prune` **The prune listing fails on unreachable
   targets.** `connectors/google_drive/connector.py:GoogleDriveConnector.retrieve_all_slim_docs`
   raises `UnreachableTargetsError` when a
   requested drive or folder is visible to no impersonable user. Without it,
   prune deletes every document indexed from that target
   ([[connectors#slim-listing-raises-on-auth-failure]]). The perm-sync listing
   does not raise.
3. `failed-impersonation-keeps-files` **A user whose impersonation failed keeps
   their files.** The checkpoint records `failed_impersonation_emails`, and
   other users' listings must not drop files that only that user owns.
4. `slim-honors-start` **The slim listing honors the indexing start.**
   `slim_listing_honors_indexing_start` is `True`, so a prune with an indexing
   start deletes files last modified before it.
5. `dedup-set-capped` **The dedup set has a cap.** `retrieved_drive_file_ids`
   stops growing at `MAX_DEDUP_DRIVE_FILE_IDS`. It prevents repeats within a
   run, but it is not a record of completeness. A saved checkpoint outlives a
   deploy, so a change to the format of its ids takes a new field name: an old
   checkpoint then loads with an empty set
   (`connectors/google_drive/models.py:GoogleDriveCheckpoint`).
6. `config-needs-scope` **A config needs at least one scope.** The constructor
   (`connectors/google_drive/connector.py:GoogleDriveConnector.__init__`) raises `ConnectorValidationError` when every toggle and every specific
   request is empty.
7. `prune-lists-late-edits` **A prune lists the edits made during its
   listing.** The shard engine lists the window `[start, end)`. A file edited
   during the listing moves past the end, and a prune would read it as
   deleted. So `_retrieve_all_slim_docs_impl` with no `end` lists the time
   since the end once more before it ends. Permission sync takes the same
   pass.

---

## Dependencies

- [[connectors]]: interfaces, binding, gateway and prune contracts.
- [[connector-capability-checks]]: runs the Google Drive named checks.

---

## Recipes

- `investigate-refused-prune` **Investigate a prune that refuses to run.** Look in the backend log for
  "Refusing to report a complete listing". It names the requested targets that
  no user can see ([[#unreachable-target-fails-prune]]). Fix the drive or folder
  URL in the config, or share the target with an impersonated user.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/google_drive/` and
  `backend/tests/unit/onyx/connectors/google_utils/`.
- External dependency tests:
  `backend/tests/external_dependency_unit/connectors/google_drive/`.
- Daily tests against a live domain: `backend/tests/daily/connectors/google_drive/`.
- Without a Workspace: the mock server in
  `backend/tests/integration/mock_services/mock_google_drive_server/` serves the
  token, Drive, Admin SDK and Docs calls, with Google's quotas and errors.
  Onyx has no setting for it. In tests,
  `backend/tests/integration/mock_services/mock_google_drive_server/mock_gdrive/patch_onyx.py`
  patches the clients, token endpoints and Docs/Forms URLs.
  `backend/tests/integration/mock_services/mock_google_drive_server/sitecustomize.py`
  does the same for a running Onyx.
  `backend/scripts/benchmark_google_drive_connector.py` measures throughput.
