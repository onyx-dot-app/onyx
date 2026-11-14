# Google Drive

> The Google Drive connector indexes files from shared drives, My Drives,
> folders and files shared with a user, as one OAuth user or as a service
> account that impersonates every user in the domain. Its checkpoint is a staged
> crawl, not a cursor.

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
staged crawl, document ids and URL candidates, and the prune guards. It also
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
listing (`GoogleDriveConnector._fetch_drive_items`). For a service account
with no requested folders it is the shard engine (see **Shard engine**). The
serial crawl lists the rest. A service account with requested folders (or a
requested drive id that is a folder) walks phases for the whole domain
(`DriveRetrievalPhase`): inventory, shared drives, My Drives, requested
targets, external shares. Shared drives run before My Drives, so later phases
drop any file from a drive already covered. This stops shortcuts from producing
duplicates. The phase state holds partition keys and page tokens, so it grows
with drives and users. Only the dedup set grows with files
([[#dedup-set-capped]]). The OAuth crawl walks stages for its one user
(`DriveRetrievalStage`).

**Checkpointed slim listing.**
`GoogleDriveConnector.retrieve_slim_docs_from_checkpoint` runs one call of the
slim listing and returns the checkpoint. It yields `SlimDocumentStub`s with a
`DriveListingPayload` (the user who listed the file).

**Indexability.** `connectors/google_drive/doc_conversion.py:drive_file_skip_reason` is the metadata
check: shortcut or folder, `exclude_domain_link_only`, size, images and the
tabular rule. It reads `_MIME_HANDLERS`, the mime type to handler table that
conversion dispatches through, and calls `file_processing/file_types.py:is_indexable_file_type`
for other types. Every listing applies it (indexing, stubs, pruning, permission
sync), so pruning removes documents of files that indexing skips. Conversion
runs it first. `_post_download_skip_reason` covers what only the content shows
(export over the size cap, Forms API off, no text).

**Shard engine.** `connectors/google_drive/parallel_listing.py:ParallelDriveLister`.
Every partition (shared drive, My Drive, files shared with a user) lists in one
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
  stores the state through `on_checkpoint`. Pruning lists the time since the
  window end once more at the end, because a file edited during the listing
  moves past the end.

A service account checkpoint of the serial crawl (`phase_progress` or a stage)
is dropped: the attempt lists again from its window start.

**Document id.** The id comes from the file's web view link
(`connectors/google_drive/doc_conversion.py:onyx_document_id_from_drive_file`).
`GoogleDriveConnector.normalize_url` returns several candidate ids for a pasted
URL, because the URL often does not say the file type.

**Conversion.** Each connector call converts what it lists on a pool of
`DRIVE_CONVERSION_WORKERS` threads (`BoundedParallelRunner`, default 32,
`GOOGLE_DRIVE_CONVERSION_WORKERS`) while the listing goes on. A call converts
everything it lists before it returns, so the order does not change what the
checkpoint records. A file's parent node is yielded before the file is
submitted, so nodes still precede their documents.

**Clients.** `connectors/google_utils/resources.py:get_google_service` builds the Docs,
Drive, Admin and Gmail clients from a `GoogleService` member, and impersonates
the given user with a service-account key. The gateway keeps one Drive client
per thread (`threading.local`), because `googleapiclient` over `httplib2` is
not thread safe.
`GOOGLE_API_ENDPOINT_OVERRIDE` (testing only) sends every client, token refresh
and Docs API call to another URL. The clients are then built from the bundled
discovery document with its root URL replaced, so batch requests follow too.

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
   deleted. So `_retrieve_all_slim_docs_impl` with `for_pruning` lists the time
   since the end once more before it ends.

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
  `GOOGLE_API_ENDPOINT_OVERRIDE` points the connector at it, and
  `backend/scripts/benchmark_google_drive_connector.py` measures throughput.
