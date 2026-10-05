# Access Control

> Who can see which document. An access control list (ACL) is attached to every
> indexed chunk at write time, compiled from the acting user at read time, and
> checked at exactly one point before any chunk leaves the index.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** access-control
**Edition:** CE for the ACL data model, individual and public access, and the single
compile-time chokepoint. EE for group-derived ACL entries, curator scoping, and
per-field post-query censoring.
**Owns:**
`backend/onyx/access/access.py`, `models.py`, `utils.py`, `hierarchy_access.py`,
`backend/ee/onyx/access/access.py`, `hierarchy_access.py`,
`backend/onyx/db/document_access.py`, `permissions.py`, `scoped_permissions.py`,
`backend/onyx/db/document_set.py`, `user_group.py`, `hierarchy.py`,
`backend/onyx/server/features/document_set/`, `backend/onyx/server/features/hierarchy/`,
`backend/ee/onyx/server/user_group/`, `backend/ee/onyx/db/user_group.py`, `external_perm.py`,
`backend/ee/onyx/external_permissions/post_query_censoring.py`, `perm_sync_types.py`,
`utils.py`, `sync_params.py`,
`backend/onyx/context/search/preprocessing/access_filters.py`,
`backend/onyx/document_index/opensearch/search.py` (the `_get_search_filters` chokepoint),
`backend/onyx/auth/schemas.py`, `permissions.py`, `backend/onyx/db/users.py`

**Does not own:** how a source system's permissions get pulled into Onyx in the
first place ([[permission-sync]] owns the crawl/sync jobs that populate
`Document.external_access` and the `ExternalUserGroup` rows this component reads),
or the chunk schema and query execution itself ([[document-index]] owns
`_get_search_filters`'s home file and the OpenSearch mapping; this document
describes only the ACL half of that function).

---

## 1. What the user experiences

A user never manages access control directly. They only ever see, in chat and in
search results, documents they already had access to in the connected source
system (Google Drive, Confluence, Slack, and so on) or documents an admin marked
public inside Onyx. There is no visible "permission" screen for a basic user; the
absence of a document from search results *is* the permission system working.

An admin (or a curator, a narrower role scoped to specific groups) manages three
things that change what a user can see:

- **User groups**: a named set of users, used to scope which connectors and
  document sets a group of people can draw from.
- **Document sets**: a named, curated subset of connectors' documents that a
  persona (agent) can be restricted to search.
- **Curator scoping**: a curator can manage document sets and connectors for
  groups they were made a manager of, without full admin access.

Both users and admins can also see identity-derived facts elsewhere in the
product: a Slack federated search result is scoped to whatever channels the
user's own Slack token can already read, not to an Onyx ACL at all (see §5.5
and §9).

---

## 2. Surfaces

### Admin routes (frontend)

| Path | Purpose |
|---|---|
| `web/src/app/admin/groups/`, `admin/groups2/` | User group management (create, rename, membership, agents). Two generations of the same UI coexist; both call the same backend. |
| `web/src/app/admin/documents/sets` | Document set management. |
| `web/src/app/admin/users/` | User list, role assignment. |
| `web/src/app/admin/scim/` | SCIM provisioning config (`ScimSyncCard.tsx`, `svc.ts`). |

### Backend endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET/POST/PATCH/DELETE | `/admin/user-group[/{id}]` | `ee/onyx/server/user_group/api.py` | EE only. Gated by `Permission.MANAGE_USER_GROUPS` / `READ_USER_GROUPS`, several with `allow_scope=True` so a curator (group manager) can reach the handler; the handler itself must then re-check scope (GATE 2). |
| GET | `/user-groups/minimal` | same file | `Permission.BASIC_ACCESS`; any authenticated user can list group names (not membership) for persona/document-set configuration UIs. |
| PUT | `/admin/user-group/{id}/permissions` | same file | `Permission.MANAGE_USER_GROUPS` / `FULL_ADMIN_PANEL_ACCESS` depending on the specific route; sets what a group's members can do, not document access. |
| CRUD | `/document-set*` | `backend/onyx/server/features/document_set/api.py` | Creating/editing a set with `is_public=False` requires naming the owning user or group(s); `filter_document_set_names_by_user_access`/`filter_document_set_ids_by_user_access` (`db/document_set.py`) are the read-side access check reused everywhere a caller supplies set names or IDs. |
| GET/PUT | `/admin/cc-pair/{id}/data-access`, `/admin/cc-pair/{id}/manage-access` | `ee/onyx/server/documents/cc_pair.py` | EE only. Data-access groups decide who reads a connector's documents. Manage-access groups (with an `EDITOR` or `OPERATOR` role) decide who administers the connector. |
| PUT | `/admin/user-group/{id}/data-access-cc-pairs`, `/admin/user-group/{id}/managed-cc-pairs` | `ee/onyx/server/user_group/api.py` | EE only. The same two relations, set from the group side. |
| GET | `/hierarchy/*` | `backend/onyx/server/features/hierarchy/api.py` | Folder/space browsing scoped by `get_user_external_group_ids` and `get_accessible_hierarchy_nodes_for_source` (see §4). |
| SCIM | `backend/ee/onyx/server/scim/*.py` | | Provisions users and groups from an external IdP; writes the same `UserGroup`/`User__UserGroup` rows the manual admin UI writes. |

### The role/permission model

`UserRole` (`backend/onyx/auth/schemas.py`) is an explicit **legacy tombstone**: it
still exists as the type of the `User.role` column, but the column is never read
or written, and the docstring says so. **Do not treat `UserRole.ADMIN` /
`CURATOR` / `BASIC` as the live authorization mechanism.** The live mechanism is:

- `Permission` (`backend/onyx/db/enums.py`), a flat set of capability tokens
  (`BASIC_ACCESS`, `READ_DOCUMENT_SETS`, `MANAGE_USER_GROUPS`,
  `FULL_ADMIN_PANEL_ACCESS`, `READ_CHAT`/`WRITE_CHAT`, and more). A user's
  `effective_permissions` (a JSONB column, computed by
  `db/scoped_permissions.py:recompute_user_permissions__no_commit`) is the union
  of permissions granted to every group they belong to, plus any
  `account_derived_permissions` from their `AccountType`.
- `AccountType` (`db/enums.py`): `STANDARD`, `SERVICE_ACCOUNT`, and others,
  independent of `Permission`.
- `User.is_group_manager` (a cached boolean): whether the user manages at least
  one non-default group. This is the closest live equivalent to the old
  "curator" concept, and it grants scoped, not global, authority: see
  `db/scoped_permissions.py:within_managed_scope_clause` and
  `auth/permissions.py:has_permission`, which returns
  `PermissionAuthority.GLOBAL` / `SCOPED` / `NONE`.
- `auth/permissions.py:require_permission(required, allow_anonymous, allow_scope)`
  is the FastAPI dependency every gated route uses. `allow_scope=True` is GATE 1:
  it lets a scoped group manager *reach* the handler; the handler itself must
  independently restrict the manager to their managed resources (GATE 2,
  `within_managed_scope_clause` for reads, an `assert_within_scope` for writes).
  A route with `allow_scope=True` and no GATE 2 check hands scoped managers
  global access.

This `Permission`/group-manager system governs **who can administer** groups,
document sets, and connectors. It is a different axis from the document-level ACL
this document otherwise describes, which governs **who can retrieve which
document** in search regardless of admin role. A basic user with no admin
permission at all still gets full document-level access to everything their
source-system identity grants.

---

## 3. Data model

```
User ──┬──< User__UserGroup >──┬── UserGroup ──< PermissionGrant
        │  (is_manager: bool)   │
        │                       └──< UserGroup__ConnectorCredentialPair >── ConnectorCredentialPair
        │                       │      (role: EDITOR | OPERATOR; who MANAGES the pair)
        │                       └──< UserGroup__CCPairDataAccess >── ConnectorCredentialPair
        │                              (who may READ the pair's documents)
        │                       └──< document sets shared with the group (join table)
        │
        └──< DocumentSet (owned, is_public=False) >──< DocumentSet__ConnectorCredentialPair >── ConnectorCredentialPair
                                                    >──< document set ⇄ user / group sharing

Document ── external_user_emails: str[]
         ── external_user_group_ids: str[]
         ── is_public: bool
         (populated by permission sync; see [[permission-sync]])

DocumentByConnectorCredentialPair ── connector_id, credential_id
ConnectorCredentialPair ── access_type: PUBLIC | SYNC | SYNC_RESTRICTED | PRIVATE

DocMetadataAwareIndexChunk (in-memory, indexing time)
  .access: DocumentAccess              # computed from the rows above
  .document_sets: set[str]
  .ancestor_hierarchy_node_ids: list[int]

OpenSearch chunk document
  ACCESS_CONTROL_LIST_FIELD_NAME: str[]   # DocumentAccess.to_acl() minus PUBLIC_DOC_PAT
  PUBLIC_FIELD_NAME: bool                 # PUBLIC_DOC_PAT split out of the list
  CC_PAIR_IDS_FIELD_NAME: int[]           # cc-pairs the document belongs to (§4.3a)
```

- `UserGroup` (`onyx/db/models.py`, EE-managed via `ee/onyx/db/user_group.py`):
  a named group. Two are seeded and protected as "default": Admin and Basic
  (`onyx/db/user_group.py:assert_group_config_is_editable`,
  `assert_not_shared_with_default_group`). Sharing a resource with the Basic
  default group is refused outright: use the resource's own `is_public` flag
  instead, since Basic holds every user.
- `PermissionGrant`: `(group_id, permission)` rows; the source of
  `User.effective_permissions`.
- `DocumentSet` (`DocumentSetDBModel`, `db/document_set.py`): `is_public`,
  `user_id` (owner for a private, groupless set), a join table to
  `ConnectorCredentialPair` (which connectors feed it) and a join to users/groups
  it is shared with. `_add_user_filters` is the one predicate every document-set
  read query applies: public, or owned, or shared via a managed/member group.
- `Document.external_user_emails` / `external_user_group_ids` / `is_public`: the
  raw permission-sync output, written by [[permission-sync]] connectors, read by
  `access.access.py` to build the indexed ACL. `ExternalUserGroup`
  (`ee/onyx/db/external_perm.py`) maps a synced external group ID to member
  emails; `fetch_public_external_group_ids` marks certain external groups (for
  example, a Google Drive domain-wide share) as effectively public.
- `HierarchyNode` (`db/hierarchy.py`): folder/space-level access, with its own
  `is_public` / `external_user_emails` / `external_user_group_ids` columns set
  from `NodeExternalAccess`, separate from but structurally identical to
  `Document`'s.
- `DocumentAccess` (`access/models.py`): the in-memory union of `user_emails`,
  `user_groups`, `external_user_emails`, `external_user_group_ids`, `is_public`.
  `DocumentAccess.to_acl()` is the **only** place that turns this into query-ready
  strings, and it is the single point of truth both the write path (indexing) and
  the read path (`build_access_filters_for_user`, indirectly) must agree with.

---

## 4. How it works

### 4.1 ACL string format (`access/utils.py`)

Every ACL entry is a prefixed string, so a user email, a group name, and an
external group ID can never collide in the same set:

- `prefix_user_email(email)` → `"user_email:{email}"`
- `prefix_user_group(name)` → `"group:{name}"`
- `prefix_external_group(id)` → `"external_group:{id}"`
- `PUBLIC_DOC_PAT = "PUBLIC"` (`configs/constants.py`), handled as a special case:
  it is never stored in the ACL list field, only as the separate boolean
  `PUBLIC_FIELD_NAME` (see §4.3).

### 4.2 Write path: computing and attaching a document's ACL

```
[[permission-sync]] connector crawl
  └─ writes Document.external_user_emails / external_user_group_ids / is_public
     and ExternalUserGroup rows                    ee/onyx/db/external_perm.py

indexing/adapters/document_indexing_adapter.py:DocumentIndexingAdapter.prepare_enrichment
  └─ get_access_for_documents(document_ids, db_session)      access/access.py
       └─ fetch_versioned_implementation("onyx.access.access", "_get_access_for_documents")
            CE: onyx.access.access._get_access_for_documents
                 → DocumentAccess.build(user_emails=..., user_groups=[], is_public=Document.is_public)
            EE: ee.onyx.access.access._get_access_for_documents
                 → calls the CE function first, then adds:
                    - user_groups from fetch_user_groups_for_documents (the data-access
                      groups of the document's PRIVATE cc-pairs; PUBLIC cc-pairs give their
                      manage groups, which changes nothing; perm-synced pairs give none)
                    - external_user_emails / external_user_group_ids from the Document row
                    - is_public widened to True if the document is public in the source
                      system, or "censoring only" applies for this source (see §4.5), or
                      one of its external groups is in fetch_public_external_group_ids

DocMetadataAwareIndexChunk.from_index_chunk(access=<DocumentAccess>, ...)
  └─ opensearch_document_index.py:generate_opensearch_filtered_access_control_list(access)
       = access.to_acl() with PUBLIC_DOC_PAT discarded
  └─ written into ACCESS_CONTROL_LIST_FIELD_NAME; access.is_public written into
     PUBLIC_FIELD_NAME
```

A document with no permission-sync-capable connector and no explicit sharing gets
`is_public=False` and an empty ACL: nobody but an admin bypassing the index (see
§9) can retrieve it until it is put in a document set or shared with a group.

### 4.3 Read path: from acting user to the query

```
build_access_filters_for_user(user, db_session)     context/search/preprocessing/access_filters.py
  └─ get_acl_for_user(user, db_session)              access/access.py
       └─ fetch_versioned_implementation("onyx.access.access", "_get_acl_for_user")
            CE: onyx.access.access._get_acl_for_user
                 anonymous  → {PUBLIC_DOC_PAT}
                 else       → {prefix_user_email(user.email),
                                *prefix_user_email(e) for e in user.prior_emails,
                                PUBLIC_DOC_PAT}
            EE: ee.onyx.access.access._get_acl_for_user
                 anonymous  → still calls the CE function underneath (same {PUBLIC_DOC_PAT}
                              result, since fetch_user_groups_for_user /
                              fetch_external_groups_for_user both short-circuit to [] for
                              an anonymous user)
                 else       → CE result UNION
                                {prefix_user_group(g.name) for g in
                                 fetch_user_groups_for_user(db_session, user.id)}
                              UNION
                                {prefix_external_group(g.external_user_group_id) for g in
                                 fetch_external_groups_for_user(db_session, user.id)}
  → UserAccessFilters: the list[str] becomes IndexFilters.access_control_list; the
    cc-pair sets (§4.3a) become IndexFilters.cc_pair_access

SearchTool.run / search_pipeline → _build_index_filters       context/search/pipeline.py
  → IndexFilters(access_control_list=<the list above>, cc_pair_access=<§4.3a>, ...)

document_index.hybrid_retrieval / keyword_retrieval / semantic_retrieval / random_retrieval
  └─ DocumentQuery._get_search_filters(access_control_list=index_filters.access_control_list, ...)
       document_index/opensearch/search.py
       └─ _get_acl_visibility_filter(access_control_list)
            {"bool": {"should": [
                {"term": {PUBLIC_FIELD_NAME: true}},
                {"terms": {ACCESS_CONTROL_LIST_FIELD_NAME: [...]}},
              ], "minimum_should_match": 1}}
       appended to filter_clauses (AND-ed with every other filter: source, tags,
       document set, time range, hierarchy scope, tenant)

  → chunks returned only if they satisfy this OR, AND everything else

fetch_ee_implementation_or_noop("onyx.external_permissions.post_query_censoring",
                                 "_post_query_chunk_censoring", noop)(chunks, user)
       CE: no-op, returns chunks unchanged
       EE: per-field censoring for sources where document-level access does not
           imply field-level access (see §4.5)
```

`build_access_filters_for_user` is called exactly once per `SearchTool.run()`
invocation, inside the single DB session opened at the top of `run()`
(`search_tool.py`), before any parallel retrieval lane starts (§5.3). Anonymous users route through
`current_chat_accessible_user`, never `current_user`, and get only
`{PUBLIC_DOC_PAT}` from either the CE or the EE `_get_acl_for_user`.

### 4.3a Query-time cc-pair access filter

A `SYNC_RESTRICTED` pair needs the workspace setting `allow_connector_group_restrictions`
(`/admin/security`, default off, Business tier to turn on). `cc_pair.py:_assert_sync_restricted_allowed`
rejects a pair that uses it while the setting is off.

A second filter works from the cc-pair a chunk belongs to instead of from the
ACL snapshot stored on the chunk. `onyx/db/connector_credential_pair.py:get_cc_pair_access_sets_for_user`
sorts every live cc-pair into three sets for the acting user:

- **Open** pairs: `PUBLIC` pairs, and non-synced pairs where the user owns the
  credential or is in a data-access group. These need no ACL match.
- **ACL** pairs: `SYNC` pairs, and `SYNC_RESTRICTED` pairs where the user is in
  a data-access group. These need a public chunk or a `user_email:` or
  `external_group:` match.
- **Hidden restricted** pairs: `SYNC_RESTRICTED` pairs that grant the user
  nothing.

`access_filters.py:build_access_filters_for_user` returns these sets as
`CCPairAccessFilter` on `UserAccessFilters`. `onyx/access/cc_pair_access.py:get_cc_pair_access_mode`
picks the `CCPairAccessMode`:

- `OFF`: the filter is not used. It is built only to hide `SYNC_RESTRICTED`
  pairs from the ACL filter.
- `SHADOW`: results use the ACL filter. The cc-pair filter is only compared and
  logged. This is the mode when `ENABLE_CC_PAIR_ACCESS_FILTER` (or the Redis
  override `cc_pair_access_filter` / `enabled`) is on.
- `ENFORCE`: results use the cc-pair filter. This needs the Redis-only flag
  `cc_pair_access_filter` / `enforce` and a finished `cc_pair_ids` backfill
  (`document_index/opensearch/cc_pair_ids_backfill.py:is_cc_pair_ids_backfill_complete`).

In `_get_search_filters`, `_get_cc_pair_access_visibility_filter` replaces the
ACL clause only in `ENFORCE` mode. In every other mode the ACL clause stays,
plus `_get_restricted_cc_pair_guard`, which removes chunks of hidden restricted
pairs unless another pair of the chunk grants access. Chunks with no cc-pair
(user files) fall back to the ACL filter. `user_can_access_chat_file` applies the
same rule in Python.

### 4.4 Document sets and hierarchy scope: an additive, not alternative, filter

A document set or hierarchy scope narrows *which* documents are searched; it does
not replace ACL enforcement. `_build_index_filters`
(`context/search/pipeline.py`) resolves `document_set` names against
`persona_document_sets` or user-supplied names, and separately resolves
`attached_document_ids` / `hierarchy_node_ids` for assistant-knowledge scoping.
All of these become additional AND-ed clauses inside `_get_search_filters`
alongside, never instead of, `_get_acl_visibility_filter`. A user who can see a
document set's *name* is not thereby granted access to documents inside it that
their own ACL would otherwise exclude; the ACL clause still applies to every
result.

`filter_document_set_names_by_user_access` / `filter_document_set_ids_by_user_access`
(`db/document_set.py`) are the DB-level check on whether a user may reference a
document set by name/ID at all (§5.2); they are unrelated to whether a specific
document inside an authorized set passes the ACL clause.

Hierarchy node (folder) browsing is a parallel, DB-level ACL check, not the
index-query one: `db/hierarchy.py:get_accessible_hierarchy_nodes_for_source` /
`filter_accessible_hierarchy_node_ids` dispatch through
`fetch_versioned_implementation("onyx.db.hierarchy", ...)`. The CE
implementation is explicitly unfiltered by design
(`onyx/db/hierarchy.py`, comment: "MIT hierarchy queries intentionally omit
permission filters... Supported Community connectors are public"); the EE
implementation (`ee/onyx/db/hierarchy.py`) applies the real per-node ACL, keyed
by `get_user_external_group_ids` (`access/hierarchy_access.py`, dispatched the
same CE/EE way as `get_acl_for_user`). This governs the folder-browse UI
(`server/features/hierarchy/api.py`), not chunk retrieval.

### 4.5 EE post-query field censoring

Some connectors (Salesforce is the concrete example in
`ee/onyx/external_permissions/sync_params.py`) can only sync document-level
access, not field-level access, at index time; a user may be allowed to see a
record but not every field on it. For these sources,
`_get_access_for_documents` marks the document `is_public` at the index level
("is_only_censored" in the EE `_get_access_for_documents`, when a source's
`perm_sync_config.censoring_config` is set but `doc_sync_config` is not) so it
passes the ACL clause for everyone, then narrows the actual field content after
retrieval:

`ee/onyx/external_permissions/post_query_censoring.py:_post_query_chunk_censoring`
groups the retrieved chunks by source, and for each source with censoring
enabled, calls that source's `censor_chunks_for_source` function
(`CensoringFuncType`, `perm_sync_types.py`) with the user's email. A chunk
missing from the censoring function's output is dropped, not degraded; a
censoring function that raises drops every chunk for that source rather than
leaking anything. Anonymous users get every chunk from a censored source
dropped outright, without calling the censoring function at all.

This runs inside `search_pipeline` (`context/search/pipeline.py`), after the
index query returns and before results reach rank fusion, via
`fetch_ee_implementation_or_noop`, so it is a genuine no-op in CE, not a
degraded check.

---

## 5. Contracts and invariants

These are the rules whose violation is silent: nothing crashes, a user just sees
(or does not see) the wrong documents.

1. **`_get_search_filters` (`document_index/opensearch/search.py`) is the single
   chokepoint for every ACL-enforced query.** Verified: every call site that
   passes a real, non-`None` `access_control_list` (the four hybrid/keyword/
   semantic/random query builders and the ID-based retrieval builder, all in
   `search.py`) routes through this one function, and it is the only place
   `_get_acl_visibility_filter`, `_get_cc_pair_access_visibility_filter`, and
   `_get_restricted_cc_pair_guard` are invoked. No other function in the codebase
   builds an OpenSearch `filter` clause referencing
   `ACCESS_CONTROL_LIST_FIELD_NAME` or `PUBLIC_FIELD_NAME`. A new retrieval
   entry point that hand-builds a query instead of going through
   `DocumentQuery._get_search_filters` bypasses ACL enforcement entirely.
2. **`access_control_list=None` means "no ACL restriction applied", not "public
   only".** This is deliberate at exactly three call sites, each with an
   established, narrow justification: `_retrieve_adjacent_chunks` and
   `inference_sections_from_ids` (`search_utils.py`) fetch chunks of a document
   the caller already retrieved through an ACL-filtered search moments earlier;
   `_run_slack_search` (`search_tool.py`) relies on Slack's own token scope
   (§5.5); and `delete_from_document_id_query`
   (`document_index/opensearch/search.py`) is a background maintenance
   operation, not a user-facing read. **Any new call site passing
   `access_control_list=None` is a security review, not a refactor**: it must
   justify, in the same way as one of these, why the caller already enforced
   access some other way.
3. **There is no ACL bypass flag.** `bypass_acl` does not exist anywhere in
   the codebase (`grep -rn "bypass_acl" backend/` is empty). Every search
   path builds its filters through `_build_index_filters`
   (`context/search/pipeline.py`) and `_get_search_filters`
   (`document_index/opensearch/search.py`, item 1), with no parameter that
   disables ACL enforcement for an entire search. A change that reintroduces
   a bypass parameter on `ChunkSearchRequest`, `SearchToolConfig`, or
   `SearchTool` is a security review, not a refactor.
4. **User-supplied document-set names are always re-checked server side**, in
   two independent places that must both stay in place:
   `filter_document_set_names_by_user_access` inside `_build_index_filters`,
   and the equivalent check in `SearchTool.run` before that. Unauthorized names
   raise `OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)`. Both checks are
   skipped when the user is anonymous or (for `_build_index_filters`) no
   `db_session` is available.
5. **The Slack federated lane carries no ACL and is a deliberate exception.**
   `_run_slack_search` builds its request with
   `IndexFilters(access_control_list=None)`; access is enforced entirely by the
   scope of the pre-fetched Slack OAuth or bot token, which Slack itself
   restricts to channels that token can read. This is safe only as long as
   (a) the token is fetched fresh per user/session rather than shared, and
   (b) Slack results never merge into the same OpenSearch-backed ACL machinery
   the rest of the pipeline uses. Verify both hold before trusting this lane
   for a new federated source; do not assume a new federated connector gets
   the same exemption without the same reasoning.
6. **The ACL is always computed from the acting `User` object passed into
   `get_acl_for_user`/`build_access_filters_for_user`, never from a
   client-supplied value.** There is no HTTP parameter anywhere in this
   component that lets a caller specify whose ACL to use; the user comes from
   the authenticated dependency chain (`current_user` /
   `current_chat_accessible_user`) established before this component runs.
7. **Anonymous users get public documents only**, in both CE and EE
   (`_get_acl_for_user` returns `{PUBLIC_DOC_PAT}` for `user.is_anonymous` in
   both, since the EE group-lookup functions themselves short-circuit to `[]`
   for an anonymous user). A change that adds a new ACL source but forgets to
   gate it on `is_anonymous` widens anonymous access silently.
8. **The read path and the write path must agree on the ACL string format.**
   Both derive from `access/utils.py`'s three prefix functions and from
   `DocumentAccess.to_acl()`. If either side changes a prefix, a separator, or
   how `PUBLIC_DOC_PAT` is split out of the list, the mismatch fails silently:
   either every document looks inaccessible (fails closed, an availability bug)
   or every ACL entry stops matching and only public documents remain visible
   (also fails closed). If instead the two sides drift to independently valid
   but different formats that happen to still intersect on some strings, it
   can fail open. Treat any change to prefixing or to `DocumentAccess.to_acl()` as
   requiring a full reindex (§7) and an explicit read/write parity check, not
   just a unit test of one side.
9. **EE dispatch must degrade safely in CE; a missing EE implementation must
   never widen access.** Every dispatch point here
   (`_get_acl_for_user`, `_get_access_for_documents`,
   `_get_user_external_group_ids`,
   `_get_accessible_hierarchy_nodes_for_source`/`_filter_accessible_hierarchy_node_ids`)
   goes through `fetch_versioned_implementation`, which falls back to the CE
   module only on `ModuleNotFoundError` naming `ee.onyx`
   (`utils/variable_functionality.py`). The CE fallback for every one of these
   is a strict subset of what EE would compute (fewer ACL entries, an empty
   group list, an unfiltered-but-narrower hierarchy result whose actual
   permission logic never runs), so the fallback narrows or leaves access
   unchanged, never widens it. A new dispatched function must preserve this
   direction: if CE cannot compute the real answer, its fallback must return
   the more restrictive one.
10. **`_get_acl_visibility_filter`'s output is deliberately cacheable in
    isolation from the rest of `_get_search_filters`'s clauses** (per its own
    docstring). A change that folds ACL logic into a combined clause with
    other filters should re-verify this caching assumption still holds; see
    [[document-index]] for the OpenSearch filter-cache mechanics.

---

## 6. Relationships

**Depends on**
- [[permission-sync]]: populates `Document.external_user_emails`,
  `external_user_group_ids`, `is_public`, and `ExternalUserGroup` rows that
  `_get_access_for_documents` (EE) and `_get_acl_for_user` (EE) read. This
  component computes and enforces the ACL; permission-sync is where the
  ACL's raw material comes from.
- [[auth-and-identity]]: supplies the authenticated `User` object
  (`current_user`/`current_chat_accessible_user`) that every ACL computation in
  this component keys on, and the `Permission`/`AccountType` model this
  document's §2 describes.
- [[editions-and-gating]]: `global_version.is_ee_version()` and
  `fetch_versioned_implementation` are how every CE/EE split in this document
  is decided at runtime.

**Depended on by**
- [[internal-search]]: `build_access_filters_for_user` is called once per
  `SearchTool.run()`, and its output flows into every non-bypassed,
  non-Slack retrieval lane's `IndexFilters`.
- [[document-index]]: `_get_acl_visibility_filter` lives inside that
  component's `_get_search_filters`, which this document treats as the shared
  chokepoint; see that document's §4.3 and §5.2 for the query-construction side
  of the same contract.
- [[core-chat-loop]]: every chat turn's search tool call carries the acting
  user's ACL through this component; a chat turn never queries the index
  without it (outside the exceptions in §5).
- [[agents-personas]]: a persona's configured document sets and hierarchy
  scope are resolved through `_build_index_filters`, which layers on top of,
  never replaces, this component's ACL clause.
- [[multi-tenancy]]: tenant isolation (`TENANT_ID_FIELD_NAME`) is a separate
  filter clause inside the same `_get_search_filters`, AND-ed alongside the ACL
  clause; this document does not cover tenant isolation itself, only that it
  composes with ACL rather than substituting for it.
- The onyx-cli/programmatic `/search` endpoint and the EE Search UI backend
  (see [[internal-search]] §2) reuse `build_access_filters_for_user` the same
  way chat does.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes an ACL string prefix or `DocumentAccess.to_acl()` | requires a full reindex; read (`_get_acl_for_user`) and write (`_get_access_for_documents`) must change in the same PR, never one ahead of the other (§5.8) |
| adds a new ACL source (a new kind of group, a new external-permission concept) | both `_get_acl_for_user` (read) and `_get_access_for_documents` (write) in **both** CE and EE, or CE's narrower fallback silently drifts from what EE now computes; add it to `DocumentAccess` first, not as a parallel field |
| adds a new filter to `IndexFilters`/`BaseFilters` | [[document-index]]'s `_get_search_filters`; confirm it AND-composes with the ACL clause rather than replacing it; the two document-set access checks in `SearchTool.run` and `_build_index_filters` |
| adds a new retrieval lane or federated source | does it carry `access_control_list`, or is it claiming the same exemption as Slack (§5.5)? That claim needs its own justification, not a copy-paste of the Slack comment |
| adds a new search entry point (a new endpoint, a new tool, a new background job that queries the index) | it must call `build_access_filters_for_user` (or explicitly justify why not, per §5.2) before building `IndexFilters`; it must not construct a query outside `DocumentQuery._get_search_filters` |
| touches `fetch_versioned_implementation` dispatch or `global_version` | every CE/EE pair in this document; verify the CE fallback still narrows rather than widens (§5.9) |
| changes group membership resolution (`fetch_user_groups_for_user`, `fetch_external_groups_for_user`) | re-run the two-user integration test (§8); a stale cache or a membership write that doesn't invalidate it is a data-exposure bug, not a performance bug |
| changes curator/group-manager scoping (`is_group_manager`, `within_managed_scope_clause`, `allow_scope`) | every route using `require_permission(..., allow_scope=True)` has a real GATE 2 check; this governs admin capability, not document ACL, but a bug here can let a curator manage a document set outside their scope, which does affect who a persona can search |
| adds an ACL bypass parameter anywhere in the search chain | re-verify §5.3 still holds: there is no such flag today. Adding one is a security review |

---

## 8. How to verify a change

### Tests

```bash
# The preferred level for this component: integration tests exercise the whole
# read path, not just one function.
cd backend && uv run pytest tests/integration/tests/permissions_access -k "not scim"
cd backend && uv run pytest tests/integration/tests/permissions_membership
cd backend && uv run pytest tests/integration/tests/permissions_resources
cd backend && uv run pytest tests/integration/tests/usergroup
cd backend && uv run pytest tests/integration/tests/chat/test_chat_document_set_access.py
cd backend && uv run pytest tests/integration/tests/indexing/test_initial_permission_sync.py
cd backend && uv run pytest tests/external_dependency_unit/permission_sync
cd backend && uv run pytest tests/unit -k "access or acl or user_group or document_set"
```

`tests/integration/common_utils/document_acl.py` (`get_user_acl`,
`get_user_document_access_via_acl`) is a reusable test helper that recomputes a
user's expected ACL independently of search ranking, specifically so a
permission test does not depend on retrieval relevance to prove a document was
or was not reachable.

See `backend/AGENTS.md` for authoritative commands and required secrets/env.

### Manual reproduction: the two-user test

This is the load-bearing manual check for this component. A change here is not
verified by "it still returns documents"; it is verified by a second user
*not* getting a document the first user can see.

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. As `admin_user@example.com` / `TestPassword123!`, index or upload a document
   visible only to a specific user or group (for example, a File connector
   upload shared with one user, or a document set restricted to one group).
3. Register or use a second user (User B) who is **not** in that group and was
   not granted direct access.
4. As User B, confirm the document does not appear:
   - **Through chat**: ask a question that should surface the document if
     visible; confirm no citation to it and no mention in the search tool's
     document cards.
   - **Through `/api/search`** (via the frontend, per this repo's `CLAUDE.md`
     rule: call `http://localhost:3000/api/search`, not the backend port
     directly): confirm the document is absent from the ranked sections.
   - **Through any other entry point your change touches** (the EE Search UI,
     the onyx-cli query path, a federated lane): the same absence must hold.
5. As User A (or a member of the granted group), confirm the same document
   **does** appear through the same entry points.
6. If your change touches document sets or groups specifically, also run
   `filter_document_set_names_by_user_access` end to end: request a search
   naming a document set User B has no access to and confirm
   `OnyxErrorCode.INSUFFICIENT_PERMISSIONS`, not an empty result (an empty
   result would mask a broken check as an unrelated ranking miss).

### What "working" looks like

- A document restricted to User A never appears in any of User B's search
  surfaces, not just chat.
- A document set name User B cannot access raises
  `INSUFFICIENT_PERMISSIONS`, not a silent empty scope.
- An anonymous session sees only documents where `is_public=True`.
- Revoking a user's group membership removes their access to that group's
  documents on the **next** ACL computation (this reads live from
  `fetch_user_groups_for_user`; there is no separate cache to invalidate in
  the read path itself, though `User.effective_permissions`, the *admin
  permission* cache, is recomputed explicitly by
  `recompute_permissions_for_group__no_commit` and is a different mechanism
  from document ACL, see §2).

---

## 9. Footguns

- **The Slack federated lane is not ACL-filtered like everything else.** Its
  `IndexFilters.access_control_list` is `None` by construction; access is
  whatever the pre-fetched Slack token can see. Do not assume every lane in a
  fan-out search carries the same protection, and do not copy this pattern to
  a new federated source without independently justifying it the way §5.5
  requires.
- **CE and EE genuinely differ in what a user can see, not just in what an
  admin can configure.** The EE `_get_acl_for_user` adds every internal user
  group and every synced external group the user belongs to; CE never does.
  Testing a permission change only in CE (the default local dev setup) proves
  nothing about whether the EE group-derived ACL entries still compose
  correctly, and vice versa. Verify both editions before trusting a fix.
- **The cc-pair filter has three modes and only `ENFORCE` changes results.**
  `SHADOW` logs disagreements and still returns ACL-filtered results. `ENFORCE`
  needs the Redis flag and a complete `cc_pair_ids` backfill, so a tenant can
  have the master flag on and still run the ACL filter. A `SYNC_RESTRICTED`
  pair is hidden in every mode, because the ACL alone cannot express it.
- **A change to how the ACL is computed does not take effect until a
  reindex.** The ACL stored on an already-indexed chunk is a snapshot from
  whenever it was last written or updated (`Updatable.update`, see
  [[document-index]]); changing `_get_acl_for_user`'s or
  `_get_access_for_documents`'s logic changes what a *future* write computes,
  not what is already in the index. A permission bug fix can look "fixed" in
  code review and still leak or hide documents in production until a resync
  or reindex runs.
- **`PUBLIC_DOC_PAT` is a bare string convention (`"PUBLIC"`), not a typed
  sentinel.** Nothing stops a future ACL source from independently producing
  the literal string `"PUBLIC"` as a legitimate group or email-derived entry
  and accidentally granting public visibility. `prefix_user_email`/
  `prefix_user_group`/`prefix_external_group` avoid this for their own
  categories by prefixing, but `PUBLIC_DOC_PAT` itself is unprefixed by
  design (§4.1) precisely so it can be split into its own index field; treat
  it as reserved.
- **A curator's `is_group_manager` scope is about admin capability
  (managing connectors, document sets, groups), not about which documents
  they personally can search.** A curator's own document-level ACL is
  computed the same way as any other user's, through `_get_acl_for_user`;
  being a group manager does not add that group's documents to their personal
  ACL unless they are also a member.
