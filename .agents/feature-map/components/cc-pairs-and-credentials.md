# CC-Pairs and Credentials

> The unit of ingestion. A connector describes how to pull from a source. A
> credential holds the encrypted secret for one account on that source. A
> `ConnectorCredentialPair` (cc-pair) joins the two and is the object every other
> system actually operates on.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** ingestion
**Edition:** CE, with EE providing real encryption (loaded by default) and sync-type access
**Owns:**
`backend/onyx/db/connector_credential_pair.py`, `connector.py`, `credentials.py`,
`credential_capability.py`, `connector_alerts.py`, `deletion_attempt.py`,
`sync_record.py`, `targeted_reindex.py`, `oauth_config.py` (connector OAuth
authorization state), `backend/onyx/connectors/credentials_provider.py`,
`backend/onyx/server/documents/` (`cc_pair.py`, `connector.py`, `credential.py`,
`credential_capabilities.py`, `standard_oauth.py`, `targeted_reindex.py`),
`backend/onyx/server/manage/administrative.py` (`create_deletion_attempt_for_connector_id`),
`backend/onyx/background/celery/tasks/connector_deletion/`,
`backend/onyx/utils/encryption.py`, `backend/onyx/utils/sensitive.py`,
`backend/onyx/db/rotate_encryption_key.py`,
`web/src/app/admin/connectors/`, `web/src/app/admin/connector/`,
`web/src/app/admin/indexing-status/`, `web/src/views/admin/connectors/`

**Read first:** [[connectors]] for what a connector implementation does once it
runs, and the ingestion vocabulary entry in `GLOSSARY.md`.

---

## 1. What the user experiences

An admin picks a source tile in the catalog at `/admin/connectors`
(`web/src/views/admin/connectors/CatalogPage.tsx`, which calls `listSourceMetadata`), fills in the connector's config (URLs, spaces, scopes),
and authenticates: either by pasting a secret into a form, uploading a file (a
service-account key), or an OAuth redirect through `/connector/oauth`
(`backend/onyx/server/documents/standard_oauth.py`). The admin then chooses who
can see the documents this connection brings in (public, private, or
group-scoped) and saves.

Saving creates three things at once: a `Connector` row (the config), a
`Credential` row (the secret), and a `ConnectorCredentialPair` row (the pairing,
with a name and a status). The pair starts `SCHEDULED`. Within 15 seconds a
background check picks it up, and the admin watches it move through
`INITIAL_INDEXING` to `ACTIVE` on the status page at
`web/src/app/admin/connector/[ccPairId]/page.tsx`, which shows index attempts,
permission-sync attempts, and any indexing errors.

The admin can pause the connection (stops new indexing, does not touch what is
already indexed), rename it, change its document-set or user-group scope, force
a prune or a targeted reindex of failed documents, or delete it. Deleting a
cc-pair does not delete the `Connector` or `Credential` rows if they are shared
with another pairing; it deletes the pairing and, for documents this pairing
owns exclusively, the documents themselves.

Document sets (`web/src/app/admin/documents/sets`, not owned here) and personas
scope themselves to a list of cc-pairs, not to connectors. Two cc-pairs on the
same connector config, each with a different credential, are two independent
things everywhere in the system: two index schedules, two access scopes, two
deletion units.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | File |
|---|---|---|---|
| POST | `/manage/admin/connector` | `create_connector_from_model` | `server/documents/connector.py` |
| POST | `/manage/admin/connector-with-mock-credential` | `create_connector_with_mock_credential`; `?paused=true` creates the pair paused and starts no indexing | `server/documents/connector.py` |
| DELETE | `/manage/admin/connector/{connector_id}` | `delete_connector_by_id` | `server/documents/connector.py` |
| POST | `/manage/admin/connector/run-once` | | Triggers one manual index attempt. |
| POST | `/manage/admin/connector/indexing-status` | | Pairs grouped by source with per-source pages; backs the Index Settings page's connector list. |
| GET | `/manage/admin/index-monitoring/overview` | `get_indexing_overview` | `server/documents/index_monitoring.py`. The indexing status page's overview card: how many readable pairs index now and are active, the documents indexed in a window (`1h`, `12h`, `24h`, `7d`) against the documents held, and the window's throughput across them. |
| GET | `/manage/admin/index-monitoring/connectors` | `get_indexing_connectors` | `server/documents/index_monitoring.py`. The indexing status page's list: the readable pairs with their latest index attempt, each in one of five buckets (indexing, failed, paused, scheduled, indexed), sorted by bucket then name, searched by name and filtered by bucket, with the bucket counts and, for admins, the federated connectors. |
| GET | `/manage/admin/index-monitoring/runs` | `get_indexing_runs` | `server/documents/index_monitoring.py`. The readable pairs' index attempts and permission syncs as one feed, newest first, with the same filters as a pair's `/runs`; each run names its pair and whether the caller may resolve its document errors. Backs the status page's Activities card. |
| POST | `/manage/admin/index-monitoring/runs/resolve` | `resolve_indexing_runs` | `server/documents/index_monitoring.py`. Marks resolved every open run of one activity level (`failures` or `errors`), or of both when the body names no `level`, that the fleet feed lists for the body's `q`, `since` and `kinds`, on the pairs the caller holds `CCPairAccessLevel.OPERATE` on. Needs `MANAGE_CONNECTORS` (global or scoped). One INSERT from SELECT per kind over the feed's own builders (`resolve_matching_runs__no_commit`, `db/cc_pair_runs.py`); a run resolved before keeps its first resolution and is not counted. Returns `resolved_count` and the `cc_pair_ids` it marked runs on, so the client refetches only those feeds. Backs the activity panel's "Resolve all shown". |
| GET | `/manage/admin/index-monitoring/runs/resolvable-count` | `get_resolvable_indexing_runs_count` | How many runs `/runs/resolve` would mark for the same `level` (optional, both levels without it), `q`, `since` and `kinds` (query params), on the same operated pairs (`count_matching_runs`, `db/cc_pair_runs.py`). The activity panel shows "Resolve all shown" only when it is above zero and states it in the confirm. |
| POST | `/manage/connector-request` | | Public "request a connector" form. |
| POST | `/manage/credential`, `POST /manage/credential/private-key` | `create_credential_from_model` | `server/documents/credential.py` |
| GET | `/manage/credential`, `/manage/credential/{id}` | `list_credentials`, `get_credential_by_id` | `server/documents/credential.py` |
| PATCH | `/manage/credential/{id}` | `update_credential_from_model` | Changes the values. Keeps the owner. |
| PUT | `/manage/admin/credential/{id}`, `PUT /manage/admin/credential/private-key/{id}` | `update_credential_data` | Global `MANAGE_CONNECTORS` only. Changes a credential the caller can edit (§4.7). Keeps the owner. |
| PUT | `/manage/admin/credential/{id}/sharing` | `update_credential_sharing_endpoint` | Changes `admin_public`, `groups` (EE) and the name of a credential the caller can edit (§4.7). Checks the groups exist and runs `assert_within_scope` on the stored and requested groups. CE refuses groups. |
| DELETE | `/manage/admin/credential/{id}` | `delete_credential_by_id_admin` | |
| DELETE | `/manage/credential/{id}`, `/manage/credential/force/{id}` | | Owner delete, and delete that also removes the pairs that use the credential. |
| PUT | `/manage/admin/credential/swap` | `swap_credentials_for_connector` | Swaps the credential a cc-pair uses. |
| GET | `/manage/admin/credential`, `/manage/admin/similar-credentials/{source}` | | Credentials the caller can use (§4.7), masked. Each snapshot carries `groups` and `is_owner`. |
| GET, POST | `/connector/oauth/*` | `server/documents/standard_oauth.py` | Connector-side OAuth authorization flow. |
| PUT | `/manage/connector/{connector_id}/credential/{credential_id}` | `associate_credential_to_connector` | `server/documents/cc_pair.py`. Creates the cc-pair. Takes `ConnectorCredentialPairMetadata`, including manage-access groups and data-access groups. |
| DELETE | `/manage/connector/{connector_id}/credential/{credential_id}` | `dissociate_credential_from_connector` | Hard-deletes the pairing row directly (no background cleanup); used when the pairing has no indexed documents yet. |
| GET | `/manage/admin/cc-pair/{id}` | `get_cc_pair_full_info` | `server/documents/cc_pair.py` |
| PUT | `/manage/admin/cc-pair/{id}/status` | `update_cc_pair_status` | Pause/resume only. |
| PUT | `/manage/admin/cc-pair/{id}/name`, `PUT .../property` | | |
| POST | `/manage/admin/cc-pair/{id}/prune` | `prune_cc_pair` | |
| GET | `/manage/admin/cc-pair/{id}/index-attempts`, `.../get-docs-sync-status` | | Status surfaces for one cc-pair. |
| GET | `/manage/admin/cc-pair/{id}/errors` | `get_cc_pair_indexing_errors` | The pair's indexing errors, newest first, paged. `include_resolved` adds resolved ones, `index_attempt_id` keeps one attempt's, and `q` matches the message or document id. Each error carries `document_name`, the indexed document's `semantic_id`, or null when the document has no row. |
| GET | `/manage/admin/cc-pair/{id}/runs` | `get_cc_pair_runs` | The pair's index attempts plus, for a perm-synced pair, its document permission and group syncs, as one feed newest first. One SQL union pages it (`db/cc_pair_runs.py`). Index attempts come from the current search settings and, during a model switch, the FUTURE ones too, so the switch's document errors show before the swap; `is_new_model` on the attempt marks them, and the activity panel tags them "New model". Throughput and the indexing-pairs count stay on the current settings. Filters: time window (`since`, plus an exclusive `until` that a click on a throughput chart slice sets, on the connector page and the status page's history panel; a run still in progress is listed whatever its age), kinds, status groups, error text (an index attempt's document errors included), `errors` (runs with open document errors, runs whose document errors were all resolved, or runs with none), `superseded`, and `resolved`. A failed run is superseded when a newer run of the same kind has succeeded or failed on the same history (a run still in progress, canceled or interrupted supersedes nothing): the same pair (an index attempt also under the same search settings, targeted reindexes excluded; a check run on the same credential and connector; a group sync on the same source when its source logs one sync for all its pairs). `superseded=false` leaves those runs out, `true` keeps only them, or with `errors` adds them to what `errors` keeps. A run is resolved when an admin marked it so (`cc_pair_run_resolution`, one row per kind and run id, `db/cc_pair_run_resolution.py`); `resolved` reads those runs the same way `superseded` reads superseded ones, and each run carries `resolved_at`. A resolved run keeps its status. The activity panel's levels each have open and closed runs: failures are failed runs neither resolved nor superseded, and its closed runs are the resolved or superseded failures; errors are runs with open document errors that are not resolved, and its closed runs are the resolved ones plus the runs whose document errors were all resolved; other has no closed runs. The panel's "Resolved" toggle, beside its level dropdown, shows each level's closed runs in place of its open ones, each element faded on a neutral card, with a "Resolved" badge; level counts stay open runs only. An open failure or error card shows a single "Resolve" action on hover or focus. A search drops the superseded filter, so old failures stay findable under failures. Status counts ignore the status filter and honor the rest, superseded included. A source whose group sync covers all its pairs shows that source's group syncs on every pair. |
| POST | `/manage/admin/cc-pair/{id}/runs/resolve` | `resolve_cc_pair_runs` | Marks runs of the pair's feed resolved, given as kind and run id. Each must have failed or hold open document errors. Needs `MANAGE_CONNECTORS` (global or scoped) and `CCPairAccessLevel.OPERATE`, as the targeted reindex does; `can_resolve_runs` on the fleet feed's `CCPairRef` says the caller has both. A run resolved before keeps its first resolution. |
| POST | `/manage/admin/cc-pair/{id}/runs/resolve-matching` | `resolve_matching_cc_pair_runs` | The pair's variant of `/index-monitoring/runs/resolve`: marks resolved every open run of the level, or of both levels, that the pair's feed lists for the filter, with the same permissions as `/runs/resolve`, and returns `resolved_count` and `cc_pair_ids`. The activity panel's "Resolve all shown" button, beside its level dropdown, shows when the level shown is All Levels, failures or errors, the Resolved view is off, and the matching `resolvable-count` is above zero. It is disabled until the list and count match the search typed. The confirm states that count and fixes the level and search when it opens, then posts them and refreshes the feeds. |
| GET | `/manage/admin/cc-pair/{id}/runs/resolvable-count` | `get_resolvable_cc_pair_runs_count` | The pair's variant of `/index-monitoring/runs/resolvable-count`, with the permissions of `resolve-matching`. |
| POST | `/manage/admin/index-attempt/{id}/cancel` | `cancel_index_attempt` | Cancels one running or queued attempt. Needs `CCPairAccessLevel.OPERATE`. Shares the pause route's cancel helper. |
| GET | `/manage/admin/cc-pair/{id}/hierarchy-breakdown` | `get_cc_pair_hierarchy_breakdown` | `server/documents/hierarchy_breakdown.py`. Node type → `{raw_node_id, display_name, link, doc_count}` rows: the pair's indexed documents in each node's subtree. `other_doc_count`: the indexed documents in no listed node's subtree. `null` until a full index run of the pair succeeds (under any search settings). Computed live; a separate route so the detail page stays fast. See [[connectors]] §4.9. |
| POST | `/manage/admin/deletion-attempt` | `create_deletion_attempt_for_connector_id` | `server/manage/administrative.py`. **The real deletion trigger.** Needs `CCPairAccessLevel.EDIT` on the pair. |
| POST, GET | `/manage/admin/indexing/targeted-reindex`, `/manage/admin/indexing/targeted-reindex/{job_id}` | `server/documents/targeted_reindex.py` | Reindex only the documents that previously failed, and read the job. |
| POST, GET | `/manage/admin/credential/{id}/capability-check`, `/capability-report`, `/manage/admin/credential/capability-reports`, `/manage/admin/credential/{id}/binding-check` | `server/documents/credential_capabilities.py` | Test a credential/connector combination without indexing. See [[connectors]] §4.8. |
| GET, PUT | `/manage/admin/cc-pair/{id}/data-access`, `/manage-access`; GET `/manage/admin/manage-access-prefill` | `ee/onyx/server/documents/cc_pair.py` | EE only. Data-access groups decide who reads the pair's documents. Manage-access groups, each with a role, decide who administers it. See [[access-control]]. |

### Environment / config

| Variable | Effect |
|---|---|
| `ENCRYPTION_KEY_SECRET` | The AES key. Encryption needs both this value and EE code loaded, which is the default. If unset, credential JSON is stored unencrypted. See §4.2. |
| `MASK_CREDENTIAL_PREFIX` | Default `True`. Gates whether credential-listing endpoints mask secret values. See §5. |
| `DEFAULT_PRUNING_FREQ` | `connector.py:update_connector` default when `prune_freq` is omitted. |

---

## 3. Data model

### `connector`

| Column | Type | Meaning |
|---|---|---|
| `id` | int, PK | |
| `name` | str | |
| `source` | `DocumentSource` | The source type (confluence, slack, ...). |
| `input_type` | `InputType` | Poll, load state, event, etc. |
| `connector_specific_config` | JSONB | Per-source config (URLs, spaces, folders). Not a secret; not encrypted. |
| `refresh_freq` | int seconds, nullable | Re-index interval. `None` means never auto-index. |
| `prune_freq` | int seconds, nullable | Interval for the pruning job (owned by [[connectors]]). |
| `indexing_start` | datetime, nullable | Earliest document time to pull. |
| `kg_processing_enabled`, `kg_coverage_days` | | Knowledge-graph extraction flags. |

Connector id `0` is a permanent seeded row for the Ingestion API
(`connector.py:create_initial_default_connector`), always present.

### `credential`

| Column | Type | Meaning |
|---|---|---|
| `id` | int, PK | Id `0` is a permanent seeded public credential (`credentials.py:create_initial_public_credential`) for sources that need no auth. |
| `name` | str, nullable | |
| `source` | `DocumentSource` | Must be usable by the paired connector(s). A compatible family credential may have a different source (`credential_families.py:is_credential_usable_for_source`, checked in `credentials.py:swap_credentials_connector` on swap). |
| `credential_json` | `SensitiveValue[dict] | None`, column type `EncryptedJson()` | The secret. Never a plain dict at rest; wrapped so every read requires an explicit `.get_value(apply_mask=...)` call. |
| `user_id` | UUID, nullable, FK `user.id` ON DELETE CASCADE | Owner. `None` for the seeded public credential and for admin-created shared credentials. |
| `admin_public` | bool, default `True` | If true, every global `MANAGE_CONNECTORS` holder can use this credential regardless of owner. Group managers do not count. See §4.7. |
| `curator_public` | bool, default `False` | Kept for older clients. Grants no access. A scoped manager cannot set it (`assert_within_scope` treats it as public). |
| `is_draft` | bool, default `False` | A new account in a connector form, saved before its connector (`server/documents/draft_credentials.py`). Credential listings and lookups leave drafts out; only the owner's form reads its own. `POST /admin/connector-with-credential` promotes it, and `CLEANUP_STALE_DRAFT_CREDENTIALS` deletes drafts unchanged for 7 days. See [[connectors]]. |
| `time_created`, `time_updated` | | A draft's `time_updated` names it in the draft check-result cache, so promotion keeps it. |

### `connector_credential_pair`

Composite: `connector_id` and `credential_id` are **both** primary-key columns
(`models.py:ConnectorCredentialPair`), plus a separate `id` (sequence-backed,
`unique`, not the PK) used everywhere else as the pair's identity. Confusingly,
foreign keys into this table (`document_set__connector_credential_pair`,
`user_group__connector_credential_pair`, `hierarchy_node_by_connector_credential_pair`)
reference the `id` column, while `document_by_connector_credential_pair`
references the `(connector_id, credential_id)` pair directly.

| Column | Type | Meaning |
|---|---|---|
| `id` | int, unique, Sequence-backed | The identifier used by nearly every other table and API. |
| `connector_id`, `credential_id` | int, PK (composite) | |
| `name` | str | |
| `status` | `ConnectorCredentialPairStatus` | `SCHEDULED`, `INITIAL_INDEXING`, `ACTIVE`, `PAUSED`, `DELETING`, `INVALID`. See §5. |
| `access_type` | `AccessType` | `public` / `private` / `sync` / `sync_restricted`. `sync_restricted` is perm sync narrowed to members of the pair's data-access groups. See §5. |
| `in_repeated_error_state` | bool | Orthogonal to `status`: a cc-pair can be `ACTIVE` and still be erroring on every attempt. |
| `auto_sync_options` | JSONB, nullable | Source-specific config for [[permission-sync]] (e.g. Google Drive customer id / domain). |
| `last_time_perm_sync`, `last_time_external_group_sync`, `last_time_hierarchy_fetch`, `last_successful_index_time`, `last_pruned` | datetime, nullable | Watermarks each background job reads and writes. |
| `total_docs_indexed` | int | |
| `indexing_trigger` | `IndexingMode`, nullable | Set to force an out-of-band `update` or `reindex` on the next beat cycle (`connector.py:mark_ccpair_with_indexing_trigger`). |
| `processing_mode` | `ProcessingMode`, default `REGULAR` | `REGULAR` runs the full chunk/embed/index pipeline. `RAW_BINARY` writes raw bytes to S3 with no text extraction. `FILE_SYSTEM` is deprecated: it bypasses indexing and is not searchable. Listing queries filter to `REGULAR` by default. |
| `creator_id` | UUID, nullable | Who created the pair; drives curator/groupless-ownership checks. |
| `deletion_failure_message` | str, nullable | Set when a deletion attempt fails partway. |

### Join tables

| Table | Keys | Note |
|---|---|---|
| `document_set__connector_credential_pair` | `(document_set_id, connector_credential_pair_id, is_current)` | `is_current=False` rows are the prior membership set, deleted once the document set finishes resyncing (`models.py:DocumentSet__ConnectorCredentialPair`). |
| `user_group__connector_credential_pair` | `(user_group_id, cc_pair_id, is_current)`, plus `role` | Same current/prior pattern. The groups that manage the pair. `role` is `ConnectorManageRole` (`EDITOR` changes and deletes, `OPERATOR` schedules and monitors). |
| `user_group__cc_pair_data_access` | `(cc_pair_id, user_group_id)` | The data-access groups: who may read the pair's documents (`models.py:UserGroup__CCPairDataAccess`). |
| `credential__user_group` | `(credential_id, user_group_id)` | Which groups may **use** a credential (EE), independent of which groups can see the cc-pair's documents. See §4.7. |
| `document_by_connector_credential_pair` | `(id=document_id, connector_id, credential_id)` | The fan-out table: one row per (document, cc-pair) that indexed it. `get_document_connector_count` (`db/document.py:get_document_connector_count`) counts these rows to decide whether a document is orphaned on deletion. See §5. |
| `hierarchy_node_by_connector_credential_pair` | `(hierarchy_node_id, connector_id, credential_id)` | Folder/space tree ownership, cleaned up the same way during pruning. |

### Entity diagram

```
Connector (1) ---< ConnectorCredentialPair >--- (1) Credential
                          |  ^
                          |  |
                          v  |
              DocumentSet__CCPair      UserGroup__CCPair
                          |
                          v
           DocumentByConnectorCredentialPair >--- Document
                          |
                          v
                     IndexAttempt (owned by [[indexing-pipeline]])
```

### Other tables owned here

- `credential_capability_report` (`models.py:CredentialCapabilityReportRow`,
  `db/credential_capability.py`): the latest "does this credential/connector
  combination actually work" probe result, one row per credential (config-less)
  and one per `(credential, connector)` scope, enforced by two partial unique
  indexes.
- `sync_record` (`models.py:SyncRecord`, `db/sync_record.py`): a generic
  progress row for any document-index syncing operation, keyed by
  `(entity_id, sync_type)`. Connector deletion is `SyncType.CONNECTOR_DELETION`
  with `entity_id = cc_pair_id`; `monitor_connector_deletion_taskset`
  (`background/celery/tasks/connector_deletion/tasks.py`) updates it as the
  taskset drains.
- `targeted_reindex_job` / `targeted_reindex_job_target`
  (`models.py:TargetedReindexJob`): a user-initiated retry of the specific
  documents that failed on a prior index attempt, not a general reindex. One
  job can span multiple `(cc_pair, search_settings)` tuples; the per-document
  work list is `targeted_reindex_job_target`.
- Connector alerts (`db/connector_alerts.py`) are **not** a dedicated table.
  They are `Notification` rows deduped by `additional_data={"cc_pair_id": ...}`
  (`connector_alerts.py:connector_alert_additional_data`), owned by
  [[background-jobs]]'s notification system.
- There is no `DeletionAttempt` table. "Deletion attempt" is a status
  transition (`ConnectorCredentialPairStatus.DELETING`) plus Redis fencing; see
  §4.

---

## 4. How it works

### 4.1 Create

`PUT /manage/connector/{connector_id}/credential/{credential_id}` →
`cc_pair.py:associate_credential_to_connector` →
`connector_credential_pair.py:add_credential_to_connector`. This validates the
user can use the credential (§4.7), validates
`AccessType.SYNC` is gated to sources that support it and requires the
business tier (`fetch_ee_implementation_or_noop("onyx.utils.tier", ...)`),
then inserts the `ConnectorCredentialPair` row with `status=SCHEDULED`. The gate applies to both `SYNC` and `SYNC_RESTRICTED` (`AccessType.is_perm_synced`). The call also writes the manage-access groups and data-access groups.

### 4.2 Encryption

`Credential.credential_json` uses the `EncryptedJson` column type
(`models.py:EncryptedJson`). On write, `process_bind_param` calls
`encrypt_string_to_bytes` (`utils/encryption.py`), which is a
`fetch_versioned_implementation` dispatch:

- **EE (`backend/ee/onyx/utils/encryption.py:_encrypt_string`)**: real AES-CBC
  with a random IV per value, keyed off `ENCRYPTION_KEY_SECRET` trimmed to a
  valid AES key size (`_get_trimmed_key`).
- **CE (`backend/onyx/utils/encryption.py:_encrypt_string`)**: a passthrough.
  It logs a warning if `ENCRYPTION_KEY_SECRET` is set and returns
  `input_str.encode()` unchanged, so the value is stored as plain UTF-8 bytes.

**Which one runs is not what the edition names suggest.** The EE implementation
is the default in a standard deployment. `set_is_ee_if_available`
(`onyx/utils/variable_functionality.py`) calls `global_version.set_ee()`
whenever the build ships the `ee.onyx` package (`is_ee_available` in the same
file).
The `ee` package ships in the standard backend image (`backend/Dockerfile`
copies `./ee` to `/app/ee`), so `fetch_versioned_implementation` resolves the
EE symbol and real AES encryption runs with or without a license.

The CE passthrough is therefore reached only when EE code is genuinely absent:
an image built without `ee/onyx`. In that build
credentials are stored unencrypted and the only signal is a log warning.

On read, `process_result_value` never decrypts eagerly. It wraps the encrypted
bytes in `SensitiveValue` (`utils/sensitive.py:SensitiveValue`), which raises
`SensitiveAccessError` on almost every implicit use (`__str__`, `__iter__`,
`__getitem__`, JSON serialization) and forces the caller to call
`.get_value(apply_mask=True|False)` explicitly.

`rotate_encryption_key.py` walks every ORM column typed `EncryptedString` or
`EncryptedJson` (`_discover_encrypted_columns`, reflection over
`Base.registry.mappers`), decrypts each value with the old key
(`decrypt_bytes_to_string`), skips rows already readable with the current key
(`_can_decrypt_with_current_key`), and re-encrypts in batches of 500. It is
idempotent and resumable.

### 4.3 Masking on read

Every admin-facing credential response goes through
`CredentialSnapshot.from_credential_db_model` (`server/documents/models.py:153`),
which calls `credential.credential_json.get_value(apply_mask=False)` and then
applies `mask_credential_dict` when `mask_credential_prefix` is true.
`mask_credential_prefix` comes from `get_security_settings().mask_credential_prefix`
(`server/security/store.py:106`), sourced from `MASK_CREDENTIAL_PREFIX`
(`configs/app_configs.py`, **default `True`**). When masked,
`mask_credential_dict` / `mask_string` (`utils/encryption.py`) show only the
first and last 4 characters of each string value, or a fixed placeholder for
short values; a small allowlist (`MASK_CREDENTIALS_WHITELIST`: scopes, cloud
IDs, the Google auth-method discriminator) passes through unmasked because
those fields are not secrets. `reject_masked_credentials` and
`restore_masked_credentials` handle the round-trip so a client editing a
credential form can submit the masked placeholder back unchanged without
overwriting the real secret with the mask string.

The credential endpoints (`server/documents/credential.py`), the cc-pair full
info and `GET /manage/admin/connector/status` also mask a credential the caller
cannot edit (§4.7), whatever the setting: `credential.py:credential_ids_to_mask`.
A user a credential is shared with can reuse it but never reads its secret.
The user-group and document-set responses still follow the setting only.

Every internal caller that needs the real secret (the connector runtime via
`credentials_provider.py:OnyxDBCredentialsProvider.get_credentials`, OAuth
token refresh, Slack bot tokens, LLM provider keys stored the same way) calls
`.get_value(apply_mask=False)` directly against the ORM object, never through
an HTTP response model.

### 4.4 Scheduling

Celery beat fires `CHECK_FOR_INDEXING` every 15 seconds
(`background/celery/tasks/beat_schedule.py`, `work_gated: True`). The task
(`background/celery/tasks/docprocessing/tasks.py:check_for_indexing`) iterates
cc-pairs and calls `should_index`
(`background/celery/tasks/docprocessing/utils.py:should_index`) per
`(cc_pair, search_settings)`, which checks `connector.refresh_freq` against the
last attempt's time, the cc-pair's `indexing_trigger` override, embedding-swap
state (`IndexModelStatus`), and repeated-error backoff. There is no per-cc-pair
cron; every cc-pair is re-evaluated every 15 seconds against its own
`refresh_freq`.

### 4.5 Pause

`PUT /manage/admin/cc-pair/{id}/status` → `cc_pair.py:update_cc_pair_status`.
Only `ACTIVE` and `PAUSED` are accepted here (not `DELETING`; the comment at
`cc_pair.py:500` is explicit that this route must not be usable to delete).
`CCPairAccessLevel.OPERATE` is enough here. Pausing sets a Redis stop fence (`RedisConnector.stop.set_fence(True)`),
requests cancellation of any in-progress `IndexAttempt` rows
(`IndexingCoordination.request_cancellation`), and revokes their Celery tasks. A first
attempt that waits for capability checks has no task, so it is canceled directly
(`cancel_waiting_index_attempt__no_commit`).
It updates `status=PAUSED` and immediately re-fires `CHECK_FOR_INDEXING` so the
change is picked up without waiting for the next 15-second tick. Pausing stops
new indexing, permission sync, and pruning from starting; it does not touch
already-indexed documents or their access.

### 4.6 Deletion

The admin UI's delete action calls `POST /manage/admin/deletion-attempt`
(`server/manage/administrative.py:create_deletion_attempt_for_connector_id`),
**not** the credential-dissociation endpoint (that one is a direct hard delete
used only when a pairing has no indexed documents; see §2). The real flow:

1. Permission gate: `get_connector_credential_pair_for_user` with
   `CCPairAccessLevel.EDIT`. A user with global `MANAGE_CONNECTORS` passes. A scoped
   manager needs the `EDITOR` role in a group that manages the pair. The creator of a
   non-public pair with no manage group also passes.
2. Cancel any scheduled/in-progress index attempts.
3. Set `status = DELETING` and commit.
4. Fire `CHECK_FOR_CONNECTOR_DELETION` immediately (also runs on its own beat
   schedule).
5. `connector_deletion/tasks.py:try_generate_document_cc_pair_cleanup_tasks`
   fences the cc-pair in Redis (`RedisConnector.delete`), refuses to proceed
   while indexing, pruning, permission sync, or a port attempt is still
   running for it (raises `TaskDependencyError`, which the beat task turns into
   a one-time revoke-and-wait), then enqueues one
   `DOCUMENT_BY_CC_PAIR_CLEANUP_TASK` per document the pair indexed.
6. Each cleanup task
   (`background/celery/tasks/shared/tasks.py:document_by_cc_pair_cleanup_task`)
   calls `get_document_connector_count` for that document. Count `== 1` means
   this cc-pair is the document's only indexer: it is deleted from the
   document index (OpenSearch) and its Postgres rows. Count `> 1` means
   another cc-pair still indexes it: the document is **not** deleted, only
   updated (`MetadataUpdateRequest`) to drop this cc-pair's contribution to
   its access list and document-set membership.
7. Once the taskset drains with zero remaining `document_by_connector_credential_pair`
   rows for the pair, `monitor_connector_deletion_taskset` deletes the
   `ConnectorCredentialPair` row itself (`delete_connector_credential_pair__no_commit`)
   and then deletes the `Connector` row if no credentials remain on it. The
   `Credential` rows stay. They cascade-delete only when their own delete is
   called. `db/connector.py:delete_connector` is explicitly marked "be VERY
   careful" and is not on the normal deletion path.
8. `sync_record` for `SyncType.CONNECTOR_DELETION` tracks progress throughout;
   `cleanup_sync_records` clears it if the cc-pair somehow left `DELETING`
   before finishing.

`db/deletion_attempt.py:check_deletion_attempt_is_allowed` (requires the pair
be paused with no in-progress index attempt) no longer gates deletion.
It has one live call site, `server/documents/connector.py:get_currently_failed_indexing_status`,
which uses it to compute the `is_deletable` field the admin UI shows per connector.
It does not block the delete call; see §9.

### 4.7 Credential access and sharing

`db/credentials.py:_add_user_filters` decides which credentials a user can
reach, at one of two `CredentialAccessLevel`s. Drafts are hidden from all but
their owner's form.

| Who | USE (list, fetch, pair) | EDIT (change values, sharing, delete) |
|---|---|---|
| The owner | Yes | Yes |
| Global `MANAGE_CONNECTORS` holder ("admin") | No owner, `admin_public`, or a `CREDENTIAL_PERMISSIONS_TO_IGNORE` source | Same as USE |
| Manager of a group in `credential__user_group`, or member of it who holds global `MANAGE_CONNECTORS` (EE) | Yes | No |
| Anyone else | No | No |

The group clause comes from
`fetch_versioned_implementation("onyx.db.credentials", "_build_credential_group_access_clause")`:
CE returns `false()`, EE (`ee/onyx/db/credentials.py`) matches the user's
managed groups (`scoped_group_ids_subquery`), or all their non-default groups
when they hold global `MANAGE_CONNECTORS`. `validate_credential_group_ids` has
the same split: CE refuses groups, EE checks they exist. Both create paths and
`PUT /manage/admin/credential/{id}/sharing` call it through
`server/documents/credential.py:assert_credential_sharing_allowed`.

USE access lets a user see a shared credential. To pair it, swap to it, edit
its bound fields or run checks with it, a non-owner must also keep the bound
values of a pair that uses it: see [[connectors]] §4.9
(`factory.py:assert_user_can_use_credential`).

---

## 5. Contracts and invariants

1. **The cc-pair, not the connector, is what indexing, permission sync,
   document sets, user groups, and deletion operate on.** A `Connector` row
   can be shared by several cc-pairs with different credentials and different
   access scopes; code that keys off `connector_id` alone is almost always
   wrong. See `db/models.py:ConnectorCredentialPair` docstring.
2. **Credentials are never returned in plaintext by a normal API response.**
   Verified: every admin/user-facing credential endpoint routes through
   `CredentialSnapshot.from_credential_db_model` gated by
   `MASK_CREDENTIAL_PREFIX` (default `True`). Setting `MASK_CREDENTIAL_PREFIX=False`
   shows plaintext only to callers who can edit the credential (§4.3, §4.7):
   the credential endpoints, the cc-pair full info and the connector status
   still mask a credential the caller cannot edit
   (`credential.py:credential_ids_to_mask`). The user-group and document-set
   responses follow the global toggle alone. A change that adds a new
   credential-reading endpoint must call `.get_value(apply_mask=...)`
   explicitly (the type system forces this) and must default to masked.
3. **Encryption depends on whether EE code is loaded, not on the
   license.** Real AES-CBC lives only in `ee/onyx/utils/encryption.py`; the
   `onyx/utils/encryption.py` implementation is a passthrough. Dispatch goes
   through `fetch_versioned_implementation`, and EE code loads by default
   because the image ships `ee/` and `set_is_ee_if_available` loads it when
   present. So a standard deployment does encrypt. A build without `ee/onyx`
   silently stores plaintext. Any change
   to `set_is_ee_if_available`, to `is_ee_available`, or to the Dockerfile's
   `ee` copy changes credential encryption for every existing deployment.
   See §4.2.
4. **Deleting a cc-pair must not delete a document another cc-pair still
   indexes.** Verified in `document_by_cc_pair_cleanup_task`: deletion from the
   document index only happens when `get_document_connector_count() == 1`;
   otherwise the document is updated (access/doc-set membership shrinks) and
   kept. This is the load-bearing invariant for any change to the deletion
   task.
5. **`AccessType.SYNC` and `SYNC_RESTRICTED` must only be set for sources permission-sync actually
   supports.** Enforced at creation time
   (`add_credential_to_connector` → `check_if_valid_sync_source`), gated to the
   business tier in EE. A cc-pair with `access_type=SYNC` or `SYNC_RESTRICTED` promises that
   [[permission-sync]] is the source of truth for who can see its documents;
   `PUBLIC` and `PRIVATE` never consult external permissions. For `SYNC_RESTRICTED`, only members of the pair's data-access groups can see the documents their source ACL allows.
   One code path changes `access_type` on an existing pair: the Community
   downgrade (`ee/onyx/db/community_downgrade.py:make_all_cc_pairs_public__no_commit`)
   sets every pair that is not `PUBLIC` to `PUBLIC`. It also clears
   `auto_sync_options`, `last_time_perm_sync` and `last_time_external_group_sync`,
   deletes the pair's `user_group__cc_pair_data_access` rows, and marks the
   pair's documents for index sync. The index keeps the old chunk ACLs until
   the metadata sync rewrites those documents. See [[billing]] §4.5.
6. **Pausing must not silently continue background work.** `update_cc_pair_status`
   must cancel in-flight index attempts and set the stop fence; a status change
   that only flips the `status` column without the Redis fence and cancellation
   calls will leave a running indexing task un-notified.
7. **The `(connector_id, credential_id)` composite primary key means a
   connector and credential can only be paired once.** The DB helper
   `add_credential_to_connector` returns `success=False` for an existing pair.
   The API (`server/documents/cc_pair.py`) rejects a duplicate request with
   `OnyxError(CONFLICT)`. A caller must not treat a duplicate as a success.
8. **A credential must be usable by the connector's source, but its stored
   `source` need not equal the connector's source.**
   `credential_families.py:is_credential_usable_for_source` accepts a
   compatible family credential across sources.
   `db/credentials.py:swap_credentials_connector` enforces this check when a
   credential is swapped. Pair creation validates the binding through
   `factory.py:validate_ccpair_for_user`. A change that lets an unusable pair
   through will break the connector at runtime, not at save time.

---

## 6. Relationships

**Depends on**
- [[access-control]]: `AccessType`, curator scoping (`assert_within_scope`,
  `CCPairAccessLevel`, `ConnectorManageRole`), and `credential__user_group` /
  `user_group__connector_credential_pair` all extend the group/ACL model owned
  there.
- [[auth-and-identity]]: `Credential.user_id`, the requesting `User`'s
  permissions (`Permission.MANAGE_CONNECTORS`, `BASIC_ACCESS`).
- [[background-jobs]]: Celery beat schedule, Redis fencing (`RedisConnector`),
  and the connector-deletion task queue.
- [[multi-tenancy]]: every credential and cc-pair read goes through a
  tenant-scoped session (`get_session_with_current_tenant`).

**Depended on by**
- [[connectors]]: reads the cc-pair's `Connector.connector_specific_config` and
  the credential's decrypted JSON to actually pull documents.
- [[indexing-pipeline]]: `IndexAttempt` rows key off `connector_credential_pair_id`;
  `should_index` reads cc-pair status and `refresh_freq`.
- [[permission-sync]]: reads `access_type`, `auto_sync_options`,
  `last_time_perm_sync`, `last_time_external_group_sync`.
- [[document-index]]: the deletion task writes directly to it
  (`get_default_document_index`, then `DocumentIndex.delete`/`update`).
- Document sets and personas: scope themselves to a list of cc-pair ids, never
  to connector ids.
- [[editions-and-gating]]: `connector_credential_pair.py:has_perm_synced_cc_pairs`
  decides if a self-hosted deployment with no license
  is gated (that document's §4.4).

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a field to `connector_specific_config` | The connector implementation that reads it ([[connectors]]), the add-connector form schema in `web/src/views/admin/connectors/AddConnectorPage/`, and whether the field is a secret that belongs in `credential_json` instead. |
| changes credential encryption (`utils/encryption.py`, EE variant, or `rotate_encryption_key.py`) | Both CE and EE code paths; `SensitiveValue`'s `is_json` branch; every `.get_value(apply_mask=...)` call site (there are 60+) still needs to decrypt correctly; run a rotation dry-run against a populated `credential` table. |
| changes `AccessType` (adding a value, changing semantics) | [[permission-sync]] (what `SYNC` means to it), [[access-control]] (`build_only_permission_sync_included_where`-style clauses in `connector_credential_pair.py`), and every place that special-cases `PUBLIC`/`SYNC` in a `where_clause`. Also the Community downgrade (`ee/onyx/db/community_downgrade.py:make_all_cc_pairs_public__no_commit`) and `has_perm_synced_cc_pairs`. |
| changes the deletion flow | The orphan-document invariant (§5.4) above all else; `sync_record` progress reporting; the Redis fence keys in `RedisConnector.delete`; whether `Connector`/`Credential` cascade rules still hold. |
| changes `ConnectorCredentialPairStatus` (adding/removing a value) | `active_statuses()`, `indexable_statuses()`, `is_active()`, every `status.in_([...])` check in `connector_credential_pair.py` and the deletion/indexing task modules, and the frontend status badge components under `web/src/app/admin/connector/`. |
| changes `ConnectorCredentialPair.id` vs `(connector_id, credential_id)` usage | Every join table above uses `id`; `document_by_connector_credential_pair` uses the composite pair directly. Mixing the two silently orphans rows. |
| changes masking defaults or `CredentialSnapshot` | Every admin/user credential-listing endpoint in `server/documents/credential.py`; confirm `apply_mask` still defaults to masked. |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration -k "cc_pair or credential or connector_deletion"
cd backend && uv run pytest tests/unit -k "connector_credential_pair or credentials or encryption"
```

Existing coverage worth reading before adding more:
`backend/tests/integration/tests/connector/test_connector_deletion.py`,
`backend/tests/external_dependency_unit/db/test_credential_sensitive_value.py`,
`backend/tests/external_dependency_unit/server/documents/test_associate_credential_rollback.py`,
`backend/tests/external_dependency_unit/server/documents/test_cc_pair_group_visibility.py`,
`backend/tests/unit/onyx/connectors/test_credentials_provider.py`,
`backend/tests/unit/onyx/utils/test_mask_credential_whitelist.py`. See
`backend/AGENTS.md` for the authoritative commands and required env
(`.vscode/.env` secrets).

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log` and
   `backend/log/*_worker_debug.log` (indexing and deletion run on separate
   Celery workers).
2. Sign in at `http://localhost:3000` as `admin_user@example.com` /
   `TestPassword123!`.
3. Add a connector (a source needing no real auth, e.g. Web, is fastest),
   choose an access type, save. Confirm it reaches `ACTIVE` on
   `/admin/connector/{ccPairId}`.
4. Inspect the row directly:
   ```bash
   PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres \
     -c "select id, connector_id, credential_id, status, access_type, total_docs_indexed from connector_credential_pair order by id desc limit 5;"
   ```
5. Pause it. Confirm no new `index_attempt` rows appear and existing documents
   remain searchable.
6. Delete it via the admin UI (not the API directly) and watch
   `status` move to `DELETING` then the row disappear; confirm its documents
   are gone from search if it was their only source, and confirm a document
   shared with another cc-pair (test with two connectors over the same corpus,
   e.g. two File connectors on the same file) survives with reduced access.
7. Toggle `MASK_CREDENTIAL_PREFIX=false`, restart the API server, and confirm
   `GET /manage/admin/credential` now returns full `credential_json` values,
   to understand exactly what the default protects.

### What "working" looks like

- No `connector_credential_pair` row lingers in `DELETING` after its documents
  are gone.
- A document indexed by two cc-pairs survives the deletion of one of them.
- `GET /manage/credential` never returns an unmasked secret when
  `MASK_CREDENTIAL_PREFIX` is unset or `true`.

---

## 9. Footguns

- **The cc-pair/connector conflation is the single most common misreading of
  this code.** Grepping for "connector" and patching `Connector` fields when
  the actual operative row is `ConnectorCredentialPair` is a real trap: status,
  access, schedule watermarks, and deletion state all live on the pair, not
  the connector.
- **CE credential storage is not encrypted**, despite the column type being
  named `EncryptedJson` and despite `ENCRYPTION_KEY_SECRET` existing as a
  config knob in CE. Setting `ENCRYPTION_KEY_SECRET` in CE only produces a
  warning log; it does nothing.
- **`check_deletion_attempt_is_allowed` (`db/deletion_attempt.py`) no longer
  gates deletion.** It runs only from
  `server/documents/connector.py:get_currently_failed_indexing_status`, to
  compute the `is_deletable` display field. It does not block the
  delete call. The actual guard against deleting an actively-indexing
  cc-pair is the Redis-fenced `TaskDependencyError` retry loop in the Celery
  task.
- **`DELETE /connector/{id}/credential/{id}` and
  `POST /admin/deletion-attempt` are two different delete paths** with very
  different behavior: the former is an immediate hard delete of the pairing
  row with no document cleanup (only safe when the pairing has never indexed
  anything), the latter is the full async cleanup flow. A UI or API change
  that routes an established cc-pair's delete button through the former will
  leave orphaned document rows.
- **`ConnectorCredentialPair.id` is not the primary key** of its own table
  (`connector_id`+`credential_id` is), but it is the foreign key nearly every
  other table uses. Writing a query that joins on `id` where the schema
  expects `(connector_id, credential_id)`, or vice versa, compiles but returns
  nothing.
- **`admin_public` and `curator_public` are independent booleans on
  `Credential`**, not an enum; a credential can be both, neither, or either.
  Only `admin_public` grants access; `curator_public` is stored and grants
  nothing (§4.7).
  Confusing this with the cc-pair's own `access_type` (which governs document
  visibility, not credential usability) is a distinct and separate scoping
  question.
