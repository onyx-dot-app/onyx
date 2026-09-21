# CC-Pairs and Credentials

> The unit of ingestion. A connector describes how to pull from a source. A
> credential holds the encrypted secret for one account on that source. A
> `ConnectorCredentialPair` (cc-pair) joins the two and is the object every other
> system actually operates on.

**Domain:** ingestion
**Edition:** CE, with EE additions for real encryption and sync-type access
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
`web/src/app/admin/add-connector/`, `web/src/app/admin/connectors/`,
`web/src/app/admin/connector/`, `web/src/app/admin/indexing/`

**Read first:** [[connectors]] for what a connector implementation does once it
runs, and the ingestion vocabulary entry in `GLOSSARY.md`.

---

## 1. What the user experiences

An admin picks a source tile in `web/src/app/admin/add-connector/page.tsx`
(`listSourceMetadata`), fills in the connector's config (URLs, spaces, scopes),
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
| POST | `/manage/admin/connector-with-mock-credential` | | `server/documents/connector.py` |
| DELETE | `/manage/admin/connector/{connector_id}` | | `server/documents/connector.py:1666` |
| POST | `/manage/admin/connector/run-once` | | Triggers one manual index attempt. |
| GET | `/manage/admin/connector/indexing-status` | | Backs the indexing status admin page. |
| POST | `/manage/connector-request` | | Public "request a connector" form. |
| POST | `/manage/credential`, `POST /manage/credential/private-key` | `create_credential_from_model` | `server/documents/credential.py` |
| GET | `/manage/credential`, `/manage/credential/{id}` | `list_credentials`, `get_credential_by_id` | `server/documents/credential.py` |
| PATCH | `/manage/credential/{id}` | `update_credential_from_model` | |
| PUT | `/manage/admin/credential/{id}`, `PUT /manage/admin/credential/private-key/{id}` | `update_credential_data` | Admin-only, any user's credential. |
| DELETE | `/manage/admin/credential/{id}` | `delete_credential_by_id_admin` | |
| PUT | `/manage/admin/credential/swap` | `swap_credentials_for_connector` | Swaps the credential a cc-pair uses. |
| GET | `/manage/admin/credential`, `/manage/admin/similar-credentials/{source}` | | Admin listing, masked. |
| GET, POST | `/connector/oauth/*` | `server/documents/standard_oauth.py` | Connector-side OAuth authorization flow. |
| PUT | `/manage/connector/{connector_id}/credential` | `associate_credential_to_connector` | `server/documents/cc_pair.py:797`. Creates the cc-pair. |
| DELETE | `/manage/connector/{connector_id}/credential/{credential_id}` | `dissociate_credential_from_connector` | Hard-deletes the pairing row directly (no background cleanup); used when the pairing has no indexed documents yet. |
| GET | `/manage/admin/cc-pair/{id}` | `get_cc_pair_full_info` | `server/documents/cc_pair.py:338` |
| PUT | `/manage/admin/cc-pair/{id}/status` | `update_cc_pair_status` | Pause/resume only. |
| PUT | `/manage/admin/cc-pair/{id}/name`, `PUT .../property` | | |
| POST | `/manage/admin/cc-pair/{id}/prune` | `prune_cc_pair` | |
| GET | `/manage/admin/cc-pair/{id}/index-attempts`, `.../errors`, `.../permission-sync-attempts`, `.../external-group-sync-attempts`, `.../get-docs-sync-status` | | Status surfaces for one cc-pair. |
| POST | `/manage/admin/deletion-attempt` | `create_deletion_attempt_for_connector_id` | `server/manage/administrative.py:149`. **The real deletion trigger.** |
| POST | `/manage/admin/targeted-reindex` | `server/documents/targeted_reindex.py` | Reindex only the documents that previously failed. |
| GET | `/manage/admin/credential-capabilities/*` | `server/documents/credential_capabilities.py` | Test a credential/connector combination without indexing. |

### Environment / config

| Variable | Effect |
|---|---|
| `ENCRYPTION_KEY_SECRET` | EE-only. If unset, credential JSON is stored base64-adjacent (encoded, not encrypted). See §5. |
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
| `source` | `DocumentSource` | Must match the connector(s) it is paired with (`credentials.py:swap_credentials_connector` enforces this on swap). |
| `credential_json` | `SensitiveValue[dict] | None`, column type `EncryptedJson()` | The secret. Never a plain dict at rest; wrapped so every read requires an explicit `.get_value(apply_mask=...)` call. |
| `user_id` | UUID, nullable, FK `user.id` ON DELETE CASCADE | Owner. `None` for the seeded public credential and for admin-created shared credentials. |
| `admin_public` | bool, default `True` | If true, any admin can use this credential regardless of owner. |
| `curator_public` | bool, default `False` | If true, curators (see [[access-control]]) can use it within their scope. |
| `time_created`, `time_updated` | | |

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
| `status` | `ConnectorCredentialPairStatus` | See §5. |
| `access_type` | `AccessType` | `public` / `private` / `sync`. See §5. |
| `in_repeated_error_state` | bool | Orthogonal to `status`: a cc-pair can be `ACTIVE` and still be erroring on every attempt. |
| `auto_sync_options` | JSONB, nullable | Source-specific config for [[permission-sync]] (e.g. Google Drive customer id / domain). |
| `last_time_perm_sync`, `last_time_external_group_sync`, `last_time_hierarchy_fetch`, `last_successful_index_time`, `last_pruned` | datetime, nullable | Watermarks each background job reads and writes. |
| `total_docs_indexed` | int | |
| `indexing_trigger` | `IndexingMode`, nullable | Set to force an out-of-band `update` or `reindex` on the next beat cycle (`connector.py:mark_ccpair_with_indexing_trigger`). |
| `processing_mode` | `ProcessingMode`, default `REGULAR` | `REGULAR` runs the full chunk/embed/index pipeline; `FILE_SYSTEM` and `RAW_BINARY` bypass it (used by Craft's file ingestion). |
| `creator_id` | UUID, nullable | Who created the pair; drives curator/groupless-ownership checks. |
| `deletion_failure_message` | str, nullable | Set when a deletion attempt fails partway. |

### Join tables

| Table | Keys | Note |
|---|---|---|
| `document_set__connector_credential_pair` | `(document_set_id, connector_credential_pair_id, is_current)` | `is_current=False` rows are the prior membership set, deleted once the document set finishes resyncing (`models.py:DocumentSet__ConnectorCredentialPair`). |
| `user_group__connector_credential_pair` | `(user_group_id, cc_pair_id, is_current)` | Same current/prior pattern, for group-scoped visibility. |
| `credential__user_group` | `(credential_id, user_group_id)` | Which groups may **use** a credential, independent of which groups can see the cc-pair's documents. |
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
  progress row for any Vespa-syncing operation, keyed by
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

`PUT /manage/connector/{connector_id}/credential` →
`cc_pair.py:associate_credential_to_connector` →
`connector_credential_pair.py:add_credential_to_connector`. This validates the
credential belongs to the user (or is public/curator-shared), validates
`AccessType.SYNC` is gated to sources that support it and requires the
business tier (`fetch_ee_implementation_or_noop("onyx.utils.tier", ...)`),
then inserts the `ConnectorCredentialPair` row with `status=SCHEDULED`.

### 4.2 Encryption

`Credential.credential_json` uses the `EncryptedJson` column type
(`models.py:EncryptedJson`). On write, `process_bind_param` calls
`encrypt_string_to_bytes` (`utils/encryption.py`), which is a
`fetch_versioned_implementation` dispatch:

- **CE (`backend/onyx/utils/encryption.py:_encrypt_string`)**: does **not**
  encrypt. It logs a warning if `ENCRYPTION_KEY_SECRET` is set and returns
  `input_str.encode()` unchanged. Ciphertext at rest in the MIT edition is
  plain UTF-8 bytes.
- **EE (`backend/ee/onyx/utils/encryption.py:_encrypt_string`)**: real AES-CBC
  with a random IV per value, keyed off `ENCRYPTION_KEY_SECRET` trimmed to a
  valid AES key size (`_get_trimmed_key`). This only runs when the EE codepath
  is loaded (`fetch_versioned_implementation` resolves to `ee.onyx...` when EE
  is installed and licensed).

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
which calls `credential.credential_json.get_value(apply_mask=mask_credential_prefix)`.
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
Pausing sets a Redis stop fence (`RedisConnector.stop.set_fence(True)`),
requests cancellation of any in-progress `IndexAttempt` rows
(`IndexingCoordination.request_cancellation`), and revokes their Celery tasks.
It updates `status=PAUSED` and immediately re-fires `CHECK_FOR_INDEXING` so the
change is picked up without waiting for the next 15-second tick. Pausing stops
new indexing, permission sync, and pruning from starting; it does not touch
already-indexed documents or their access.

### 4.6 Deletion

The admin UI's delete action calls `POST /manage/admin/deletion-attempt`
(`server/manage/administrative.py:create_deletion_attempt_for_connector_id`),
**not** the credential-dissociation endpoint (that one is a direct hard delete
used only when a pairing has no indexed documents; see §2). The real flow:

1. Permission gate: global admins can delete any cc-pair; a non-admin can only
   delete a groupless cc-pair they created (`user_owns_groupless_cc_pair`).
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
   document index (Vespa/OpenSearch) and its Postgres rows. Count `> 1` means
   another cc-pair still indexes it: the document is **not** deleted, only
   updated (`MetadataUpdateRequest`) to drop this cc-pair's contribution to
   its access list and document-set membership.
7. Once the taskset drains with zero remaining `document_by_connector_credential_pair`
   rows for the pair, `monitor_connector_deletion_taskset` deletes the
   `ConnectorCredentialPair` row itself (`delete_connector_credential_pair__no_commit`)
   and, if no other pair uses them, leaves the `Connector`/`Credential` rows
   otherwise untouched (they cascade-delete only when their own delete is
   called, e.g. `db/connector.py:delete_connector`, which is explicitly marked
   "be VERY careful" and is not on the normal deletion path).
8. `sync_record` for `SyncType.CONNECTOR_DELETION` tracks progress throughout;
   `cleanup_sync_records` clears it if the cc-pair somehow left `DELETING`
   before finishing.

`db/deletion_attempt.py:check_deletion_attempt_is_allowed` (requires the pair
be paused with no in-progress index attempt) exists but its only call site in
`administrative.py` is **commented out** ("background locking improvements"
made it redundant). Treat it as dead code, not an active gate; see §9.

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
   removes this protection for every credential-listing endpoint at once; it
   is a single global toggle, not per-request. A change that adds a new
   credential-reading endpoint must call `.get_value(apply_mask=...)`
   explicitly (the type system forces this) and must default to masked.
3. **CE does not actually encrypt credentials at rest.** `_encrypt_string` in
   `onyx/utils/encryption.py` is a passthrough. Real AES-CBC encryption is an
   EE-only implementation (`ee/onyx/utils/encryption.py`) dispatched through
   `fetch_versioned_implementation`. Do not describe CE credential storage as
   "encrypted" without this caveat.
4. **Deleting a cc-pair must not delete a document another cc-pair still
   indexes.** Verified in `document_by_cc_pair_cleanup_task`: deletion from the
   document index only happens when `get_document_connector_count() == 1`;
   otherwise the document is updated (access/doc-set membership shrinks) and
   kept. This is the load-bearing invariant for any change to the deletion
   task.
5. **`AccessType.SYNC` must only be set for sources permission-sync actually
   supports.** Enforced at creation time
   (`add_credential_to_connector` → `check_if_valid_sync_source`), gated to the
   business tier in EE. A cc-pair with `access_type=SYNC` promises that
   [[permission-sync]] is the source of truth for who can see its documents;
   `PUBLIC` and `PRIVATE` never consult external permissions.
6. **Pausing must not silently continue background work.** `update_cc_pair_status`
   must cancel in-flight index attempts and set the stop fence; a status change
   that only flips the `status` column without the Redis fence and cancellation
   calls will leave a running indexing task un-notified.
7. **The `(connector_id, credential_id)` composite primary key means a
   connector and credential can only be paired once.** `add_credential_to_connector`
   checks `existing_association` and returns a no-op success rather than a
   duplicate row.
8. **`credential.source` must match every connector it is paired with.**
   Enforced only at `swap_credentials_connector` time, not at pair-creation
   time in the same explicit way (creation relies on the UI only offering
   compatible credentials). A change that lets a mismatched pair through will
   break the connector at runtime, not at save time.

---

## 6. Relationships

**Depends on**
- [[access-control]]: `AccessType`, curator scoping (`assert_within_scope`,
  `user_owns_groupless_cc_pair`), and `credential__user_group` /
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
  (`get_all_document_indices`, `RetryDocumentIndex.delete`/`update`).
- Document sets and personas: scope themselves to a list of cc-pair ids, never
  to connector ids.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a field to `connector_specific_config` | The connector implementation that reads it ([[connectors]]), the add-connector form schema in `web/src/app/admin/add-connector/`, and whether the field is a secret that belongs in `credential_json` instead. |
| changes credential encryption (`utils/encryption.py`, EE variant, or `rotate_encryption_key.py`) | Both CE and EE code paths; `SensitiveValue`'s `is_json` branch; every `.get_value(apply_mask=...)` call site (there are 60+) still needs to decrypt correctly; run a rotation dry-run against a populated `credential` table. |
| changes `AccessType` (adding a value, changing semantics) | [[permission-sync]] (what `SYNC` means to it), [[access-control]] (`build_only_permission_sync_included_where`-style clauses in `connector_credential_pair.py`), and every place that special-cases `PUBLIC`/`SYNC` in a `where_clause`. |
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
- **`check_deletion_attempt_is_allowed` (`db/deletion_attempt.py`) is dead
  code.** Its only caller is commented out in
  `server/manage/administrative.py`. Do not assume it still gates anything;
  the actual guard against deleting an actively-indexing cc-pair is the
  Redis-fenced `TaskDependencyError` retry loop in the Celery task.
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
  Confusing this with the cc-pair's own `access_type` (which governs document
  visibility, not credential usability) is a distinct and separate scoping
  question.
