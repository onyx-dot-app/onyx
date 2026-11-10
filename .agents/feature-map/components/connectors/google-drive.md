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

**Crawl.** The service-account crawl walks phases for the whole domain
(`DriveRetrievalPhase`): inventory, shared drives, My Drives, requested
targets, external shares. Shared drives run before My Drives, so later phases
drop any file from a drive already covered. This stops shortcuts from producing
duplicates. The phase state holds partition keys and page tokens, so it grows
with drives and users. Only the dedup set grows with files
([[#dedup-set-capped]]). The OAuth crawl walks
stages for its one user (`DriveRetrievalStage`). Indexing and the slim
listings share the crawl (`GoogleDriveConnector._fetch_drive_items`).

**Checkpointed slim listing.**
`GoogleDriveConnector.retrieve_slim_docs_from_checkpoint` runs one call of the
slim listing for indexing and returns the checkpoint. It yields
`SlimDocumentStub`s with a `DriveListingPayload` (the user who listed the
file). It drops files that conversion cannot index
(`connectors/google_drive/doc_conversion.py:drive_file_can_be_indexed`): keep
that function in step with `_convert_drive_item_to_document`. No worker calls
it yet. Pruning and permission sync still use the serial crawl.

**Parallel listing.** For a service account with no requested folders, that
call runs `connectors/google_drive/parallel_listing.py:ParallelDriveLister`.
Every partition (shared drive, My Drive, files shared with a user) lists in one
`AdaptiveTaskPool`, one page per task, at `pageSize=1000`. A partition with
many pages splits into `modifiedTime` shards by probe and split
(`plan_split`): the sub-ranges are query filters, so no step depends on page
order. `GoogleDriveCheckpoint.listing` (`DriveListingState`) holds the open
shards, the coverage sets, the learned worker limit and the count of stubs by
`DocumentTypeLabel`. One lock guards each page step, and a call drains the pool
before it returns, so the checkpoint covers exactly what the call yielded. The
OAuth flow and a connector with requested folders use the serial crawl.

**Document id.** The id comes from the file's web view link
(`connectors/google_drive/doc_conversion.py:onyx_document_id_from_drive_file`).
`GoogleDriveConnector.normalize_url` returns several candidate ids for a pasted
URL, because the URL often does not say the file type.

**Shared API budget.** With `ENABLE_SOURCE_API_LIMITER` (off by default),
`connectors/factory.py:instantiate_connector` passes the connector a
`SourceApiLimiter` (`background/indexing/source_api_limiter.py`). The gateway
spends from it before each Drive and Docs request
(`connectors/google_drive/source_operations.py:attach_source_api_limiter`) and
reports a rate-limit answer with its scope: 403 `userRateLimitExceeded` cuts
that user's budget, and 429 cuts the project's. The budgets live in Redis
(`redis/redis_rate_window.py`), so every worker that uses the credential shares
them. Connector code does not import Redis.

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
