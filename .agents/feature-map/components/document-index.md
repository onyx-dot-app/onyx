# Document Index

> The searchable index itself. It stores document chunks with their vectors and
> metadata, answers hybrid/keyword/semantic/random/id-based retrieval calls, and
> tracks the state machine for swapping in a new embedding model.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** search-index
**Edition:** CE, with multi-tenant sharding differences on AWS-managed OpenSearch
**Owns:**
`backend/onyx/document_index/interfaces.py`, `factory.py`, `disabled.py`,
`backend/onyx/document_index/opensearch/` (`opensearch_document_index.py`, `search.py`,
`schema.py`, `constants.py`, `client.py`, `cluster_settings.py`, `index_reclaim.py`,
`port_copy.py`, `string_filtering.py`, `cc_pair_ids_backfill.py`),
`backend/onyx/db/search_settings.py`, `swap_index.py`,
`backend/onyx/natural_language_processing/search_nlp_models.py`,
`backend/onyx/server/manage/search_settings.py`, `backend/onyx/server/manage/embedding/`

**Does not own:** the retrieval orchestration that decides what to search and how to
merge results across sources ([[internal-search]]), or the chunking/embedding pipeline
that produces the `DocMetadataAwareIndexChunk` objects this component writes
([[indexing-pipeline]]). This document stops at the `DocumentIndex` interface boundary
on both sides: it describes what happens once a chunk crosses `index()`, and what a
caller gets back from `hybrid_retrieval()`, not how either caller assembled its input.

---

## 1. What the user experiences

Most users never see this component directly. It is the layer that makes search fast
and correct: which documents a query can see, how well a query matches a chunk, and
whether the index is healthy.

Full admins see a resource-warning popup when entering Onyx, at most once per 24 hours.
A compact persistent admin banner opens details for disk, JVM heap, and native vector-cache pressure.
Both direct admins to their system administrator or support@onyx.app.
`backend/onyx/document_index/opensearch/resource_health.py` checks the cluster every five minutes
through the monitoring worker. The API only reads cached results. Stale warnings remain
in the banner, but cannot trigger a popup. See `backend/onyx/document_index/opensearch/README.md`
for thresholds, timeouts, and recovery behavior.

An admin experiences it directly on the embedding-model page. They pick a new
embedding model (self-hosted, Cohere, OpenAI, Azure, Bedrock, Vertex, LiteLLM, and
more), optionally run a sample embedding test (a fixed test string, not a document), and start a re-index. From that point,
Onyx builds a second, parallel index in the background using the new model while the
old index keeps serving live search. A progress view shows re-index status and errors.
When indexing catches up (the exact criterion depends on the switchover type chosen),
Onyx switches live search to the new index automatically, and the old index is later
torn down. Search quality and result ordering can visibly shift right after a switch,
because the new model can rank chunks differently.

OpenSearch is the only backend. The earlier Vespa backend and the Vespa-to-OpenSearch
data migration are gone. Migration `3067343245d1_drop_opensearch_migration_tables`
dropped the migration tables, and #15336 removed Vespa and the retrieval toggle.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/manage/admin/opensearch-health` | `read_resource_health` | Cached resource pressure; requires `FULL_ADMIN_PANEL_ACCESS`. |
| POST | `/manage/admin/opensearch-health/popup` | `claim_resource_popup` | Claims a tenant-scoped, per-admin 24-hour popup allowance in Redis. |
| POST | `/search-settings/set-new-search-settings` | `set_new_search_settings` | Creates a FUTURE `SearchSettings` row, starts a re-index. Requires `FULL_ADMIN_PANEL_ACCESS`. |
| POST | `/search-settings/cancel-new-embedding` | `cancel_new_embedding` | Cancels the in-flight FUTURE re-index. |
| DELETE | `/search-settings/delete-search-settings` | | |
| GET | `/search-settings/get-current-search-settings` | | The PRESENT row. |
| GET | `/search-settings/get-secondary-search-settings` | | The FUTURE row, if any. |
| GET | `/search-settings/get-all-search-settings` | | |
| GET | `/search-settings/reindex-progress` | | |
| GET | `/search-settings/reindex-errors` | | |
| POST | `/search-settings/reindex/port/resume` | | Resumes a stalled reindex-port backfill. |
| POST | `/search-settings/update-inference-settings` | | |
| GET/PUT/DELETE | `/search-settings/unstructured-api-key-set`, `/upsert-unstructured-api-key`, `/delete-unstructured-api-key` | | Unrelated document-parsing key, colocated in this router. |
| POST | `/admin/embedding/test-embedding` | `test_embedding_configuration` (`server/manage/embedding/api.py`) | Dry-run an embedding call against a candidate config. |
| GET | `/admin/embedding` | `list_embedding_models` | |
| GET/PUT/DELETE | `/admin/embedding/embedding-provider[/{provider_type}]` | | Cloud embedding provider credentials. |

Per the frontend rule in `CLAUDE.md`, always call these through the web server
(`http://localhost:3000/api/...`), never the backend port directly.

### Environment configuration (`backend/onyx/configs/app_configs.py` unless noted)

| Variable | Default | Effect |
|---|---|---|
| `DISABLE_VECTOR_DB` | false | `get_default_document_index` returns `DisabledDocumentIndex` instead of a real backend. Every method except `verify_and_create_index_if_necessary` raises `RuntimeError`. |
| `USING_AWS_MANAGED_OPENSEARCH` | false | Changes shard/replica counts (`schema.py:DocumentSchema.get_index_settings_based_on_environment`) and gates IAM auth. |
| `OPENSEARCH_TEXT_ANALYZER` | `"english"` | Stemming/tokenization analyzer for `title`/`content`. Changing it needs a reindex of existing indices. |
| `OPENSEARCH_INDEX_NUM_SHARDS` / `OPENSEARCH_INDEX_NUM_REPLICAS` | environment-dependent | Override shard/replica counts. |
| `HYBRID_SEARCH_NORMALIZATION_PIPELINE` | `1` (`MIN_MAX`) | Integer enum value. `2` is `ZSCORE`. Chooses the OpenSearch normalization technique (`opensearch/constants.py`). |
| `ENABLE_CC_PAIR_ACCESS_FILTER` | false | Fallback for the `cc_pair_access_filter` `enabled` runtime flag. True turns on shadow mode (see §4.3). The `enforce` flag has no env var and defaults to false. |
| `DEFAULT_NUM_HYBRID_SUBQUERY_CANDIDATES` | 500 | Candidates fetched per hybrid subquery before fusion. |
| `HYBRID_ALPHA` | 0.5 (`configs/chat_configs.py`) | Caller-level keyword/semantic hint. The env default is clamped to `[0, 1]`. A caller-provided `hybrid_alpha` is not validated. See §4.3 and §9 for how little of this the index actually uses. |
| `OPENSEARCH_MATCH_HIGHLIGHTS_DISABLED` | true | Disables highlight computation in query bodies. |
| `OPENSEARCH_EXPLAIN_ENABLED` | false | Adds scoring breakdowns; documented as roughly 1000x slower for hybrid search in practice. |
| `PIT_KEEP_ALIVE` | `"5m"` | Point-in-time lease used by the reindex port's consistent scan. |
| `VERIFY_CREATE_OPENSEARCH_INDEX_ON_INIT_MT` | true | Whether multi-tenant cloud checks/creates the index on every `OpenSearchDocumentIndex` construction. |

---

## 3. Data model

### `SearchSettings` (Postgres, `onyx.db.models.SearchSettings`)

The configuration row for one embedding model generation. Selected by status:

- `get_current_search_settings` (`db/search_settings.py`): the row with
  `status == IndexModelStatus.PRESENT`, the live model.
- `get_secondary_search_settings`: the row with `status == IndexModelStatus.FUTURE`,
  a re-index in progress, or `None`.
- `ActiveSearchSettings` / `get_active_search_settings`: bundles both.

`IndexModelStatus` (`db/enums.py`): `PAST`, `PRESENT`, `FUTURE`. Only one row is
normally PRESENT and at most one is FUTURE at a time; `get_current_search_settings`
raises if none is PRESENT.

Fields that matter to this component: `model_name`, `model_dim`, `normalize`,
`query_prefix`, `passage_prefix`, `api_key`, `provider_type`, `api_url`,
`deployment_name`, `reduced_dimension`, `vector_quantization`, `index_name`,
`switchover_type`, `use_port_flow`, `port_backfill_source_id`, and the reclaim columns
`reclaim_status`, `reclaim_stopped_reading_at`, `reclaim_attempts`,
`reclaim_last_error`, `pending_cc_pair_deletions`.

`IndexReclaimStatus` (`db/enums.py`): `PENDING`, `SOAKING`, `DELETING`, `RECLAIMED`,
`BLOCKED`. Governs deletion of a PAST index's data after a swap; see §4.4.

### The chunk schema (OpenSearch, `opensearch/schema.py`)

`DocumentSchema.get_document_schema` builds the mapping with `"dynamic": "strict"`, so
an unexpected field on write is a hard error, not a silent drop. `DocumentChunk`
(`schema.py`) is the pydantic model whose field names **must** match the schema
one-to-one; `DocumentChunkWithoutVectors` is the same shape without the vector fields,
used for query responses that exclude vectors.

Field-name constants (all in `opensearch/schema.py`), grouped by role:

- Content and vectors: `TITLE_FIELD_NAME`, `CONTENT_FIELD_NAME` (`text`, stemmed by
  `OPENSEARCH_TEXT_ANALYZER`), `TITLE_VECTOR_FIELD_NAME`, `CONTENT_VECTOR_FIELD_NAME`
  (`knn_vector`, HNSW/`cosinesimil`/`lucene` engine, `EF_CONSTRUCTION`/`M` from
  `opensearch/constants.py`). `title_vector` is still mapped but no longer written or
  queried; existing indices keep stored values until chunks are rewritten.
- Access control: `PUBLIC_FIELD_NAME`, `ACCESS_CONTROL_LIST_FIELD_NAME`,
  `HIDDEN_FIELD_NAME`.
- Identity and chunking: `DOCUMENT_ID_FIELD_NAME`, `CHUNK_INDEX_FIELD_NAME`,
  `MAX_CHUNK_SIZE_FIELD_NAME`, `TENANT_ID_FIELD_NAME` (present only when
  `multitenant`).
- Filtering metadata: `SOURCE_TYPE_FIELD_NAME`, `METADATA_LIST_FIELD_NAME`,
  `LAST_UPDATED_FIELD_NAME`, `CREATED_AT_FIELD_NAME`, `DOCUMENT_SETS_FIELD_NAME`,
  `USER_PROJECTS_FIELD_NAME`, `PERSONAS_FIELD_NAME`,
  `ANCESTOR_HIERARCHY_NODE_IDS_FIELD_NAME` (hierarchy-scoped search, uses an
  OpenSearch bitmap `terms` query), `CC_PAIR_IDS_FIELD_NAME` (IDs of the cc-pairs
  that own the document; see §4.3), `PRIMARY_OWNERS_FIELD_NAME`,
  `SECONDARY_OWNERS_FIELD_NAME`.
- Display-only, not searchable (`index: False`, `doc_values: False`, `store: False`):
  `SEMANTIC_IDENTIFIER_FIELD_NAME`, `IMAGE_FILE_ID_FIELD_NAME`,
  `SOURCE_LINKS_FIELD_NAME`, `BLURB_FIELD_NAME`, `DOC_SUMMARY_FIELD_NAME`,
  `CHUNK_CONTEXT_FIELD_NAME`, `METADATA_SUFFIX_FIELD_NAME`.
- Bookkeeping: `GLOBAL_BOOST_FIELD_NAME`,
  `WRITTEN_BY_PORT_FIELD_NAME` (marks chunks written by the reindex port so the
  orphan sweep's delete-by-query can find and remove them).

The chunk ID itself (`schema.py:get_opensearch_doc_chunk_id`) encodes
`document_id + "__" + max_chunk_size + "__" + chunk_index`, hashed with blake2b if the
document ID would overflow OpenSearch's ID length limit, with a tenant-ID prefix in
multi-tenant mode.

### Redis / cache

None owned directly by this component; caching for search results lives above it in
[[internal-search]].

---

## 4. How it works

### 4.1 The abstraction and backend selection

`DocumentIndex` (`interfaces.py`) is the contract every backend implements. It is
composed from capability mixins so different call sites can type-narrow to only what
they need: `SchemaVerifiable` (`verify_and_create_index_if_necessary`), `Indexable`
(`index`), `Updatable` (`update`), `Deletable` (`delete`), `HybridCapable`
(`hybrid_retrieval`, `keyword_retrieval`, `semantic_retrieval`), `IdRetrievalCapable`
(`id_based_retrieval`), `RandomCapable` (`random_retrieval`).

`OpenSearchDocumentIndex` (`opensearch/opensearch_document_index.py`) is the only real
implementation. A `DisabledDocumentIndex` (`document_index/disabled.py`) is used when `DISABLE_VECTOR_DB` is set.
Every method except `verify_and_create_index_if_necessary` (a no-op) raises `RuntimeError`, so a stray vector-DB call fails fast.

`OpenSearchIndexPair` wraps a `primary` and an optional `secondary`
`OpenSearchDocumentIndex` behind the same `DocumentIndex` interface. Its fan-out rules
differ by call:

- `index` writes to the primary only. The port backfill (`port_copy.py`, the `port`
  Celery tasks) fills the secondary.
- `delete`, `update`, and `verify_and_create_index_if_necessary` go to both.
- All retrieval goes to the primary.

`factory.py:get_default_document_index(search_settings, secondary_search_settings, *,
primary_backfill_in_progress=False)` is the single entry point for both retrieval and
writes:

1. `DISABLE_VECTOR_DB` -> `DisabledDocumentIndex()`.
2. Otherwise, it builds an `OpenSearchIndexPair` (`build_opensearch_document_index`
   per `SearchSettings`). `secondary` is `None` when `secondary_search_settings` is
   `None`.

Most callers pass `None` as the second argument. They get a one-index handle for the
generation they work on. Callers that must reach both generations pass the FUTURE
settings, for example `server/manage/search_settings.py` and the connector cleanup task
(`tasks/shared/tasks.py`). `primary_backfill_in_progress` marks an INSTANT-swap primary
that the port is still filling. `OpenSearchIndexPair.update` then raises
`SecondaryIndexDocumentMissingError` for documents the port has not copied yet.

### 4.2 Writing

`Indexable.index(chunks, indexing_metadata)` takes an iterable of
`DocMetadataAwareIndexChunk` (owned by [[indexing-pipeline]]) and returns
`DocumentInsertionRecord` per document (new vs. already-existed). The interface
contract, not just convention: all chunks for one document arrive in a single `index()`
call, never split across calls, and the implementation is responsible for deleting any
now-stale trailing chunks when a re-indexed document got shorter (using
`IndexingMetadata.doc_id_to_chunk_cnt_diff`).

`Updatable.update(update_requests)` patches ACL, document-set membership, boost,
hidden, project/persona membership, and `secondary_index_updated` without a
re-embed. `MetadataUpdateRequest` can raise `SecondaryIndexDocumentMissingError`
mid-port, when a metadata update lands on the primary before the reindex port has
copied that document into the FUTURE index; callers use this to defer the secondary
sync instead of failing outright.

`SchemaVerifiable.verify_and_create_index_if_necessary(embedding_dim)` is called on backend construction paths and at swap time
(`swap_index.py:_perform_index_swap`) to make sure the physical index exists before
anything writes to it.

### 4.3 Querying and score combination

`HybridCapable` exposes three retrieval modes plus `RandomCapable.random_retrieval`
and `IdRetrievalCapable.id_based_retrieval` (reconstructing a document or a
contiguous chunk range, assuming non-overlapping chunking).

For OpenSearch, one hybrid call is built by
`search.py:DocumentQuery.get_hybrid_search_query`. It assembles keyword and vector
subqueries (`_get_hybrid_search_subqueries`: a `content_vector` k-NN query and a
combined title/content keyword query), wraps them in an OpenSearch `hybrid` compound
query with a shared `pagination_depth` and a single AND-ed `filter.bool.filter` list,
and excludes the vector fields from `_source` on the way back out.

Score combination happens in an OpenSearch **search pipeline**, not in application
code: `get_normalization_pipeline_name_and_config` selects `min_max` or `z_score`
normalization (`HYBRID_SEARCH_NORMALIZATION_PIPELINE`), and both build a
`normalization-processor` with `combination.technique = "arithmetic_mean"` and
`_get_hybrid_search_normalization_weights()` as the per-subquery weights:
content-vector 0.5, combined keyword 0.5.

`_get_hybrid_search_normalization_weights` asserts the weights it returns sum to
`1.0`, and a code comment states the weight order must match the subquery order
exactly, since OpenSearch has no other way to associate a weight with a clause.

`hybrid_alpha` (a float on the caller's `ChunkIndexRequest`, defaulting to
`HYBRID_ALPHA = 0.5`) is resolved in `context/search/retrieval/search_runner.py` into
a `QueryType`: `<= 0.2` maps to `QueryType.KEYWORD`, otherwise `QueryType.SEMANTIC`.
That `QueryType` is passed into `hybrid_retrieval`, but
`OpenSearchDocumentIndex.hybrid_retrieval` marks the parameter `# noqa: ARG002`
(unused) and never branches on it; the hybrid query always runs the same
weighted keyword+vector fusion regardless of `query_type`. The only place
`hybrid_alpha` actually changes behavior is `search_runner.py:search_chunks`:
`hybrid_alpha == 0.0` skips embedding entirely and calls `keyword_retrieval` directly
instead of `hybrid_retrieval`.

`_get_search_filters` (`search.py:DocumentQuery._get_search_filters`) is the single
function that compiles every filter into the AND-ed `bool.filter` list used by hybrid,
keyword, semantic, and random queries alike: ACL visibility
(`_get_acl_visibility_filter`, a `should` of `{"term": {public: true}}` OR
`{"terms": {access_control_list: [...]}}`, `minimum_should_match: 1`), the optional
cc-pair access filter (below), source types,
tags, document sets, per-user-project and per-persona filters, created/updated time
ranges, chunk index and chunk size, an attached-document-id or hierarchy-node clause,
tenant ID (multi-tenant only), and forced document sets.

**Query-time cc-pair access filter.** `IndexFilters.cc_pair_access` is a
`CCPairAccessFilter` with a mode (`CCPairAccessMode`: `OFF`, `SHADOW`, `ENFORCE`).
`access/cc_pair_access.py:get_cc_pair_access_mode` picks the mode. It returns `None`
when the `cc_pair_access_filter` `enabled` flag is off (env fallback
`ENABLE_CC_PAIR_ACCESS_FILTER`). It returns `ENFORCE` only when the `enforce` flag
is on and `is_cc_pair_ids_backfill_complete` is true. Otherwise it returns `SHADOW`.
In `SHADOW` mode, results use the old ACL filter. A background check
(`_log_cc_pair_access_shadow_disagreement`, at most 4 in flight) logs sample chunks
where the old and new filters disagree. In `ENFORCE` mode,
`_get_enforced_cc_pair_access` swaps in the cc-pair filter, which tests
`cc_pair_ids` against the user's open and ACL cc-pairs. Chunks with no cc-pair (user
files) fall back to the old ACL filter. Even in `OFF` mode, the filter exists to hide
`SYNC_RESTRICTED` cc-pairs (`hidden_restricted_cc_pair_ids`). See [[permission-sync]].
Chunks get `cc_pair_ids` at index time. The beat task
`cc_pair_ids_backfill` fills older chunks without re-embedding, with progress in the
KV store (`KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY`), restarted per `SearchSettings`
generation. Metadata sync keeps the field current. Filter semantics are in
`backend/onyx/document_index/FILTER_SEMANTICS.md`.

### 4.4 The embedding-model swap state machine

Two state machines exist, and they interlock at the moment of promotion.

**Model generation status** (`IndexModelStatus` on `SearchSettings`):

```
        create_search_settings(status=FUTURE)
              |
   [PRESENT]-----------------reindex/backfill----------------->[FUTURE]
      ^                                                            |
      |                                    check_and_perform_index_swap
      |                                    (swap_index.py:_perform_index_swap)
      |                                                            |
      +---------------- update_search_settings_status -------------
      |  PRESENT -> PAST                    FUTURE -> PRESENT
      v
   [PAST]  (the old index; now subject to reclamation, below)
```

`create_search_settings` (`db/search_settings.py`) inserts the FUTURE row.
`check_and_perform_index_swap` (`db/swap_index.py`) decides *when* to swap, branching
on `switchover_type` (`INSTANT`, `REINDEX`, `ACTIVE_ONLY`) and on `use_port_flow`. With
`use_port_flow`, INSTANT swaps at once and the port backfills the live index
afterward. The other types wait on `_port_swap_ready` for the required cc-pairs.
Without `use_port_flow`, INSTANT swaps at once and deletes the cc-pairs' document
rows, REINDEX waits until every connector has a successful attempt on the new
settings, and ACTIVE_ONLY waits only on non-paused connectors. `_perform_index_swap` does the actual promotion:
`update_search_settings_status(current, PAST)`,
`update_search_settings_status(new, PRESENT)`, then calls
`verify_and_create_index_if_necessary` on the index from
`get_default_document_index(new_search_settings, None)` before returning.

**Reclaim status** (`IndexReclaimStatus` on the now-PAST `SearchSettings` row), driven
by a beat task, one step per tick, via the `advance_to_*` helpers in
`db/search_settings.py`:

```
PENDING --advance_to_soaking--> SOAKING --advance_to_deleting--> DELETING --advance_to_reclaimed--> RECLAIMED
   |                                |                                |
   +-------------- record_failure__no_commit (repeated failure) -----+---> BLOCKED
```

`set_reclaim_intent_on_current__no_commit` stamps `PENDING` on the current PRESENT row
at reindex-submit time (the future PAST). `advance_to_soaking__no_commit` anchors
`reclaim_stopped_reading_at` and only fires from `PENDING`, so it cannot be re-run to
extend the soak window. `advance_to_deleting__no_commit` only fires from `SOAKING`
(soak elapsed, new index confirmed healthy, verified in `db/search_settings.py` but the
exact soak-duration and health-check call sites were **not traced**; treat that gap as
unverified). `advance_to_reclaimed__no_commit` only fires from `DELETING`, and the PAST
row is kept forever as a durable record, not deleted, once RECLAIMED.
`mark_abandoned_future_for_reclaim__no_commit` jumps straight to `DELETING` for a
reverted or superseded FUTURE, skipping the soak, because that index was never on the
live read path. `record_failure__no_commit` parks a row in `BLOCKED` after
`max_attempts` failures; BLOCKED rows are excluded from
`fetch_reclaimable_past_settings` and need operator intervention.

### 4.5 The embedding model and reranker

`EmbeddingModel.from_db_model(search_settings, server_host, server_port)`
(`search_nlp_models.py`) materializes the embedder used for indexing and for
query-time embedding, pulling `model_name`, `normalize`, `query_prefix`,
`passage_prefix`, `api_key`, `provider_type`, `api_url`, `deployment_name`,
`reduced_dimension` straight off the `SearchSettings` row. Separate `server_host`
values are used depending on whether the call is from indexing or inference.

`RerankingModel` (`search_nlp_models.py`) is a fully implemented class (local
cross-encoder plus direct API paths for Cohere/Bedrock) with **no active call site**.
Its only instantiation in the codebase is inside
`warm_up_cross_encoder` (`search_nlp_models.py`), a function whose own docstring
comment reads `# No longer used`. See §9.

---

## 5. Contracts and invariants

1. **A write must target the index of the generation it belongs to.** Docprocessing
   passes the attempt's own `SearchSettings` to `get_default_document_index(..., None)`.
   `OpenSearchIndexPair.index` writes to the primary only, so a caller that passes the
   FUTURE settings as `secondary` does not get its chunks written there. The port
   backfill fills the FUTURE index.
2. **All chunk-permission filtering flows through `_get_search_filters`.** Nothing may
   query OpenSearch with a hand-built filter that bypasses
   `_get_acl_visibility_filter`; that is the only place ACL and public-doc visibility
   is enforced at the index layer. See [[access-control]].
3. **Hybrid normalization weights must sum to 1.0.** Enforced by an `assert` in
   `_get_hybrid_search_normalization_weights`; a weight change that forgets this
   crashes on the first call, not silently.
4. **Weight order must match subquery order.** The normalization pipeline associates
   weights with clauses positionally, with no other binding.
5. **A schema change needs a migration path for existing indices**, because
   `"dynamic": "strict"` means an unexpected field on write is a hard error, not a
   silent merge. Adding a field to `DocumentSchema.get_document_schema` without a
   corresponding index-mapping update breaks every index created before the change.
6. **`DocumentChunk`/`DocumentChunkWithoutVectors` field names must match the
   OpenSearch schema exactly.** They are two independent sources of truth for the same
   shape; nothing enforces this at the type level.
7. **The chunks of one document are never split across `index()` calls.** Backends may
   assume this when computing which trailing chunks to delete for a shortened
   document.
8. **The reclaim state machine only advances forward, one step at a time**, and each
   `advance_to_*` helper is a no-op unless the row is in the exact prior state. A
   caller that mutates `reclaim_status` directly instead of going through these
   helpers can desynchronize `reclaim_stopped_reading_at` from the actual state.
9. **`get_current_search_settings` returns the highest-id PRESENT row and raises
    only when none exists.** `swap_index.py:_perform_index_swap` commits the old
    row as PAST before it commits the new row as PRESENT. The transition briefly
    has no PRESENT row. Do not build code that assumes exactly one PRESENT row at
    every instant.

---

## 6. Relationships

**Depends on**
- [[indexing-pipeline]]: produces the `DocMetadataAwareIndexChunk` objects passed to
  `index()`, and drives `check_and_perform_index_swap` after successful runs.
- [[background-jobs]]: the reclaim beat task drives the `IndexReclaimStatus` state
  machine; the reindex port backfills a secondary index in the background.
- [[access-control]]: supplies the `access_control_list` and `public` values baked
  into every chunk, and the ACL semantics `_get_acl_visibility_filter` implements.
- [[multi-tenancy]]: `TenantState` and the `tenant_id` field/filter only exist when
  `MULTI_TENANT` is set; sharding defaults also change under
  `USING_AWS_MANAGED_OPENSEARCH` with `MULTI_TENANT`.

**Depended on by**
- [[internal-search]]: calls `hybrid_retrieval` / `keyword_retrieval` /
  `semantic_retrieval` / `id_based_retrieval` / `random_retrieval` through
  `get_default_document_index`, and owns query construction, result merging, and
  reranking orchestration above this layer.
- [[connectors]]: connector-scoped deletes and cc-pair resyncs call `Deletable.delete`
  and drive document-set/ACL updates through `Updatable.update`.
- [[core-chat-loop]]: search tools ultimately bottom out in this component's retrieval
  methods.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a chunk field | `opensearch/schema.py` mapping, `DocumentChunk`/`DocumentChunkWithoutVectors`, the writer in [[indexing-pipeline]], any query/filter that should read it, and a migration path for indices created before the change |
| changes hybrid weights or subqueries | run a retrieval-quality eval before shipping; the weights-sum-to-1.0 assert catches arithmetic mistakes but not quality regressions |
| adds a filter | `_get_search_filters` and every one of its private helper functions that builds one clause; the hybrid, keyword, semantic, and random query builders all call the same function, so a filter added there applies everywhere automatically, but a filter added ad hoc to just one query builder will not |
| changes `SearchSettings` | `create_search_settings`, `update_search_settings`, the reindex request models in `server/manage/search_settings.py`, and `EmbeddingModel.from_db_model` if the field feeds the embedder |
| touches the swap state machine (`IndexModelStatus` or `IndexReclaimStatus`) | `swap_index.py:_perform_index_swap`, every `advance_to_*` helper's prior-state guard, and the reclaim beat task; a broken guard can double-delete or skip the soak window |
| changes `get_default_document_index` or `OpenSearchIndexPair` fan-out rules | every caller, since most pass `None` as the secondary; a change to which calls reach the secondary affects the port backfill and swap-time deletes |

---

## 8. How to verify a change

### Tests

```bash
# Unit tests for OpenSearch client behavior (auth, TLS, batch flush)
cd backend && uv run pytest tests/unit/onyx/document_index -x
cd backend && uv run pytest tests/unit/server/metrics/test_opensearch_search_metrics.py -x

# External dependency unit tests (real OpenSearch, mocked elsewhere) -- prefer these
# for index/query behavior
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/document_index
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/opensearch
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/search_settings

# Integration tests for the swap/reindex admin flow
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/search_settings
```

See `backend/AGENTS.md` for the authoritative commands and required env.

### Manual reproduction: a query

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. Run a search that should hit both keyword and vector matches, and confirm results
   are ordered sensibly and every result respects your account's document
   permissions.
4. Check `backend/log/api_server_debug.log` for the OpenSearch query; if
   `OPENSEARCH_EXPLAIN_ENABLED` is set, the response body's `explain` section shows
   the per-clause score contribution.

### Manual reproduction: an embedding-model swap

1. In the admin panel, start a new embedding model under Search Settings.
2. Watch `GET /search-settings/reindex-progress` (or the admin UI) advance.
3. Confirm `GET /search-settings/get-current-search-settings` flips to the new model
   once `check_and_perform_index_swap` promotes it, and that search results reflect
   the new model immediately after.
4. If reclaim is enabled, watch the old `SearchSettings` row's `reclaim_status`
   progress through `PENDING -> SOAKING -> DELETING -> RECLAIMED` in the DB (see
   `backend/CLAUDE.md` for the `psql` connection command).

### What "working" looks like

- No documents missing from search results due to a filter bug or an incomplete
  port backfill during a swap.
- The old index's data is actually gone after `RECLAIMED`, and the row is never
  deleted.
- Hybrid search returns results that blend keyword and vector matches in the
  proportions the configured weights imply, not a pure keyword or pure vector
  ordering.

---

## 9. Footguns

- **The reranker looks load-bearing but is not.** `RerankingModel`
  (`search_nlp_models.py`) is fully built out with cloud-provider rerank calls,
  but its only call site is `warm_up_cross_encoder`, which its own comment marks
  `# No longer used`. Do not assume reranking runs in the live query path just
  because the class exists; verify with a fresh grep for `RerankingModel(` before
  relying on it.
- **`hybrid_alpha` is mostly a no-op inside the index.** It is used once, upstream in
  `search_runner.py`, to decide whether to skip embedding and call
  `keyword_retrieval` directly (`hybrid_alpha == 0.0`) or to pick a `QueryType` label
  that `OpenSearchDocumentIndex.hybrid_retrieval` receives and ignores (marked
  `# noqa: ARG002`). Do not expect tuning `hybrid_alpha` between 0 and 1 to change
  the actual OpenSearch query; it does not, except at the `0.0` boundary.
- **`OpenSearchIndexPair.index` writes to the primary only.** A caller that expects
  both generations to receive a write is wrong, and nothing errors. Only the port
  backfill fills the secondary. `delete` and `update` do reach both.
- **An OpenSearch under disk pressure fails as "Could not connect to a document
  index".** OpenSearch's disk watermarks block index creation at the high watermark
  and flip affected indices read-only at flood stage; the resulting error at the Onyx
  layer looks like a connectivity problem, not a disk problem. The dev/CI compose
  overlay sets `cluster.routing.allocation.disk.threshold_enabled=false`, so this
  failure mode does not apply to dev/CI stacks — only to deployments without that
  overlay. There, check `df` and cluster health before debugging the client code.
- **`"dynamic": "strict"` means a partially-migrated schema change breaks indexing
  outright**, not gradually. A chunk built with a new field against an index whose
  mapping has not been updated raises on `index()`, not on read.
- **The two schemas of a chunk are independently maintained.** `DocumentChunk`'s
  pydantic fields and `DocumentSchema.get_document_schema`'s mapping properties must
  be changed together by hand; nothing generates one from the other.

---

Cross-links: [[internal-search]], [[indexing-pipeline]], [[access-control]],
[[connectors]], [[background-jobs]], [[multi-tenancy]].
