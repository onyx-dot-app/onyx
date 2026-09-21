# Permission Sync

> Pulling permissions from a source system into Onyx. Two independent syncs, doc
> sync (who can see this document) and group sync (who is in this external group),
> feed the raw material that [[access-control]] turns into query-time ACL strings.

**Domain:** access-control
**Edition:** EE only. There is no CE permission sync; a CE-only deployment has no
mechanism to narrow a connector's documents below "public" or "shared with an
Onyx user/group" set by hand.
**Owns:**
`backend/ee/onyx/external_permissions/` (`sync_params.py`, `perm_sync_types.py`,
`utils.py`, `post_query_censoring.py`, and the per-source `doc_sync.py` /
`group_sync.py` / `access.py` files),
`backend/ee/onyx/background/celery/tasks/doc_permission_syncing/tasks.py`,
`backend/ee/onyx/background/celery/tasks/external_group_syncing/tasks.py`,
`group_sync_utils.py`,
`backend/ee/onyx/db/external_perm.py`, `backend/ee/onyx/db/user_group.py`,
`backend/ee/onyx/db/document.py` (`upsert_document_external_perms`),
`backend/onyx/db/permission_sync_attempt.py`.

**Does not own:** how the ACL is computed from synced data or enforced at query
time ([[access-control]] owns `_get_acl_for_user`, `_get_access_for_documents`,
and the OpenSearch filter chokepoint), or how a document's ACL snapshot is
actually written into the index once it changes ([[document-index]] and
[[indexing-pipeline]] own `document_index_metadata_sync_task` and the
`needs_sync` machinery this document only describes the trigger for).

---

## 1. What the user experiences

An admin turns on permission sync by setting a connector's access type to
**Sync** instead of Public or Private, for a source that supports it (Google
Drive, Confluence, Jira, Slack, Box, Canvas, GitHub, SharePoint, Teams, Outlook,
Gmail; Salesforce is a partial case, see §4.5). From that point, Onyx does not
decide who can see a document. The source system does, and Onyx mirrors it.

The admin does not manually grant or revoke access to synced documents; the
connector's own sharing settings are authoritative. What the admin sees is a
sync attempt history per connector (recent `DocPermissionSyncAttempt` and
`ExternalGroupPermissionSyncAttempt` rows), and, indirectly, the effect: a user
who loses Drive access to a folder stops seeing its documents in Onyx search
and chat once the next sync cycle runs, not instantly.

This lag is a real product property, not a bug: permission sync is
**eventually consistent**. Between a permission change at the source and the
next successful sync plus the next index metadata write, Onyx's answer to "can
this user see this document" can be stale. See §9.

---

## 2. Surfaces

There are no end-user HTTP endpoints owned by this component; it is entirely a
background job. Its only visible surface is connector configuration
(`ConnectorCredentialPair.access_type == AccessType.SYNC`) and whatever the
admin UI renders from `PermissionSyncAttempt` rows (owned by
[[cc-pairs-and-credentials]]).

### Celery tasks

| Task | Trigger | Body |
|---|---|---|
| `CHECK_FOR_DOC_PERMISSIONS_SYNC` | Beat, every 30s, EE-gated | `doc_permission_syncing/tasks.py:check_for_doc_permissions_sync`. Scans `SYNC` cc_pairs, decides which are due (`_is_external_doc_permissions_sync_due`), fences and dispatches one generator task per due cc_pair. |
| `CONNECTOR_PERMISSION_SYNC_GENERATOR_TASK` | Dispatched by the check task | `doc_permission_syncing/tasks.py:connector_permission_sync_generator_task`. Runs one source's `doc_sync_func`, streams `DocExternalAccess`/`NodeExternalAccess` into Postgres. |
| `CHECK_FOR_EXTERNAL_GROUP_SYNC` | Beat, every 20s, EE-gated | `external_group_syncing/tasks.py:check_for_external_group_sync`. Same shape as the doc check task, for group sync. |
| `CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK` | Dispatched by the check task | `external_group_syncing/tasks.py:connector_external_group_sync_generator_task` -> `_perform_external_group_sync` -> `_timed_perform_external_group_sync`. Runs one source's `group_sync_func`, upserts `ExternalUserGroup` rows. |

Both beat entries are registered in `backend/onyx/background/celery/tasks/beat_schedule.py`
(not the `ee/` file of the same name, which is empty of these entries) and are
only added to `beat_task_templates` when `ENTERPRISE_EDITION_ENABLED or
_LICENSE_ENFORCEMENT_ENABLED` (`beat_schedule.py`, the block starting `if
ENTERPRISE_EDITION_ENABLED or _LICENSE_ENFORCEMENT_ENABLED:`). Both are
`work_gated: True` and route through the `heavy` worker per `backend/AGENTS.md`.

### Per-source sync frequency (`ee/onyx/configs/app_configs.py`)

| Source | Doc sync | Group sync |
|---|---|---|
| Google Drive | `DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | `GOOGLE_DRIVE_PERMISSION_GROUP_SYNC_FREQUENCY` (5 min) |
| Confluence | `CONFLUENCE_PERMISSION_DOC_SYNC_FREQUENCY` (30 min) | `CONFLUENCE_PERMISSION_GROUP_SYNC_FREQUENCY` (30 min) |
| Jira | `JIRA_PERMISSION_DOC_SYNC_FREQUENCY` (30 min) | `JIRA_PERMISSION_GROUP_SYNC_FREQUENCY` (30 min) |
| Canvas | `CANVAS_PERMISSION_DOC_SYNC_FREQUENCY` (30 min) | `CANVAS_PERMISSION_GROUP_SYNC_FREQUENCY` (30 min) |
| Box | `BOX_PERMISSION_DOC_SYNC_FREQUENCY` (30 min) | `BOX_PERMISSION_GROUP_SYNC_FREQUENCY` (5 min) |
| GitHub | `GITHUB_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | `GITHUB_PERMISSION_GROUP_SYNC_FREQUENCY` (5 min) |
| Slack | `SLACK_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | no group sync (§4.5) |
| Teams | `TEAMS_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | `TEAMS_PERMISSION_GROUP_SYNC_FREQUENCY` (5 min) |
| Outlook | `OUTLOOK_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | no group sync |
| SharePoint | `SHAREPOINT_PERMISSION_DOC_SYNC_FREQUENCY` (30 min) | `SHAREPOINT_PERMISSION_GROUP_SYNC_FREQUENCY` (5 min) |
| Gmail | `DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY` (5 min) | no group sync |
| Zoom | `DEFAULT_PERMISSION_DOC_SYNC_FREQUENCY`, but `doc_sync_func=mock_doc_sync` (a no-op; see §4.3) | no group sync |
| Salesforce | none (`doc_sync_config=None`) | none; `censoring_config` only (§4.5) |

Every value is env-overridable and is additionally multiplied by
`OnyxRuntime.get_doc_permission_sync_multiplier()` in
`_is_external_doc_permissions_sync_due` (cloud-only backpressure knob).

---

## 3. Data model

```
ConnectorCredentialPair
  .access_type: PUBLIC | SYNC | PRIVATE
  .last_time_perm_sync, .last_time_external_group_sync

DocPermissionSyncAttempt                          onyx/db/models.py
  .connector_credential_pair_id, .status (PermissionSyncStatus),
  .total_docs_synced, .docs_with_permission_errors,
  .error_message, .full_exception_trace, .time_started/.time_finished

ExternalGroupPermissionSyncAttempt                onyx/db/models.py
  .connector_credential_pair_id (nullable: some sources sync groups once for
   every cc_pair of that source, see source_group_sync_is_cc_pair_agnostic),
  .status, .total_users_processed, .total_groups_processed,
  .total_group_memberships_synced, .errors_encountered

Document
  .external_user_emails: str[]
  .external_user_group_ids: str[]   # already namespaced, see §4.1
  .is_public: bool
  .last_modified: timestamp         # bumped only when perm-sync actually changes a value
  .last_synced: timestamp           # set by the separate index-write task, [[document-index]]

User__ExternalUserGroupId                          ee/onyx/db/models via external_perm.py
  .user_id, .external_user_group_id (namespaced string), .cc_pair_id, .stale: bool

PublicExternalUserGroup
  .external_user_group_id, .cc_pair_id, .stale: bool
  # a synced group marked "gives everyone access" (e.g. a Drive domain share)

ExternalUserGroup (pydantic, not a table)           ee/onyx/db/external_perm.py
  .id, .user_emails: list[str], .gives_anyone_access: bool
  # what a source's group_sync_func yields; upsert_external_groups writes it
  # into User__ExternalUserGroupId / PublicExternalUserGroup rows

ExternalAccess (frozen dataclass)                   onyx/access/models.py
  .external_user_emails, .external_user_group_ids, .is_public
  # what a source's doc_sync_func yields per document, wrapped as:

DocExternalAccess / NodeExternalAccess              onyx/access/models.py
  .doc_id / .raw_node_id, .external_access
  # union type ElementExternalAccess is what doc_sync generators actually yield
```

```
                 doc_sync_func yields ElementExternalAccess
                              |
                              v
              element_update_permissions (per element)
                    |                       |
                    v                       v
        upsert_document_external_perms   db_update_hierarchy_node_permissions
        (Document.external_* / is_public)   (HierarchyNode.*, see access-control §3)
                              |
                              v
              Document.last_modified bumped IF changed
                              |
                    (picked up later, see §4.3)
                              v
              document_index_metadata_sync_task
              recomputes get_access_for_document
              and writes the ACL into the index
```

```
              group_sync_func yields ExternalUserGroup
                              |
                              v
              upsert_external_groups (batch upsert,
              stale=False on every row touched this cycle)
                              |
                              v
        User__ExternalUserGroupId / PublicExternalUserGroup
                              |
              read by fetch_external_groups_for_user /
              fetch_public_external_group_ids (access-control §4.3)
```

---

## 4. How it works

### 4.1 The registry: `get_source_perm_sync_config`

`ee/onyx/external_permissions/sync_params.py:_SOURCE_TO_SYNC_CONFIG` is the one
place that says what a source supports. Each entry is a `SyncConfig` with up to
three independent, optional pieces:

- `doc_sync_config: DocSyncConfig | None`. If set: a `doc_sync_func`
  (`DocSyncFuncType`, `perm_sync_types.py`), a `doc_sync_frequency`, and
  `initial_index_should_sync` (whether the connector already fetches
  permissions inline during indexing, so doc sync must wait for the first
  successful index before it has anything meaningful to correct;
  `_is_external_doc_permissions_sync_due` gates on this).
- `group_sync_config: GroupSyncConfig | None`. If set: a `group_sync_func`
  (`GroupSyncFuncType`), a `group_sync_frequency`, and
  `group_sync_is_cc_pair_agnostic` (Confluence and Jira: one sync run at the
  source level, not per cc_pair, `sync_params.py:_SOURCE_TO_SYNC_CONFIG`
  entries for `CONFLUENCE`/`JIRA`).
- `censoring_config: CensoringConfig | None`. A `chunk_censoring_func`
  (`CensoringFuncType`). Salesforce is the only current user (§4.5); it has
  `censoring_config` set and `doc_sync_config=None`.

A source with none of the three is not in the dict at all;
`get_source_perm_sync_config` returns `None` and
`check_if_valid_sync_source`/`source_requires_doc_sync`/
`source_requires_external_group_sync` all report `False`.

`DocSyncFuncType`/`GroupSyncFuncType`/`CensoringFuncType` are `Protocol`/
`Callable` type aliases in `perm_sync_types.py`; every `_load_*` function in
`sync_params.py` lazily imports the real implementation on first call (`_lazy_doc_sync`,
`_lazy_group_sync`, `_lazy_censoring`), so importing `sync_params` does not pull
in every connector SDK.

### 4.2 Doc sync flow

```
beat: CHECK_FOR_DOC_PERMISSIONS_SYNC (every 30s)
  check_for_doc_permissions_sync                doc_permission_syncing/tasks.py
    get_all_auto_sync_cc_pairs                   ee/onyx/db/connector_credential_pair.py
    _is_external_doc_permissions_sync_due(cc_pair)  per cc_pair, per §2 frequency table
    try_creating_permissions_sync_task            fences via RedisConnectorPermissionSync,
                                                   inserts a SyncRecord, dispatches:
  CONNECTOR_PERMISSION_SYNC_GENERATOR_TASK
    connector_permission_sync_generator_task
      create_doc_permission_sync_attempt          onyx/db/permission_sync_attempt.py
      mark_doc_permission_sync_attempt_in_progress
      doc_sync_func(cc_pair, fetch_existing_docs_fn, fetch_existing_doc_ids_fn, callback)
        -> Generator[ElementExternalAccess]
      for each element:
        redis_connector.permissions.update_db
          -> element_update_permissions            doc_permission_syncing/tasks.py
             DocExternalAccess  -> upsert_document_external_perms      ee/onyx/db/document.py
             NodeExternalAccess -> db_update_hierarchy_node_permissions onyx/db/hierarchy.py
      complete_doc_permission_sync_attempt (SUCCESS or COMPLETED_WITH_ERRORS)
      on exception: _fail_doc_permission_sync_attempt, fence cleared, re-raised
```

Most doc-sync implementations funnel through
`ee/onyx/external_permissions/utils.py:generic_doc_sync`, which:

1. Streams the source's `SlimConnectorWithPermSync.retrieve_all_slim_docs_perm_sync`
   output (interface: `onyx/connectors/interfaces.py:SlimConnectorWithPermSync`).
2. Yields a `DocExternalAccess` per fetched document, or a `NodeExternalAccess`
   for a `HierarchyNode`.
3. Raises `RuntimeError` if a fetched document has no `external_access` set at
   all (`utils.py:generic_doc_sync`, `"No external access found for document ID"`):
   a connector bug here stops the whole sync rather than silently under-permissioning
   one document.
4. Diffs the fetched ID set against `fetch_all_existing_docs_ids_fn()`
   (`get_document_ids_for_connector_credential_pair`). Every existing document
   **not** seen in this fetch gets `DocExternalAccess(external_access=ExternalAccess.empty())`,
   i.e. `is_public=False` and both ID sets emptied: the source stopped
   reporting it, so Onyx makes it private. This is the fail-closed default for
   the "document disappeared or the user lost access" case.

Confluence, Jira, Canvas, Box, SharePoint, Teams, and Outlook doc_sync
(`ee/onyx/external_permissions/{confluence,jira,canvas,box,sharepoint,teams,outlook}/doc_sync.py`)
are thin wrappers around `generic_doc_sync`, differing only in which connector
class and `DocumentSource` they pass. Two sources have a genuinely different
shape:

- **Slack** (`ee/onyx/external_permissions/slack/doc_sync.py:slack_doc_sync`)
  does not use `generic_doc_sync` at all. Slack has no document-level ACL
  concept in the same sense; access is channel membership, resolved from
  `get_channel_access` and workspace user/email maps. There is no
  `group_sync_config` for Slack (`sync_params.py` comment: "All channel access
  is done at the individual user level").
- **Google Drive** (`ee/onyx/external_permissions/google_drive/doc_sync.py:gdrive_doc_sync`)
  is custom because a Drive file's ACL includes domain-wide and "anyone with
  link" grants. `_domain_group_for_permission` maps a domain-wide permission to
  `build_domain_group_id(domain)` (`onyx/access/utils.py`), placed into the
  document's `external_user_group_ids`, resolved later against the real domain
  roster by group sync (§4.4).

**Zoom and the mock connector are a documented no-op** (`sync_params.py:mock_doc_sync`):
permissions are set once, during indexing, and doc sync never revises them. A
missing or stale permission for these sources is an indexing bug, not a sync
bug; a change here needs the indexing pipeline, not this component.

### 4.3 From `Document` row to indexed ACL: the missing link, made explicit

**Doc sync writes to Postgres only.** `element_update_permissions` calls
`upsert_document_external_perms` (`ee/onyx/db/document.py`), which compares
the incoming `ExternalAccess` against the current `Document` row and, **only if
something actually changed**, updates the columns and bumps
`document.last_modified = datetime.now(timezone.utc)`
(`ee/onyx/db/document.py:upsert_document_external_perms`). Nothing in the doc
sync task pushes a value into the document index directly.

**The index write is a separate, generic mechanism**, owned by
[[document-index]] and [[indexing-pipeline]], that this component depends on
rather than implements:

```
beat: CHECK_FOR_VESPA_SYNC_TASK                    onyx/background/celery/tasks/vespa/tasks.py
  try_generate_stale_document_sync_tasks
    construct_document_id_select_by_needs_sync_or_secondary_pending   onyx/db/document.py
      predicate: Document.last_modified > Document.last_synced
              OR Document.last_synced IS NULL
    -> dispatches DOCUMENT_INDEX_METADATA_SYNC_TASK per stale document id
  document_index_metadata_sync_task
    get_access_for_document(document_id)           access-control's dispatch point
    MetadataUpdateRequest(access=doc_access, document_sets=..., ...)
    RetryDocumentIndex(document_index).update(...)  a metadata-only write, not
                                                     a full re-embed/re-chunk
    (on success) mark_document_as_synced             sets Document.last_synced
```

**Verified**: `upsert_document_external_perms` (`ee/onyx/db/document.py`) bumps
`last_modified` only on an actual diff; `construct_document_id_select_by_needs_sync_or_secondary_pending`
(`onyx/db/document.py`) is the query the vespa-sync beat task uses to find work;
`document_index_metadata_sync_task` (`onyx/background/celery/tasks/vespa/tasks.py`)
is the task that calls `get_access_for_document` and issues the index write. This
is a **metadata-only** update (chunk content, embeddings, and text are
untouched); it is not what "reindex" usually means for content changes, but it
is the mechanism that makes a permission-sync ACL change visible in search.
Until this task runs for a given document, that document's indexed ACL is
whatever the previous sync (or the initial index) wrote.

Group sync has no equivalent per-document trigger of its own: a group
membership change does not bump any `Document.last_modified`, because a
document's indexed ACL contains the *group id*, not the resolved member list
(`DocumentAccess.to_acl`, [[access-control]] §4.1). The membership change takes
effect at **read time**, the next time `fetch_external_groups_for_user` runs
for that user, with no index write needed. See §5.4 for why this makes group
sync safe to lag doc sync.

### 4.4 Group sync flow

```
beat: CHECK_FOR_EXTERNAL_GROUP_SYNC (every 20s)
  check_for_external_group_sync                  external_group_syncing/tasks.py
    get_all_auto_sync_cc_pairs
    _is_external_group_sync_due(cc_pair)           per cc_pair, per §2 frequency table
    try_creating_external_group_sync_task          fences, inserts SyncRecord, dispatches:
  CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK
    connector_external_group_sync_generator_task -> _perform_external_group_sync
      create_external_group_sync_attempt
      _timed_perform_external_group_sync:
        remove_stale_external_groups(cc_pair_id)     clears LAST cycle's leftovers, see §5.4
        mark_old_external_groups_as_stale(cc_pair_id) tags this cycle's starting rows stale=True,
                                                       commits immediately (idle-in-transaction
                                                       safety, ee/onyx/db/external_perm.py comment)
        mark_external_group_sync_attempt_in_progress
        group_sync_func(tenant_id, cc_pair) -> Generator[ExternalUserGroup]
        for each batch of 100:
          upsert_external_groups                     sets stale=False on every touched row
        remove_stale_external_groups(cc_pair_id)     removes rows nothing in THIS cycle re-confirmed
        complete_external_group_sync_attempt
        mark_all_relevant_cc_pairs_as_external_group_synced   group_sync_utils.py; widens to every
                                                               cc_pair of the source if
                                                               source_group_sync_is_cc_pair_agnostic
      on exception: mark_external_group_sync_attempt_failed, re-raised
                    (no final remove_stale_external_groups call: see §5.3/§5.4)
```

`upsert_external_groups` (`ee/onyx/db/external_perm.py`) does the namespacing:
for each `ExternalUserGroup`, it computes
`build_ext_group_name_for_onyx(ext_group_name=external_group.id, source=source)`
once, and reuses that value as `external_user_group_id` for every member row
(and, if `gives_anyone_access`, for the `PublicExternalUserGroup` row too). It
batch-adds any not-yet-known member emails via
`batch_add_ext_perm_user_if_not_exists` (`onyx/db/users.py`) before writing
group rows, so a user who has never logged into Onyx can still be granted
access via a synced group.

**Confluence/Jira group sync is source-scoped, not cc_pair-scoped**
(`source_group_sync_is_cc_pair_agnostic` returns `True` for these sources in
`sync_params.py`). `group_sync_utils.py:mark_all_relevant_cc_pairs_as_external_group_synced`
looks up every cc_pair for that source and marks all of them synced after one
successful run, and `permission_sync_attempt.py:get_relevant_external_group_sync_attempts_for_cc_pair`
widens its query to the whole source for these two, with a documented caveat:
two independent Confluence sites in the same deployment share one merged
attempt history.

**Google Drive is the concrete "domain group" case.**
`ee/onyx/external_permissions/google_drive/group_sync.py:gdrive_group_sync`
yields, among per-folder and per-Google-group entries, one
`ExternalUserGroup(id=build_domain_group_id(google_drive_connector.google_domain), ...)`
populated with the real Workspace roster for that domain. Doc sync
independently emits `build_domain_group_id(permission.domain)` as a raw group
id on any document with a domain-wide share
(`google_drive/doc_sync.py:_domain_group_for_permission`). Both are raw,
unprefixed ids; `build_ext_group_name_for_onyx` is applied identically to both
by `upsert_external_groups` (group write path) and by
`upsert_document_external_perms` (doc write path, which prefixes every id in
`external_access.external_user_group_ids` the same way). This symmetry is what
makes a domain-wide share resolvable at read time; see §5.2 and §9.

### 4.5 Salesforce: censoring instead of doc sync

Salesforce has `doc_sync_config=None` and `censoring_config` set
(`sync_params.py:_SOURCE_TO_SYNC_CONFIG[DocumentSource.SALESFORCE]`). Per
[[access-control]] §4.5, this makes every Salesforce document pass the ACL
filter for everyone (`ee/onyx/access/access.py:_get_access_for_documents`,
`is_only_censored` branch), and access is narrowed **after** retrieval instead:
`ee/onyx/external_permissions/salesforce/postprocessing.py:censor_salesforce_chunks`
is invoked per user, per chunk, by
`ee/onyx/external_permissions/post_query_censoring.py:_post_query_chunk_censoring`,
itself reached from `context/search/pipeline.py` via
`fetch_ee_implementation_or_noop`. There is no group sync for Salesforce.

This means Salesforce has **no doc-sync `PermissionSyncAttempt` history at
all** for admins to inspect; "is Salesforce permission sync working" is a
question about `censor_salesforce_chunks` behaving correctly per query, not
about a background job's status.

---

## 5. Contracts and invariants

This is the write side of the same trust boundary [[access-control]] enforces
on read. A silent bug here does not throw; it shows (or hides) the wrong
document to the wrong person.

1. **A doc sync generator must account for every document it used to know
   about, or "disappeared" documents keep their old ACL forever.**
   `generic_doc_sync` (`utils.py`) does this by diffing against
   `fetch_all_existing_docs_ids_fn()` and emitting `ExternalAccess.empty()`
   for anything missing, which is a fail-closed default (§4.2, point 4). A new
   source's doc_sync that does **not** route through `generic_doc_sync` (Slack
   is the current exception) must implement an equivalent "document vanished
   means private" rule itself, or a deleted/unshared source document stays
   visible in Onyx indefinitely. **Unverified**: whether `slack_doc_sync`
   implements an equivalent revocation path for a channel a user was removed
   from; it was not read in full for this document. Check
   `ee/onyx/external_permissions/slack/doc_sync.py` before relying on this for
   Slack.
2. **The write-side namespacing (`upsert_document_external_perms`,
   `upsert_external_groups`) and the read-side namespacing
   (`_get_acl_for_user`'s `prefix_external_group`) must both go through
   `build_ext_group_name_for_onyx`, with the same `(raw_id, source)` pair.**
   Both call sites apply it: `ee/onyx/db/document.py:upsert_document_external_perms`
   for the document's `external_user_group_ids`, and
   `ee/onyx/db/external_perm.py:upsert_external_groups` for
   `User__ExternalUserGroupId.external_user_group_id`. Since
   `build_ext_group_name_for_onyx` also **lowercases** its output
   (`onyx/access/utils.py`, "NOTE: the name is lowercased to handle case
   sensitivity"), any code path that stores or compares a group id **without**
   calling this function breaks the match silently: the ACL entry and the
   membership row diverge only in case, `set` equality fails, and the user
   loses access to a document they should see. This fails closed (an
   availability bug), which is the safer direction, but it is still silent.
   A new source's doc_sync or group_sync must call `build_ext_group_name_for_onyx`
   at both id-producing sites, never construct the prefixed id by hand.
3. **A failed doc sync attempt does not roll back what it already wrote.**
   `element_update_permissions` commits per-document
   (`upsert_document_external_perms` calls `db_session.commit()` directly on
   the changed-value branch). If the generator raises partway through
   (`connector_permission_sync_generator_task`'s `except` block), documents
   already processed keep their new (correct, freshly-fetched) ACL; documents
   not yet reached keep their old ACL and are picked up on the next scheduled
   attempt. This is safe **only** because no doc sync clears an ACL
   speculatively before confirming the new one: a partial sync never leaves a
   document in a wider state than before the sync started, only a
   possibly-stale one. Do not add a step that clears or widens a document's
   access before the fetch confirming the replacement value succeeds.
4. **A failed or partial group sync leaves last-cycle's memberships in place,
   including ones that should have been revoked.** `fetch_external_groups_for_user`
   and `fetch_external_groups_for_user_email_and_group_ids`
   (`ee/onyx/db/external_perm.py`) select from `User__ExternalUserGroupId`
   **without filtering on `stale`**. `stale` is a bookkeeping flag consumed
   only by `remove_stale_external_groups`, called at the **start** of the next
   cycle (`_timed_perform_external_group_sync`, "Clean up stale rows from
   previous cycle BEFORE marking new ones") and again at the **end** of a
   successful cycle. If a cycle throws (`except Exception` block,
   `external_group_syncing/tasks.py:_timed_perform_external_group_sync`), the
   end-of-cycle `remove_stale_external_groups` call is skipped and the
   exception re-raises; rows marked stale this cycle (i.e. every row from the
   *previous* successful cycle that this cycle's fetch has not yet
   re-confirmed) remain queryable and still grant access until the next
   attempt succeeds. **A user removed from a source group keeps that group's
   access in Onyx until a group sync attempt completes successfully**, not
   just runs. This is a real fail-open window, bounded by the sync frequency
   table in §2 plus however many consecutive attempts fail. Treat a string of
   `FAILED` `ExternalGroupPermissionSyncAttempt` rows for a cc_pair as a
   security-relevant alert, not just an operational one.
5. **CE has no permission sync at all; the CE fallback for the dispatch points
   this component feeds is "no group ever resolves; only manually-shared
   access applies".** There is no dispatched function in this component
   itself analogous to `_get_acl_for_user`/`_get_access_for_documents`; those
   live in [[access-control]] and already degrade correctly
   (`ee.onyx.access.access._get_access_for_documents` reads
   `Document.external_user_emails`/`external_user_group_ids`/`is_public`,
   which are EE-only-populated columns; the CE `_get_access_for_documents`
   never reads them). A CE deployment simply never gets these columns
   populated, so it narrows rather than widens by construction. See
   [[access-control]] §5.9 for the general dispatch-safety contract this
   depends on.
6. **A source with `doc_sync_config=None` and no `censoring_config` either
   must not be marked `AccessType.SYNC`.** `_is_external_doc_permissions_sync_due`
   logs an error and returns `False` for such a cc_pair
   (`"No sync config found for %s"` / `"No doc sync config found for %s"`), so
   the connector silently never gets a permission sync attempt, ever, while
   `connector_permission_sync_generator_task` treats it as a hard failure if
   dispatched anyway (`"No doc sync func found for ... with cc_pair="`,
   raises). **Unverified**: whether the connector-creation UI/API actually
   prevents selecting `SYNC` for a source with no doc-sync capability, or
   whether this is caught only here at sync time. Check
   `backend/onyx/server/documents/` connector-creation validation before
   assuming the UI blocks this.
7. **`MAX_NUM_ENTRIES` (5000, `ExternalAccess.MAX_NUM_ENTRIES`) is enforced only
   at consumption time, not by the connector.** `RedisConnectorPermissionSync.update_db`
   skips (does not apply, counts as an error) any element whose combined
   user+group entry count exceeds this, logging a warning
   (`onyx/redis/redis_connector_doc_perm_sync.py`). A document with a
   pathologically large ACL keeps its **previous** synced state rather than
   silently truncating to a wrong-but-smaller set. This is fail-static, not
   fail-closed or fail-open; treat repeated skips (visible via
   `docs_with_permission_errors` on the attempt) as a real gap, not noise.

---

## 6. Relationships

**Depends on**
- [[connectors]]: `SlimConnectorWithPermSync.retrieve_all_slim_docs_perm_sync`
  and `CheckpointedConnectorWithPermSync` (`onyx/connectors/interfaces.py`) are
  the connector-side contracts doc sync fetches through; a connector that adds
  perm-sync support implements one of these.
- [[cc-pairs-and-credentials]]: `ConnectorCredentialPair.access_type == SYNC`
  is what makes a cc_pair eligible at all; `last_time_perm_sync`/
  `last_time_external_group_sync` live on that model.
- [[background-jobs]]: the Celery beat/fence/lock machinery
  (`RedisConnectorPermissionSync`, `RedisConnectorExternalGroupSync`,
  `SyncRecord`) this component's tasks are built on.
- [[editions-and-gating]]: `ENTERPRISE_EDITION_ENABLED` /
  `_LICENSE_ENFORCEMENT_ENABLED` gate both beat entries
  (`onyx/background/celery/tasks/beat_schedule.py`).

**Depended on by**
- [[access-control]]: reads `Document.external_user_emails`/
  `external_user_group_ids`/`is_public` (write path,
  `ee.onyx.access.access._get_access_for_documents`) and
  `User__ExternalUserGroupId`/`PublicExternalUserGroup` (read path,
  `fetch_external_groups_for_user`/`fetch_public_external_group_ids`) that
  this component alone populates. Every claim in access-control.md's §4.2 and
  §4.3 about where synced data comes from resolves here.
- [[document-index]] / [[indexing-pipeline]]: the `needs_sync` /
  `document_index_metadata_sync_task` machinery this component relies on to
  turn a Postgres ACL change into an indexed one (§4.3) is owned there, not
  here; a bug in that machinery makes a correct permission-sync write
  invisible.
- [[auth-and-identity]]: `batch_add_ext_perm_user_if_not_exists`
  (`onyx/db/users.py`) can create a `User` row for someone who has never
  logged into Onyx, purely because a sync mentioned their email.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a source's perm sync | register it in `sync_params.py`'s `_SOURCE_TO_SYNC_CONFIG`; decide `initial_index_should_sync` correctly (§4.1) or the first sync races the first index; if it uses groups, get the namespacing right (§5.2) from the first commit, not as a follow-up |
| changes an ACL prefix or the namespacing (`build_ext_group_name_for_onyx`, `prefix_external_group`) | [[access-control]] §7's reindex requirement applies; additionally, every write site here (`upsert_document_external_perms`, `upsert_external_groups`) must change in the same PR as the read side, and a full doc + group re-sync is needed, not just a reindex, since the raw Postgres rows are wrong, not just the derived index ACL |
| changes the sync schedule (frequencies in `ee/onyx/configs/app_configs.py`, or the beat interval in `beat_schedule.py`) | the eventual-consistency window in §9 widens or narrows; re-run the two-user propagation test in §8 with the new interval to confirm it still completes in a reasonable multiple of the schedule |
| changes `DocumentAccess` (fields, `to_acl`) | [[access-control]] §7 covers the read side; on the write side, confirm `upsert_document_external_perms` and every `doc_sync_func` still populate exactly the fields `DocumentAccess.build`/`ee.onyx.access.access._get_access_for_documents` expect |
| changes group resolution (`fetch_user_groups_for_user`, `fetch_external_groups_for_user`, `remove_stale_external_groups`, `mark_old_external_groups_as_stale`) | re-run the revocation half of the two-user test (§8); a change to the stale-marking order can reopen or widen the fail-open window in §5.4 |
| touches `element_update_permissions` or `upsert_document_external_perms`'s change-detection | confirm `Document.last_modified` still only bumps on a real diff; bumping it unconditionally does not break correctness but defeats the point of `needs_sync` filtering and can make every synced document look permanently stale to [[document-index]]'s beat task |
| adds a new `doc_sync_func` that does not use `generic_doc_sync` | re-implement the "document vanished means private" rule (§5, point 1) explicitly; do not assume it comes for free |

---

## 8. How to verify a change

### Tests

```bash
# External dependency unit: exercises real Postgres/Redis with connector SDKs
# mocked at the network boundary. The confluence group sync test is the
# canonical example referenced in backend/AGENTS.md.
cd backend && uv run --env-file .vscode/.env pytest tests/external_dependency_unit/permission_sync
cd backend && uv run --env-file .vscode/.env pytest tests/external_dependency_unit/connectors/confluence/test_confluence_group_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/external_dependency_unit/connectors/google_drive/test_google_drive_group_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/external_dependency_unit/connectors/jira/test_jira_group_sync.py

# Integration: full sync attempt against a live connector job test environment
cd backend && uv run --env-file .vscode/.env pytest tests/integration/connector_job_tests/google/test_google_drive_permission_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/integration/connector_job_tests/slack/test_permission_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/integration/connector_job_tests/github/test_github_permission_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/integration/connector_job_tests/jira/test_jira_permission_sync_full.py
cd backend && uv run --env-file .vscode/.env pytest tests/integration/tests/indexing/test_initial_permission_sync.py
cd backend && uv run --env-file .vscode/.env pytest tests/integration/tests/usergroup/test_usergroup_syncing.py

# Unit: attempt-record bookkeeping, redis fencing, per-source group-sync logic
cd backend && uv run pytest tests/unit/onyx/redis/test_connector_permission_sync.py
cd backend && uv run pytest tests/unit/ee/onyx/external_permissions
cd backend && uv run pytest tests/unit/ee/onyx/connectors/test_perm_sync_valid.py
```

`test_perm_sync_no_pg_conn_during_crawl.py`
(`tests/external_dependency_unit/permission_sync/`) specifically covers the
idle-in-transaction concern noted in `mark_old_external_groups_as_stale`'s
inline comment (§4.4); re-run it if you touch transaction boundaries in either
generator task.

See `backend/AGENTS.md` for authoritative commands and required secrets/env
(connector credentials resolve through `backend/tests/utils/aws_secrets.py`
per the root `CLAUDE.md`).

### Manual reproduction: two-user, two-permission propagation test

This is the load-bearing check for this component, distinct from
[[access-control]]'s two-user test: that one proves enforcement works for a
fixed ACL; this one proves **sync correctly changes** the ACL over time.

1. Confirm services are up: `tail -f backend/log/api_server_debug.log` and the
   `heavy` worker's log (permission sync tasks route there per
   `backend/AGENTS.md`).
2. Connect a source that supports doc sync (Google Drive is the most complete
   example) as `AccessType.SYNC`, using real source-side sharing you control.
3. At the source, share one document with User A only. Wait for a doc
   permission sync attempt to complete (poll
   `get_latest_doc_permission_sync_attempt_for_cc_pair` or the admin UI; do not
   assume it already ran).
4. As User A (`admin_user@example.com` / `TestPassword123!`, or a second
   registered user), confirm the document is visible in chat and
   `/api/search` (called via the frontend per this repo's `CLAUDE.md`).
5. As User B, a different Onyx user with no source-side access, confirm the
   document is **not** visible through the same surfaces.
6. **Now change the permission at the source**: share the document with User B
   as well (or, for the revocation direction, remove User A's access).
7. Force or wait for the next doc permission sync attempt. Separately, confirm
   [[document-index]]'s metadata sync has also run (`document.last_synced`
   should move past the new `last_modified`; there is no dedicated UI for
   this, check via the database or logs).
8. Re-check both users through chat and `/api/search`. The visibility split
   must now match the **new** source-side permission, not the one from step 3.
9. If the source and sync support groups, repeat steps 3-8 with a group
   membership change instead of a direct share: add/remove a user from a
   source group, wait for a **successful** (not just attempted) external
   group sync attempt, and confirm the propagation. Deliberately induce one
   failed attempt first (for example, revoke the connector credential
   mid-cycle) and confirm the previous membership is still honored until a
   subsequent attempt succeeds, per §5.4.

### What "working" looks like

- A document's visibility in chat/search matches the source system's current
  permission, not a permanently stale snapshot, within one sync-plus-index-write
  cycle.
- A `DocPermissionSyncAttempt`/`ExternalGroupPermissionSyncAttempt` history
  shows `SUCCESS` or `COMPLETED_WITH_ERRORS` for steady-state operation;
  a persistent run of `FAILED` attempts for a cc_pair means that cc_pair's
  access is frozen at whatever it last successfully synced, per §5.3/§5.4,
  not automatically corrected by later successful indexing.
- Revoking a source-side group membership removes a document from that user's
  results only after a group sync attempt **succeeds**, never mid-failure.

---

## 9. Footguns

- **Lowercasing.** `build_ext_group_name_for_onyx` lowercases the final id.
  Anything that constructs or compares a namespaced external group id without
  calling this function (a debugging script, a new connector's inline logic, a
  manual DB query) will not match, and the mismatch fails closed (invisible,
  not leaked) but is easy to misdiagnose as "the sync isn't running" when it
  actually ran and wrote a differently-cased string.
- **Per-source namespacing is mandatory, not cosmetic.** Two sources
  legitimately producing the same raw group name (`"Engineering"` in both
  Confluence and Jira) would collide into one ACL entry without the
  `source.value` prefix `build_ext_group_name_for_onyx` adds. Never store or
  compare a raw, unprefixed group id anywhere in this component.
- **A permission-sync write to Postgres is not a permission-sync write to the
  index.** §4.3 is the single most important flow to internalize: doc sync
  changes `Document` columns and bumps `last_modified`; a separate,
  differently-scheduled beat task in [[document-index]] notices the staleness
  and performs a metadata-only index write. A code review that only checks
  "does `upsert_document_external_perms` get called with the right value" has
  not verified the user-visible effect.
- **Sync is eventually consistent by design, on two independent clocks.** Doc
  sync frequency and group sync frequency differ per source (§2) and are
  unrelated to the index metadata-sync beat interval. A document's *group id*
  can update quickly while the *group's membership* update is still pending, or
  vice versa; do not assume both halves of a group-based grant land atomically.
- **A failed group sync is a security-relevant silence, not just an
  operational one (§5.4).** `stale` rows are not excluded from
  `fetch_external_groups_for_user`; they are only cleaned up by a
  **subsequent successful** cycle. Do not read "the last attempt failed" as
  "access is currently correct but sync is behind"; it specifically means "a
  revocation that should have happened may not have happened yet."
- **This entire component is EE-only.** A CE deployment has no doc sync, no
  group sync, and no `PermissionSyncAttempt` rows ever created; `AccessType.SYNC`
  exists as an enum value but nothing populates the columns it implies are
  kept fresh. Do not test a permission-sync fix only in a CE dev environment
  and conclude it works; see [[access-control]]'s footgun about CE/EE
  divergence, which applies here even more directly since the feature does
  not exist at all in CE.
- **Salesforce has no doc-sync attempt history to check (§4.5).** If a
  Salesforce access bug is reported, do not look for a failed
  `DocPermissionSyncAttempt`; there will never be one. Look at
  `censor_salesforce_chunks` and `_post_query_chunk_censoring` instead.
