# Connectors

> The boundary between Onyx and the outside world. A connector pulls documents
> from one source type, in one of a small set of standard shapes, and hands
> plain `Document` objects to indexing. It never chunks, embeds, or writes to
> the index, and it never touches credential encryption directly.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** ingestion
**Edition:** CE for the connector interfaces, the registry, and indexing
(`CredentialCapability.INDEXING`). EE adds the two permission-sync capabilities
(`DOC_PERMISSION_SYNC`, `EXTERNAL_GROUP_SYNC`); `capability_checks/applicability.py`
gates them behind `fetch_ee_implementation_or_noop`.
**Owns:**
`backend/onyx/connectors/interfaces.py`, `models.py`, `registry.py`, `factory.py`,
`capabilities.py`, `connector_runner.py`, `credentials_provider.py`, `exceptions.py`,
`source_operations.py`, `capability_checks/`, `cross_connector_utils/`, and the
individual `backend/onyx/connectors/<source>/` implementation packages (not owned
individually; see §2 for the canonical list).

**Does not own:** turning a `Document` into chunks, embeddings, and index writes
([[indexing-pipeline]] owns that, starting from the batches `ConnectorRunner`
yields); the `Connector`/`Credential`/`ConnectorCredentialPair` tables, credential
encryption, and the cc-pair admin lifecycle ([[cc-pairs-and-credentials]] owns
those; this document only describes the shape of the config and credential a
connector receives); compiling `external_access` into search-time ACL filters
([[access-control]] and [[permission-sync]] own that; a connector only emits the
field).

**Read first:** `backend/onyx/connectors/README.md`. It is the contributor guide
for adding a new source. This document maps it to code, corrects two places
where the code has grown past it, and adds verification guidance.

---

## 1. What the user experiences

An admin opens **Add Connector**, picks a source (for example Confluence), and
authenticates: an API token, an OAuth flow, or a service-account key, depending
on the source. They then scope what to pull, for example a space key or a CQL
query for Confluence, a set of channels for Slack, a shared drive for Google
Drive. Saving creates the connector and kicks off an initial index run. The
admin watches the connector's status move from indexing to a document count and
a "last successful index" timestamp on the connector status page. From then on,
a background job polls for new and changed documents on a schedule the admin
sets, and a separate job prunes documents that were deleted at the source.

If credentials are wrong or a permission is missing, the admin sees a
validation error at connector-creation time rather than a silent empty index
later; that error comes from the capability-check machinery in §4, not from
watching an index run fail.

---

## 2. Surfaces

### Admin routes (frontend)

| Route | Purpose |
|---|---|
| `web/src/app/admin/connectors/page.tsx` | The source picker (re-exports `web/src/views/admin/connectors/CatalogPage.tsx`): cards for every entry in `SOURCE_METADATA_MAP`. `/admin/add-connector` redirects here (`web/next.config.js`). |
| `web/src/app/admin/connectors/[connector]/` | The dynamic per-source config route: renders the form described by `connectorConfigs[source]`. |

### Frontend config surfaces

| File | Holds |
|---|---|
| `web/src/lib/connectors/connectors.tsx` | `connectorConfigs`, keyed by source: the form schema (fields, types, defaults) the add-connector page renders and posts as `connector_specific_config`. |
| `web/src/lib/sources.ts` | `SOURCE_METADATA_MAP`: icon, display name, and docs link per source, read by `getSourceMetadata`/`isValidSource`-style helpers. |

`backend/onyx/connectors/README.md:96,113` names exactly these two files as the
frontend changes a new connector requires.

### Backend HTTP endpoints (`backend/onyx/server/documents/connector.py`, prefix `/manage`)

| Method | Path | Notes |
|---|---|---|
| POST | `/admin/connector` | Create a `Connector` row (`create_connector_from_model`). |
| PATCH | `/admin/connector/{connector_id}` | Update config, schedule, etc. |
| DELETE | `/admin/connector/{connector_id}` | |
| POST | `/admin/connector/run-once` | On-demand index trigger. |
| GET | `/admin/connector/status`, `/admin/connector/indexing-status` (POST) | Status and index-attempt history for the admin UI. |
| GET | `/admin/connector/failed-indexing-status` | |
| POST | `/admin/connector/file/upload`, GET/POST `/admin/connector/{id}/files*` | File-connector-specific upload and file-list management. |
| GET | `/connector/{google-drive,gmail}/authorize/{credential_id}`, `/callback` | Google-specific OAuth flows in `connector.py`. |
| GET | `/connector/oauth/authorize/{source}`, `/callback/{source}`, `/details/{source}` | Generic OAuth flow for every `OAuthConnector` implementation (`server/documents/standard_oauth.py`). |
| POST/GET | `/admin/credential/{credential_id}/capability-check`, `/capability-report`, `/admin/credential/capability-reports`, `/admin/credential/{credential_id}/binding-check` | Run and read capability checks, and check credential-bound config fields (`server/documents/credential_capabilities.py`). |
| POST/GET | `/admin/connector-checks/runs`, `/admin/connector-checks/runs/{run_id}` | Draft capability-check runs on an unsaved connector form (`server/documents/capability_check_runs.py`). |
| GET | `/connector`, `/connector/{connector_id}`, `/indexed-sources` | Read paths, including the anonymous-ish `/connector-status` used by chat surfaces. |

Every connector run on a cc-pair (index, prune, hierarchy fetch, targeted reindex,
capability check) goes through
`backend/onyx/connectors/factory.py:instantiate_connector` before it touches the
source. User-file ingestion is the exception: it builds `LocalFileConnector`
directly in `user_file_processing/tasks.py:_load_user_file_documents`. See §4.

### The `DocumentSource` enum: the canonical list

`backend/onyx/configs/constants.py:DocumentSource` has 62 members and is the
single source of truth for "what is a valid source in Onyx". It is **not** 1:1
with `backend/onyx/connectors/registry.py:CONNECTOR_CLASS_MAP`. Four members
have no connector class and are handled by other components instead:

| `DocumentSource` value | Why it has no connector |
|---|---|
| `INGESTION_API` | Documents pushed directly via the ingestion API, no fetch step. |
| `NOT_APPLICABLE` | Used for federated-search-only pseudo-sources. |
| `USER_FILE` | User-uploaded files; owned by [[file-store-and-user-files]]. |
| `CRAFT_FILE` | Raw binary files for the Craft sandbox; no text extraction. |

`DocumentSource.MOCK_CONNECTOR` does have a registry entry
(`onyx.connectors.mock_connector.connector.MockConnector`) for integration
tests. A separate `FederatedConnectorSource` enum
(`backend/onyx/configs/constants.py:FederatedConnectorSource`) maps a
federated-only source like `FEDERATED_SLACK` back to the `DocumentSource` it
shadows; see [[federated-search]].

Do not enumerate all 58 registered connectors here. `DocumentSource` plus
`registry.py:CONNECTOR_CLASS_MAP` is the authoritative list. The handful of
architecturally distinct *shapes* those connectors take are in §4 and §6.

---

## 3. Data model

### The `Connector` table

`backend/onyx/db/models.py:Connector` (`connector` table): `id`, `name`,
`source` (`DocumentSource`), `input_type` (`InputType`),
`connector_specific_config` (JSONB, the kwargs passed to the connector's
`__init__`), `indexing_start`, `refresh_freq`, `prune_freq`,
`kg_processing_enabled`, `kg_coverage_days`. A `Connector` row is not runnable
by itself; it is paired with a `Credential` through `ConnectorCredentialPair`.
[[cc-pairs-and-credentials]] owns that table, the `Credential` table, and
encryption. This component only consumes the pairing at run time (§4).

### The document model a connector emits (`backend/onyx/connectors/models.py`)

- **`Section` / `TextSection` / `ImageSection` / `TabularSection`**: a
  `SectionType`-discriminated union. `TextSection.text` is inline text.
  `ImageSection.image_file_id` points at a file-store blob. `TabularSection`
  stages a CSV in the file store (`csv_file_id`) and is streamed row-by-row at
  chunk time so a large sheet never sits on the worker heap
  (`TabularSection.materialize_text`).
- **`DocumentBase`** / **`Document`** (`Document.id` and `Document.source` are
  required; everything else on `DocumentBase` is optional): `id` (the stable
  dedup key, see §5), `sections`, `semantic_identifier` (the UI display
  identifier), `title` (falls back to `semantic_identifier` via
  `get_title_for_document_index`), `metadata` (dict of string/string-list,
  turned into filterable key-value pairs by
  `convert_metadata_dict_to_list_of_strings`), `doc_updated_at`/`doc_created_at`,
  `primary_owners`/`secondary_owners` (`BasicExpertInfo`), `external_access`
  (`ExternalAccess | None`, optional connector-provided metadata. Many
  connectors fill it only during permission-sync runs. Some, such as
  `GmailConnector`, fill it on every indexing run. Flows to [[access-control]]), `parent_hierarchy_raw_node_id` (links
  a document to a `HierarchyNode`), `file_id`, `additional_info` (opaque,
  connector-specific).
- **`Document.content_hash`**: an MD5 fingerprint over title, text, image ids, sorted
  `doc_metadata` (not the filter `metadata` field), and sorted owners, computed before image summarization runs. It is
  the fallback dedup gate for connectors that don't supply `doc_updated_at`
  (the web connector is the example in the docstring).
- **`SlimDocument`**: `id`, `external_access`, `parent_hierarchy_raw_node_id`,
  `doc_created_at`. What a slim connector yields instead of a full `Document`.
- **`HierarchyNode`**: a folder/space/page structural node (`raw_node_id`,
  `raw_parent_id`, `display_name`, `node_type`, `external_access`), distinct
  from the SQLAlchemy `HierarchyNode` row it becomes during docprocessing.
- **`ConnectorCheckpoint`**: base class is just `{has_more: bool}`. Real
  connectors subclass it with whatever cursor state they need; see the case
  studies in §4. Checkpoints must round-trip through
  `CheckpointedConnector.validate_checkpoint_json`.
- **`ConnectorFailure`** (`DocumentFailure` or `EntityFailure`, exactly one):
  yielded alongside documents so one bad item doesn't fail an entire batch.
- `credential_capability_report` (`backend/onyx/db/models.py:CredentialCapabilityReportRow`):
  the persisted outcome of a capability check run (§4, §5).

---

## 4. How it works

### 4.1 The connector flows that actually exist

The README describes four flows (Load, Poll, Slim, Event). The real interface
set in `backend/onyx/connectors/interfaces.py` is larger:

| Base class | Method | Driven by a background job today? |
|---|---|---|
| `LoadConnector` | `load_from_state` | Rarely for the generic index path; the direct call site is `backend/onyx/background/celery/tasks/user_file_processing/tasks.py:_load_user_file_documents`, used for user-uploaded files via `LocalFileConnector`, not the connector index loop. |
| `PollConnector` | `poll_source` | Only as a fallback inside `backend/onyx/background/celery/celery_utils.py:extract_ids_from_runnable_connector` when pruning a non-slim, non-checkpointed connector. `ConnectorRunner` also supports it directly, but no shipped connector both lacks `CheckpointedConnector` and is exercised through the primary indexing path today. |
| `CheckpointedConnector` | `load_from_checkpoint` | **Yes, this is the primary indexing path.** Driven by `backend/onyx/connectors/connector_runner.py:ConnectorRunner.run`, called from `backend/onyx/background/indexing/run_docfetching.py`, which `backend/onyx/background/celery/tasks/docfetching/tasks.py:_docfetching_task` invokes. |
| `CheckpointedConnectorWithPermSync` | `load_from_checkpoint_with_perm_sync` | Same call chain as above, selected by `ConnectorRunner` when `include_permissions=True`. |
| `SlimConnector` | `retrieve_all_slim_docs` | Yes: `celery_utils.py:extract_ids_from_runnable_connector`, called from `backend/onyx/background/celery/tasks/pruning/tasks.py:connector_pruning_generator_task`, beat-scheduled via `check_for_pruning`. |
| `SlimConnectorWithPermSync` | `retrieve_all_slim_docs_perm_sync` | Same pruning call chain, and consumed by EE permission-sync jobs. |
| `Resolver` | `reindex` | Yes, but on demand, not beat-scheduled: `backend/onyx/background/indexing/run_targeted_reindex.py:process_targets_for_cc_pair`, reached from the admin-triggered `backend/onyx/background/celery/tasks/docprocessing/targeted_reindex_task.py`. Re-fetches specific documents named by stored `ConnectorFailure` rows. |
| `HierarchyConnector` | `load_hierarchy` | Yes, beat-scheduled: `backend/onyx/background/celery/tasks/hierarchyfetching/tasks.py:_run_hierarchy_extraction`, gated by `_is_hierarchy_fetching_due`. |
| `CredentialsConnector` | `set_credentials_provider` | Not a fetch flow; a marker interface `factory.py:instantiate_connector` checks to decide whether to call `load_credentials` or hand over a `CredentialsProviderInterface` (§4.3). |
| `OAuthConnector` | `oauth_*` classmethods | Backs the generic `/connector/oauth/*` endpoints in §2. Egnyte, Linear, and Salesforce implement it. Google Drive and Gmail use their own endpoints. |

**`CheckpointedConnector` is the modern path.** `PollConnector`/`LoadConnector`
are legacy for the main index loop; new connectors should implement
checkpointing (`backend/onyx/connectors/README.md` predates this shift and
still frames Load/Poll as the two primary flows, but `factory.py`'s own
`_validate_connector_supports_input_type` already treats `CheckpointedConnector`
as satisfying an `InputType.POLL` request).

**Slim connectors exist so pruning can list document IDs cheaply.** Confirmed:
`retrieve_all_slim_docs`/`_perm_sync` return `SlimDocument` (just `id`,
`external_access`, `parent_hierarchy_raw_node_id`, `doc_created_at`), never full
content, and the only consumer is the pruning diff in §4.4. A slim connector
does the same enumeration as the full connector without downloading bodies.

### 4.2 Registry and factory: source to running instance

1. `backend/onyx/connectors/registry.py:CONNECTOR_CLASS_MAP` maps each
   `DocumentSource` to a `ConnectorMapping(module_path, class_name)`, never the
   class object itself, so importing the registry never imports every SDK.
`ConnectorMapping` also carries a `config_class`, a `ConnectorConfig` subclass from
   `<source>/config.py` (`connector_config.py`). It types `connector_specific_config` and
   forbids unknown keys.
2. `factory.py:_load_connector_class` imports the module lazily on first use
   and caches the class in `_connector_cache`. A missing map entry raises
   `ConnectorMissingException` (only at first instantiation, not at import
   time; see §9).
3. `factory.py:identify_connector_class` additionally validates the class
   against a requested `InputType` via `_validate_connector_supports_input_type`.
4. `factory.py:instantiate_connector` builds the instance:
   `connector_class(**build_connector_kwargs(source, config))`, then branches on
   `isinstance(connector, CredentialsConnector)`:
   - **True**: builds an `OnyxDBCredentialsProvider` via
     `credentials_provider.py:build_db_credentials_provider` and calls
     `connector.set_credentials_provider(provider)`. The connector never sees
     the raw credential dict; it pulls through the provider under a Redis lock
     (`OnyxDBCredentialsProvider.LOCK_TTL = 900`), which matters for
     credentials that rotate mid-run.
   - **False**: decrypts `credential.credential_json` once, converts it with
     `credential_families.py:to_source_credential_json`, calls
     `connector.load_credentials(credential_json)`, and if the connector
     returns a refreshed dict, writes it back via
     `backend_update_credential_json`.
   `build_connector_kwargs` validates the stored config against `config_class`. If
   validation fails, it logs a warning and passes the stored config through as is, because
   old rows may not conform.
   Either way, `connector.set_allow_images(...)` and, if a raw-file callback
   was supplied, `connector.set_raw_file_callback(...)` run afterward.

### 4.3 Credentials without the connector knowing about encryption

`credentials_provider.py` gives a connector two implementations of
`CredentialsProviderInterface`, both handing back a plain dict:
`OnyxDBCredentialsProvider` (dynamic, DB-backed, lock-guarded, used for real
cc-pairs) and `OnyxStaticCredentialsProvider` (in-memory, used by tests and the
`if __name__ == "__main__"` manual-test pattern the README recommends).
`is_dynamic()` tells a connector whether it must re-acquire the lock around
renewal. Neither implementation is visible to the connector as anything but
`get_credentials()`/`set_credentials()`; decryption happens inside
`OnyxDBCredentialsProvider.get_credentials`, not in connector code.

### 4.4 A fetch run through `connector_runner.py`

`ConnectorRunner.__init__` rejects `include_permissions=True` for anything that
isn't a `CheckpointedConnector`. `ConnectorRunner.run(checkpoint)`:

- For a `CheckpointedConnector`: calls `load_from_checkpoint` (or
  `_with_perm_sync`), wraps the raw generator in
  `CheckpointOutputWrapper`, which separates `Document | HierarchyNode |
  ConnectorFailure` items and captures the generator's `StopIteration` return
  value as the next checkpoint. Hierarchy nodes are flushed to the caller
  **before** documents in every batch boundary, to keep the parent-before-child
  invariant intact for [[indexing-pipeline]].
- For a legacy `PollConnector`/`LoadConnector`: builds a dummy finished
  checkpoint (`has_more=False`) after draining `poll_source`/`load_from_state`.

The docfetching entrypoint (`backend/onyx/background/indexing/run_docfetching.py`)
drives this generator, batches the yielded documents onward, and persists the
returned checkpoint. An interrupted attempt resumes from that checkpoint on the
next scheduled run. After a successful attempt, the next run starts with a fresh
dummy checkpoint (`run_docfetching.py`).
[[indexing-pipeline]] owns everything from "batch of `Document` objects
received" onward: chunking, embedding, and the index write.

### 4.5 Pruning: the slim diff

`backend/onyx/background/celery/tasks/pruning/tasks.py:connector_pruning_generator_task`
loads `all_indexed_document_ids` for the cc-pair from Postgres, calls
`celery_utils.py:extract_ids_from_runnable_connector` to get
`all_connector_doc_ids` from the slim connector, and computes
`doc_ids_to_remove = all_indexed_document_ids - all_connector_doc_ids.keys()`.
See §5 for the invariant this depends on.

### 4.6 Three representative shapes

Do not read all 58 connectors. These three (chosen for the README) span the
range:

| Connector | Base classes | Checkpoint | Notable |
|---|---|---|---|
| Confluence (`confluence/connector.py:ConfluenceConnector`) | `CheckpointedConnector`, `SlimConnector`, `SlimConnectorWithPermSync`, `CredentialsConnector`, `Resolver` | `ConfluenceCheckpoint` (`next_page_url`) | No `LoadConnector`/`PollConnector`; checkpointing is mandatory, not optional. `load_credentials` deliberately raises `NotImplementedError("Use set_credentials_provider with this connector.")`. Has a `source_operations.py` gateway (`ConfluenceSourceOperations`) and registers named capability checks. |
| Google Drive (`google_drive/connector.py:GoogleDriveConnector`) | `SlimConnector`, `SlimConnectorWithPermSync`, `CheckpointedConnectorWithPermSync`, `Resolver` | `GoogleDriveCheckpoint` (`google_drive/models.py`): a multi-stage state machine (`DriveRetrievalStage`: `START → OAUTH_FILES → USER_EMAILS → MY_DRIVE_FILES → DRIVE_IDS → SHARED_DRIVE_FILES → DONE`) plus a per-impersonated-user completion map. Not a simple cursor. | Splits source-API logic across `file_retrieval.py`, `doc_conversion.py`, `section_extraction.py` rather than a single `source_operations.py`. |
| Slack (`slack/connector.py:SlackConnector`) | `SlimConnectorWithPermSync`, `CredentialsConnector`, `CheckpointedConnectorWithPermSync` | `SlackCheckpoint`: `channel_ids`, per-channel completion map, `current_channel_access` (carries an in-flight channel's `ExternalAccess` across a checkpoint boundary) | Has a real `source_operations.py` (`SlackSourceOperations`), the enforced single import site for `slack_sdk`. `external_access` is assigned inline on yielded documents, not in a separate pass. |

### 4.7 The `SourceOperations` gateway pattern

`source_operations.py` defines an ABC, `SourceOperations`, that a connector's
own `<source>/source_operations.py` subclasses to become the single place that
source-API calls happen. `@source_operation` stamps a `SourceOperationSpec`
(capabilities served, `OperationConsumes`, optional named `variants` for calls
whose required permission depends on an argument) onto each public method;
`SourceOperations.__init_subclass__` raises at import time if any public
method on the subclass lacks the stamp, or if the subclass overrides
`__init__`. Operations must return plain data, never live SDK objects, because
lazily-evaluated SDK attribute access (PyGithub, office365) can fire network
calls outside any wrapper. Only Slack, Confluence, OneDrive, and Outlook have a gateway today
(`<source>/source_operations.py`); most connectors still call their SDK directly.

### 4.8 Capabilities and capability checks

`capabilities.py:CredentialCapability` (`INDEXING`, `DOC_PERMISSION_SYNC`,
`EXTERNAL_GROUP_SYNC`) is the vocabulary. `capability_checks/applicability.py`
decides which capabilities apply to a source on this build (CE: `INDEXING`
only; EE adds the perm-sync ones). `capability_checks/registry.py` maps a
source to named `CapabilityCheck`s (only Slack, Confluence, OneDrive, and Outlook register real ones
today; every other source gets a synthesized fallback wrapping
`validate_connector_settings`). A source with named checks must have a
`SourceOperations` gateway; `get_capability_checks` asserts this. `capability_checks/runner.py:generate_capability_report`
instantiates the connector in isolation with a timeout guard, builds the
source's `SourceOperations` gateway if one is registered, and runs checks
sequentially (source APIs rate-limit) via `run_capability_checks`, mapping
`ConnectorValidationError` to `FAILED` and anything else ambiguous to
`INDETERMINATE`, never to `FAILED`. `CapabilityCheckTrigger`
(`backend/onyx/db/enums.py`): `MANUAL`, `CREDENTIAL_CREATED`,
`CC_PAIR_VALIDATION`, `INDEXING_ATTEMPT`, `PERM_SYNC_ATTEMPT`. The simpler,
existing blocking-validation path in `factory.py:validate_ccpair_for_user`
still runs its own `validate_connector_settings`/`validate_perm_sync` calls and
separately feeds a coarse pass/fail report into the same
`credential_capability_report` table via
`capability_checks/recorder.py:record_blocking_validation_outcome`, which
never clobbers a richer report the check-runner already wrote.

For a source with named checks, a pairing at creation or credential swap
(`CapabilityCheckTrigger.CC_PAIR_VALIDATION`) skips the legacy
`validate_connector_settings`/`validate_perm_sync` calls.
`capability_checks/creation.py:validate_pairing_with_named_checks` runs the named
checks instead and stores the full report. Only a required check that `FAILED`
within the blocking budget blocks the pairing. Indexing and perm-sync attempts keep
the legacy validation. Full runs execute as the `RUN_CAPABILITY_CHECKS` Celery task
on the `capability_checks` queue. A beat task, `CHECK_FOR_STALE_CAPABILITY_RUNS`,
retires dead runs. Draft runs on an unsaved form (`/admin/connector-checks/runs`)
reuse their result at creation when the form is unchanged.

With `CONNECTOR_CHECKS_ENABLED`, a pair's first index attempt waits while a check
run is in flight or fails to run, or while a required check has `FAILED`
(`capability_checks/indexing_hold.py:get_first_indexing_hold`). See
[[indexing-pipeline]] §4.2.

### 4.9 Typed configs and credential families

Every registry entry has a `ConnectorConfig` (`connector_config.py`). Each field
mirrors one `__init__` kwarg of the connector. A config may inherit a
`CredentialBinding` model for fields whose valid values depend on the account behind
the credential, such as a site URL. `factory.py:validate_credential_binding` checks
those fields at pairing and on config edit.

`credential_families.py` lets related sources share one stored credential: Atlassian
(Confluence, Jira), Google (Gmail, Drive), and Microsoft (SharePoint, OneDrive,
Outlook, Teams). Each source has a `FamilyCredentialCodec`.
`to_source_credential_json` converts the family shape back to the source's own keys,
so a connector reads only its own keys. Credentials created before a source joined a
family keep the source's shape and stay usable by that source only.

---

## 5. Contracts and invariants

1. **`Document.id` must be stable across runs.** It is the dedup key against
   `DocumentByConnectorCredentialPair`. A connector that regenerates IDs (for
   example from a mutable field) creates duplicate documents on every run.
2. **A poll or checkpointed connector must honour its `start`/`end` window.**
   `ConnectorRunner.run` passes UNIX timestamps computed from the scheduling
   layer; a connector that ignores them either reprocesses everything every
   run or misses documents changed between runs.
3. **A slim connector must return exactly the same ID set as the full
   connector**, modulo the time window. Pruning's diff (§4.5) treats any ID
   present in the index but absent from the slim result as deleted at the
   source.
4. **Checkpoints must be JSON-serializable and resumable.**
   `ConnectorCheckpoint` subclasses are Pydantic models; `validate_checkpoint_json`
   must round-trip whatever `load_from_checkpoint` returns. `build_dummy_checkpoint`
   must produce a checkpoint with `has_more=True` so a fresh run actually starts.
5. **A connector must not swallow an auth failure as an empty result.**
   **Verified true, and unguarded at the framework level.** The pruning diff
   in §4.5 has no minimum-count or ratio check: if `extract_ids_from_runnable_connector`
   (`backend/onyx/background/celery/celery_utils.py`) returns a genuinely empty
   dict without raising, `connector_pruning_generator_task`
   (`backend/onyx/background/celery/tasks/pruning/tasks.py`) computes
   `doc_ids_to_remove` as every currently-indexed document for the cc-pair and
   proceeds to delete them. The framework's only protection is that an
   *exception* during slim retrieval aborts the run
   (`connector_pruning_generator_task`'s outer `except Exception` calls
   `set_failure_backoff` and re-raises, deleting nothing). Whether a given
   connector is safe depends entirely on whether its `retrieve_all_slim_docs*`
   implementation raises on a 401/403 rather than catching it and returning
   early. This is the highest-consequence contract in this component: a new
   connector's slim path must raise, not return empty, on auth failure.
6. **`include_attachments` parity between the main and slim passes.** Per
   `backend/onyx/connectors/README.md`, the slim pass must admit exactly the
   documents the main pass would index. Emitting attachment slim-doc IDs the
   main pass skips leaves permanent `chunk_count IS NULL` rows; omitting them
   incorrectly blocks pruning from cleaning up attachments after the setting
   is turned off.
7. **A `DocumentSource` value needs a matching `registry.py` entry**, or
   `factory.py:_load_connector_class` raises `ConnectorMissingException` the
   first time anyone tries to run it, not when the enum value is added.
8. **A `SourceOperations` subclass may not override `__init__`** and every
   public method on it must carry `@source_operation`; `__init_subclass__`
   enforces both at import time.
9. **`CredentialsConnector` and `load_credentials` are mutually exclusive in
   practice.** `factory.py:instantiate_connector` picks one path via
   `isinstance`. A connector that implements `CredentialsConnector` should make
   `load_credentials` raise (as Confluence and Slack do), so a caller cannot
   accidentally reach the wrong path.

---

## 6. Relationships

**Depends on**
- [[cc-pairs-and-credentials]]: owns `Connector`, `Credential`, and
  `ConnectorCredentialPair`; this component only reads
  `connector_specific_config` and decrypted credential JSON at run time.
- [[file-store-and-user-files]]: `RawFileCallback` staging for attachments and
  the tabular/CSV staging path in `cross_connector_utils/tabular_section_utils.py`.
  `backend/onyx/file_processing/extract_file_text.py:extract_text_and_images`
  is where a connector hands off a raw file for parsing into
  `TextSection`/`ImageSection` content.
- [[background-jobs]]: every fetch, prune, hierarchy-fetch, and targeted-reindex
  run is a Celery task driving this component's interfaces.
- [[access-control]]: `ExternalAccess` is defined and consumed there; a
  connector only produces the value.

**Depended on by**
- [[indexing-pipeline]]: the sole consumer of the `Document`/`HierarchyNode`/
  `ConnectorFailure` batches `ConnectorRunner` yields.
- [[permission-sync]]: EE perm-sync jobs drive `SlimConnectorWithPermSync` and
  `CheckpointedConnectorWithPermSync`, and reuse `SourceOperations` gateways
  (Slack, Outlook) for permission API calls.
- [[document-index]]: indirectly, through the documents this component
  supplies to indexing.
- [[federated-search]]: `FederatedConnectorSource` maps a federated pseudo-source
  back to the `DocumentSource` whose connector code (Slack) it partially reuses.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new connector | `DocumentSource` enum, `registry.py:CONNECTOR_CLASS_MAP`, the class itself, `web/src/lib/connectors/connectors.tsx` (`connectorConfigs`), `web/src/lib/sources.ts` (`SOURCE_METADATA_MAP`), a folder under `backend/tests/daily/connectors/`, and (if attachments exist) the `include_attachments` gating on both the main and slim pass |
| changes the `Document`/`Section`/`SlimDocument` model | every connector that constructs one directly (no central factory does this for them); [[indexing-pipeline]]'s consumption of the new/changed field; the dedup logic keyed on `Document.id` and `content_hash` |
| changes `interfaces.py` (adds/renames a base class or method) | `factory.py:_validate_connector_supports_input_type` and `identify_connector_class`; `connector_runner.py`'s `isinstance` branches; every connector implementing the affected interface |
| changes checkpoint serialization (`ConnectorCheckpoint` or a subclass) | `validate_checkpoint_json` for that connector; any in-flight, persisted checkpoint from a prior run becomes unreadable, which [[indexing-pipeline]]'s resume logic must handle |
| changes `capabilities.py` or the `CredentialCapability` enum | `capability_checks/applicability.py`, `registry.py`, `runner.py`, and the `credential_capability_report` schema; the admin UI surface that reads capability reports |
| changes `source_operations.py`'s decorator or `SourceOperations` base | every existing gateway (`slack`, `confluence`, `onedrive`, `outlook` `source_operations.py`) and the import-fence test guarding SDK imports |
| changes pruning's diff logic | the invariant in §5.5; verify a connector auth failure still raises rather than producing an empty slim result |
| touches `credentials_provider.py` | the Redis lock TTL and rotation semantics for every `CredentialsConnector`; static-credential paths used by daily tests |

---

## 8. How to verify a change

### Tests

```bash
# One directory per source; this is the primary way a connector is tested
uv run pytest backend/tests/daily/connectors/confluence/

# Isolated, mockable logic only (rare for connectors)
uv run pytest backend/tests/unit -k connector

# External-dependency unit tests: real Postgres/Redis/OpenSearch, connector
# instantiated directly, selective mocking of the source API
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/connectors
```

Daily connector tests (`backend/tests/daily/connectors/<source>/`) declare real
credential requirements with `@pytest.mark.secrets(TestSecret.X)` (see
`backend/tests/daily/connectors/confluence/test_confluence_basic.py`), resolved
by `backend/tests/utils/aws_secrets.py` in order: process env vars, the
gitignored `.vscode/.env`, then AWS Secrets Manager. Root `AGENTS.md` and
`backend/CLAUDE.md` are authoritative on this mechanism; do not skip a test for
lack of a key, ask instead. The shared helper
`backend/tests/daily/connectors/utils.py:load_all_from_connector` drives
`load_from_checkpoint`/`load_from_checkpoint_with_perm_sync` and returns the
`Document` list a test asserts against.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000/admin/connectors`, sign in as
   `admin_user@example.com` / `TestPassword123!`.
3. Add a connector for a source you changed, watch it move through indexing to
   a document count on the connector status page.
4. Confirm the documents are searchable in chat.
5. If you touched pruning or slim logic: delete a document at the source,
   trigger a prune run, confirm the document disappears from the index and not
   more than that document.

### What "working" looks like

- No `ConnectorMissingException` at run time for a source with a registry entry.
- Index count matches the source's actual document count after a full run.
- A prune run removes only documents actually deleted at the source.
- A resumed checkpointed run does not reprocess documents from before the
  checkpoint, and does not skip documents added after it.

---

## 9. Footguns

- **`DocumentFailure.document_id` must equal the `Document.id` the connector
  indexes, not a source-native id.** The internal producer
  (`indexing/indexing_pipeline.py`, `DocumentFailure(document_id=document.id)`)
  sets the convention, and three consumers compare it directly against
  `Document.id`: `background/celery/tasks/docprocessing/tasks.py`
  (`document.id not in failed_document_ids`),
  `background/indexing/run_targeted_reindex.py` (`{d.id for d in documents} -
  failed_ids`), and `background/celery/celery_utils.py:_get_failure_id` (pruning
  preservation). Every connector follows it (#14962): for example Confluence
  passes `page_url`, GitHub `html_url`, Jira `build_jira_url(...)`, and Zendesk
  `article:{id}` / `zendesk_ticket_{id}`. A mismatched id breaks targeted reindex:
  Confluence's `reindex` extracts the page id from a URL, so a bare numeric id can
  never be repaired. Gong and SharePoint pass `"unknown"` only when the source
  returns no id at all. Copy an existing connector's failure site when you add
  one.
- **The pruning framework trusts the connector to raise on auth failure.**
  There is no zero-count safety net (§5.5). A connector that catches a 401 and
  returns an empty generator will look, to pruning, exactly like "the source
  deleted everything."
- **`InputType.EVENT` is rejected for every connector.** `factory.py` raises when a connector is built with `InputType.EVENT`, so no event-driven path exists.
- **A missing `registry.py` entry only fails at first use**, not at import
  time or when the `DocumentSource` enum value is added, so a half-finished
  connector can sit invisible until someone tries to run it.
- **`load_credentials` and `set_credentials_provider` look like two optional
  hooks but are meant to be exclusive.** Confluence and Slack make this
  explicit by raising `NotImplementedError` in `load_credentials`. A connector
  that implements both silently picks whichever `factory.py`'s `isinstance`
  check favors (`CredentialsConnector` wins).
- **Checkpoint shape varies enormously.** `GoogleDriveCheckpoint` is a
  multi-stage state machine with a per-user completion map, not a cursor. Do
  not assume a checkpoint is small or simple when reasoning about serialization
  changes.
- **`SourceOperations` is opt-in and mostly unused.** Only Slack, Confluence,
  OneDrive, and Outlook have a gateway; most connectors still make source-API calls inline, so the
  "one file that talks to the source" guarantee only holds for those four today.
- **`include_attachments` default differs by connector age.** New connectors
  default to `False`; connectors retrofitted with the flag default to `True`
  to preserve existing behavior for connector rows that predate the setting.
  Copying a default from the wrong kind of connector silently changes behavior
  for existing users.
