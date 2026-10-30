# Access Control

> Who can retrieve which document. Indexing stores an access control list (ACL)
> on every chunk, and every query passes through one filter built from the
> acting user's ACL.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE builds ACLs from user emails and public flags. EE adds Onyx
user groups, synced external groups and permissions, per-connector group
access, hierarchy filtering and post-query censoring.

---

## User experience

- **An end user** never manages access. In chat, search, document previews and
  citations, they see only documents that their source-system account can see,
  documents shared with their Onyx groups, and documents marked public. A
  missing document looks the same as a document that does not exist. No
  message says "you cannot see this".
- **An anonymous visitor** sees public documents only.
- **An admin** controls visibility through connector access types (public,
  private to groups, or synced from the source), user groups, and document
  sets. A document set narrows what an agent searches. It never grants access
  to a document the user could not already see.
- **A user who asks for a document set they cannot access** gets a 403
  `INSUFFICIENT_PERMISSIONS`, not an empty answer.
- **When a permission changes in the source system,** Onyx reflects it after
  the next permission sync and index metadata update. Until then the user can
  see the old access. A change to a user's Onyx group membership applies on
  the next query.
- **A self-hosted admin** can switch query-time connector filtering between
  off, shadow and enforce on the Index Settings page. On cloud, operators
  control this.

---

## Scope

This component owns the ACL model and its string format, the write path that
computes a document's `DocumentAccess` for indexing, the read path that builds
a user's ACL and cc-pair access sets, the ACL half of the index filter, the
post-query censoring hook, and user groups and document sets as access
objects.

Neighbours own:
- [[permission-sync]]: the jobs that fill `Document.external_user_emails`,
  `external_user_group_ids`, `is_public` and the external group tables.
- [[document-index]]: the OpenSearch schema, the rest of `_get_search_filters`,
  and the metadata sync that rewrites a chunk's stored ACL.
- [[auth-and-identity]]: the acting `User`.
- [[authorization]]: who may administer groups, connectors and document sets.
- [[cc-pairs-and-creds]]: the access level (READ, OPERATE, EDIT) that each
  cc-pair route needs.
- [[multi-tenancy]]: the tenant clause in the same filter.
- [[billing]]: what the Community downgrade does to groups and connector access.
- [[editions-and-gating]]: the CE fallbacks on a build without EE code, such
  as the hierarchy access fallback ([[editions-and-gating#noop-not-only-security-control]]).
- [[federated-search]]: the Slack lane, which uses the user's Slack token instead
  of an ACL.

---

## Architecture

**ACL strings.** `access/utils.py` prefixes every entry: `user_email:`,
`group:` (the Onyx group name) and `external_group:`. `DocumentAccess.to_acl()`
adds the unprefixed `PUBLIC_DOC_PAT` (`"PUBLIC"`). The OpenSearch index removes
it from the stored list and writes the separate public boolean field instead.

**Write path.**

```
indexing -> access/access.py:get_access_for_documents
  -> fetch_versioned_implementation("_get_access_for_documents")
     CE: db/document.py:get_access_info_for_documents
         user emails = credential owners of the document's non-synced cc-pairs
         is_public   = any live cc-pair of the document is PUBLIC
     EE: the CE result, plus
         group names from the data-access groups of the document's PRIVATE
         cc-pairs (synced pairs give no groups)
         external emails and groups from the Document row, only when a live
         cc-pair of the document is perm-synced
         is_public widened, again only for a perm-synced document, when the
         source says public, the source is censoring-only, or an external
         group is marked public
  -> DocumentAccess.to_acl() -> ACL list field + public field on each chunk
```

The stored ACL is a snapshot. The metadata sync in [[document-index]] rewrites
it when a document is marked for sync.

**Read path.**

```
build_access_filters_for_user(user, db_session)
  get_acl_for_user -> CE: {user_email:<email>, user_email:<prior emails>, PUBLIC}
                      EE: CE + group:<name> + external_group:<id>
                      anonymous: {PUBLIC} in both editions
  cc-pair access sets and the access mode
-> IndexFilters.access_control_list, IndexFilters.cc_pair_access
-> document_index/opensearch/search.py:DocumentQuery._get_search_filters
     public OR acl-match   (or the cc-pair filter in ENFORCE mode)
     AND tenant, document set, hierarchy, source, time ... clauses
-> access/access.py:censor_chunks_for_user   (EE censoring; CE no-op)
```

`user.prior_emails` keeps old addresses in the ACL, because indexed ACLs name
the old address until the source re-syncs.

**Query-time cc-pair filter.** A second filter works from the cc-pairs a chunk
belongs to, not the ACL snapshot. `context/search/models.py:CCPairAccessFilter`
holds three sets of pairs for the user. A chunk in an open pair is visible. A
chunk in an ACL pair is visible when it is public or matches the user's
`user_email:` or `external_group:` entries. Group access comes from open pairs,
so this filter carries no `group:` entries. Hidden pairs grant nothing. Chunks
with no cc-pair, such as user files, fall back to the ACL filter.
`access/cc_pair_access.py:get_cc_pair_access_mode` picks the mode from two
`OnyxRuntime` flags:

- off: only the guard that hides restricted pairs runs;
- `SHADOW`: results use the ACL filter, and the cc-pair filter is compared and
  logged;
- `ENFORCE`: the cc-pair filter replaces the ACL clause. It needs the enforce
  flag and a complete `cc_pair_ids` backfill
  (`document_index/opensearch/cc_pair_ids_backfill.py:is_cc_pair_ids_backfill_complete`).

`server/manage/search_settings.py:update_cc_pair_access_mode` refuses `ENFORCE`
before the backfill ends, and refuses every change on multi-tenant
deployments, because all tenants share the flags.

**Hidden pairs.** A `SYNC_RESTRICTED` pair grants nothing to a user outside its
data-access groups. A pair that moves from `PUBLIC` or `PRIVATE` to a synced type
gets `perm_sync_pending_since` when its source needs a doc sync
(`db/connector_edit_requests.py:apply_access_change__no_commit`), because its
chunks still carry the old access, such as public. Both are hidden in every
mode unless another pair of the same chunk grants access. The doc permission
sync beat clears the mark when the syncs have caught up
(`ee/onyx/background/celery/tasks/doc_permission_syncing/tasks.py:clear_caught_up_perm_sync_pending_marks`).
`connectors/pairing_access.py:validate_pairing_access` refuses
`SYNC_RESTRICTED` while `allow_connector_group_restrictions` is off, or before
the backfill.

**EE censoring.** A censoring-only source, such as Salesforce, has a
censoring function and no doc permission sync. It checks access at query time,
so its perm-synced documents are indexed as public. After retrieval,
`ee/onyx/external_permissions/post_query_censoring.py:_post_query_chunk_censoring`
sends a chunk to the censoring function, with the user's email, when no
`PUBLIC` pair holds its document and a perm-synced pair does, or no pair is
left. When the source sets `censors_private_connectors`, as Salesforce does,
documents under only private pairs are censored too, because older indexes
hold an open ACL for them. A chunk missing from the output is dropped. If
the function raises, every chunk of that source is dropped. Anonymous users get
none of them.

**Hierarchy browsing** (`server/features/hierarchy/`) uses a database check,
not the index filter. The CE implementation in `db/hierarchy.py` returns every
non-stub node of the source. EE (`ee/onyx/db/hierarchy.py`) filters nodes by
their own ACL columns or the user's connector access.

---

## Contracts and traps

1. `one-acl-filter-point` **`_get_search_filters` is the only place an index
   query gets its ACL clause, and the ACL comes from the authenticated `User`
   only.** `_get_acl_visibility_filter`, `_get_cc_pair_access_visibility_filter`
   and `_get_restricted_cc_pair_guard` are called only there
   (`document_index/opensearch/search.py:DocumentQuery._get_search_filters`). A retrieval that
   builds its own OpenSearch query bypasses access control. No request field
   may name whose ACL to use.
2. `none-acl-means-unrestricted` **`access_control_list=None` means no
   restriction, not public only.** Each call site must justify why access was
   already enforced: adjacent-chunk and by-ID expansion of documents the user
   just retrieved, the Slack lane, deletes, and a background re-chunk that
   reads for no user. Find them with `git grep -n "access_control_list=None"`.
   A new one needs a security review.
3. `acl-format-read-write-agree` **Read and write must agree on the ACL
   format.** `access/utils.py`, `onyx/access/access.py:_get_acl_for_user`,
   `ee/onyx/access/access.py:_get_acl_for_user` and the two
   `_get_access_for_documents` in the same files must change together. A change to
   a prefix or to the public split needs a full reindex. A mismatch usually
   hides documents, but two formats that overlap can expose them.
4. `write-side-snapshot-lag` **Write-side fixes do not reach indexed chunks.**
   `_get_acl_for_user` runs on every query, so read-side changes apply at once.
   `onyx/access/access.py:_get_access_for_documents` output is stored on chunks. A write-side fix
   leaks or hides documents until a metadata sync or reindex rewrites them.
5. `group-acl-uses-name` **Group ACL entries use the group name.**
   `ee/onyx/db/user_group.py:rename_user_group` marks the group's documents and
   its data-access pairs for re-sync. While a group syncs, edits to it fail
   with `RESOURCE_SYNCING`. A new path that changes a group name must do the
   same.
6. `new-acl-source-rules` **A new ACL source must prefix its entries and skip
   anonymous users.** `PUBLIC` is the one unprefixed entry, so a prefix keeps a
   value from equalling `PUBLIC` or another kind of entry. Both editions return
   only `PUBLIC` for `user.is_anonymous`, and the EE group lookups skip
   anonymous users.
7. `ce-fallback-narrows` **CE fallbacks narrow access, except for hierarchy.**
   If EE code is missing, the CE ACL functions return fewer entries. The CE
   hierarchy functions return every non-stub node, because the connectors that
   Community supports are public; private and synced pairs are paid features
   (`onyx/db/hierarchy.py:_get_accessible_hierarchy_nodes_for_source`). A new dispatched access
   function must return the more restrictive answer in CE
   ([[editions-and-gating]]).
8. `document-set-names-checked` **Document set names from a caller are checked
   on the server.** `onyx/db/document_set.py:filter_document_set_names_by_user_access`
   runs in `SearchTool.run`, in `context/search/pipeline.py` and in
   `chat/process_message.py`. All raise `INSUFFICIENT_PERMISSIONS` and skip
   anonymous users. Keep each check, and do not turn a refusal into an empty
   filter. Trap: `onyx/db/document_set.py:_add_user_filters` counts ownership only
   in edit mode. The creator of a private set with no groups can edit it, but
   chat and search do not return it unless they hold `READ_DOCUMENT_SETS`.
9. `censor-every-chunk-reader` **Every path that returns chunk content must
   call `onyx/access/access.py:censor_chunks_for_user`.** Censoring-only documents are public in the
   index. Callers are the search pipeline, the document chunk-info and
   size-info routes (`server/documents/document.py`), and the Open URL tool. A
   new reader of indexed chunk text that skips it leaks Salesforce fields in
   EE.
10. `acl-clause-size-limit` **The ACL clause is a separate `bool` clause** so
    OpenSearch can cache it apart from the other filters (see the
    `_get_acl_visibility_filter` docstring). An ACL above
    `document_index/opensearch/search.py:MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY`
    entries raises.
11. `manager-scope-not-doc-access` **Manage access is not document access.**
    A group's manage rows on a pair (role Editor or Operator) and a group
    manager's scope decide who administers the pair ([[authorization]]). Only the
    data-access groups of a `PRIVATE` pair enter its documents' `group:` ACL
    (`ee/onyx/db/user_group.py:fetch_user_groups_for_documents`). For that
    reason a manage-row change needs no document sync, and a data-access change
    does. A manager is a member of their group, so they read what its
    data-access grants give, nothing more.
12. `non-synced-private-to-owner` **A non-synced document with no explicit
    sharing is private to the credential owner.**
    `onyx/db/document.py:get_access_info_for_documents` adds only the owner's email. Other users
    need public access, a group, or a sync.
13. `no-default-group-shares` **Do not share a resource with a default group
    (Basic or Admin).** `onyx/db/user_group.py:assert_not_shared_with_default_group`
    refuses it, because Basic holds every user and Admin every admin. Use the
    resource's public flag.

---

## Decisions

- **One filter point.** Every query path shares `_get_search_filters`, so a
  fix there covers chat, search, the API and the Open URL tool together.
- **Store the ACL on chunks.** The index filters without a lookup in Postgres.
  The cost is the snapshot lag in [[#write-side-snapshot-lag]]. The cc-pair
  filter reads connector-level access at query time, so a change to a pair's
  groups does not wait for every chunk to be rewritten.
- **Fail closed in censoring.** A censoring error drops chunks rather than
  showing fields the user may not see.

---

## Known issues

- **CE tests do not cover EE ACLs.** A change verified only in the default CE
  dev setup has not tested group and external-group entries.
- **Admin search does not censor.**
  `onyx/server/query_and_chat/query_backend.py:admin_search` builds the admin's ACL
  filter but returns chunk blurbs without `censor_chunks_for_user`
  ([[#censor-every-chunk-reader]]). It needs full admin. The code does not say
  whether censoring-only sources should apply to admins.
- **The Slack federated lane has no ACL.** It is safe only while each search
  uses that user's own Slack token ([[federated-search]]). A new federated
  source needs its own reason, not a copy of that exception.

---

## Dependencies

- [[permission-sync]]: external emails, groups and public flags on documents.
- [[auth-and-identity]]: the acting `User`.
- [[editions-and-gating]]: `fetch_versioned_implementation` and
  `fetch_ee_implementation_or_noop` choose CE or EE code.
- [[document-index]]: stores the ACL fields and runs the filter.

---

## Recipes

- `new-search-entry-point` **Add a search entry point.** Copy the Open URL tool
  (`tools/tool_implementations/open_url/open_url_tool.py`): call
  `build_access_filters_for_user`, pass both results into `IndexFilters`, query
  through the document index, and run `censor_chunks_for_user` on the chunks.
  List the current readers with `git grep -n censor_chunks_for_user`.
- `new-acl-source` **Add an ACL source.** Copy `external_group:`: `prefix_external_group` in
  `access/utils.py`, its field on `DocumentAccess` (`access/models.py`), the
  write side in both `_get_access_for_documents` and the read side in both
  `_get_acl_for_user`. Follow [[#new-acl-source-rules]] and plan a reindex.
- `group-shareable-resource` **Add a resource that can be shared with a group.** Copy an entry of
  `ee/onyx/db/community_downgrade.py:_UNCASCADED_GROUP_LINKS`, such as
  `DocumentSet__UserGroup`. List the link tables there when a group delete
  does not cascade to yours, or the delete fails on the foreign key.
  `_make_group_shared_resources_public__no_commit` must make the resource
  public on downgrade, or it stays private with no groups ([[billing]]). Its
  manager rules go in [[authorization#scoped-manager-rights]].
- `investigate-acl-mismatch` **Investigate "a user sees a document they should not", or the reverse.**
  Compare the user's ACL with the document's stored access:
  `backend/tests/integration/common_utils/document_acl.py:get_user_acl` and
  `get_user_document_access_via_acl` do this without relying on search
  ranking. `get_user_acl` rebuilds only the `user_email:`, `external_group:`
  and `PUBLIC` entries; add `group:` entries and prior emails by hand for an
  EE group case. If the `Document` row is right but chunks are wrong, the metadata
  sync has not run ([[#write-side-snapshot-lag]]). If the access mode is
  `SHADOW`, the API server log shows the disagreements from
  `document_index/opensearch/opensearch_document_index.py`. On EE, check
  whether the source is censoring-only.

---

## Verification

- Integration suites under `backend/tests/integration/tests/`:
  `permissions_access/`, `permissions_membership/`, `permissions_resources/`
  and `usergroup/`. The helper
  `backend/tests/integration/common_utils/document_acl.py` checks a user's ACL
  without relying on search ranking.
- The two-user test: index a document that only user A can see. As user B,
  confirm it is absent from chat citations, `/api/search` and every other entry
  point your change touches. As user A, confirm it is present. Run it on an EE
  build when groups are involved.
