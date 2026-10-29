# Document Index

> The OpenSearch index that stores document chunks with their vectors and
> metadata, with the query and filter builder, the metadata sync that pushes ACL
> and document-set changes into chunks, and the reindex that moves search to a
> new embedding model.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. Multi-tenant cloud adds a tenant field and filter, and uses
different shard settings on AWS-managed OpenSearch.

## User experience

- **An end user's search** matches and sees only the chunks this index lets
  through. When a document's permissions or document sets change, search
  reflects it after the next metadata sync, seconds to minutes later.
- **An admin changes the embedding model** on the Index Settings page. Onyx
  builds a second index in the background with the new model, while the old
  index keeps serving search. A progress view shows the reindex and its
  errors. When the new index is ready, live search switches to it without a
  click. Rankings can shift after the switch, because the new model scores
  chunks differently. The admin can cancel a reindex in progress. A second
  reindex is refused with a conflict until the first one ends. A port unit that
  stops on failure waits for the admin to resume it, and the switch waits too.
- **Model choice.** For a provider whose model list Onyx owns, only models that
  the registry marks `SELECTABLE` can be a new target. LiteLLM, Azure, Bifrost
  and OpenAI-compatible providers take free-form model names
  (`server/manage/search_settings.py:_REGISTRY_ONLY_CLOUD_PROVIDERS`). A
  `LEGACY` model is a valid target only for a same-model reindex of the PRESENT
  model. Before Onyx saves a selectable cloud model, or a Bifrost or
  OpenAI-compatible model, it embeds a test string and rejects a failed call or
  a wrong dimension.
- **A full admin sees resource warnings** when the OpenSearch cluster is short
  of disk, JVM heap or vector memory: one popup per 24 hours, and a banner on
  admin pages.
- **An operator** sees the old index deleted about a day after a switch, once
  the new index is healthy. A reclaim that fails repeatedly stops and needs a
  person.

## Scope

This component owns the `DocumentIndex` interface and its OpenSearch
implementation, the chunk schema and the hybrid query. It owns the
`SearchSettings` generations (PAST, PRESENT, FUTURE), the reindex port, the
swap and the reclaim of old indices. It owns the metadata sync: the `needs_sync`
predicate and `document_index_metadata_sync_task`. Their module keeps the name
`vespa`; the backend AGENTS file explains why. It owns the embedding model registry,
how the model server loads a self-hosted model, the cluster resource health
check and the `cc_pair_ids` backfill.

Its neighbours own:
- [[indexing-pipeline]]: building the chunks that cross `index()`.
- [[internal-search]]: what to search, query expansion, and merging results.
- [[access-control]]: the ACL values in each chunk, the user's ACL filter, and
  the cc-pair access filter modes.
- [[permission-sync]]: the Postgres permission changes that the metadata sync
  pushes into the index.
- [[background-jobs]]: the workers and beat entries that run these tasks, and
  the document cleanup task of pruning and connector deletion.

## Architecture

**The interface.** `document_index/interfaces.py:DocumentIndex` combines small
capability classes (`Indexable`, `Updatable`, `Deletable`, `HybridCapable` and
others), so a caller can depend on one capability.
`document_index/opensearch/opensearch_document_index.py:OpenSearchIndexPair`
wraps a primary and an optional secondary index. `index` and retrieval use the
primary only. `update`, `delete` and index creation reach both.
`DISABLE_VECTOR_DB` makes `document_index/factory.py:get_default_document_index`
return `DisabledDocumentIndex`, which raises on use.

**The factory.** Most callers pass `None` as the secondary and get one index for
the generation they work on. Callers that update or delete existing chunks pass
the FUTURE settings as the secondary, so both generations stay in step. Examples
are the metadata sync, the document cleanup task, and user-file updates and
deletes. Search the callers of `get_default_document_index` for the current set.
`primary_backfill_in_progress` marks a PRESENT index that an INSTANT reindex
promoted while the port still fills it.

**A hybrid query.** `document_index/opensearch/search.py:DocumentQuery` builds
one OpenSearch `hybrid` query with a vector subquery and a keyword subquery. A
search pipeline normalizes and combines their scores, not application code
(`get_normalization_pipeline_name_and_config`). Every retrieval query compiles
its filters in one place, `DocumentQuery._get_search_filters`: ACL, the cc-pair
access filter, sources, tags, document sets, projects, personas, time ranges,
hierarchy nodes and tenant. `document_index/opensearch/README.md` explains why
time decay and boosts cannot be applied inside the hybrid query.

**The metadata sync.** A chunk stores a copy of its document's ACL, document
sets, boost, hidden flag and cc-pair IDs. Postgres is the source of truth.

```
writer changes a Document's metadata in Postgres, bumps last_modified
beat: check_for_vespa_sync_task                 tasks/vespa/tasks.py
  try_generate_stale_document_sync_tasks        tasks/vespa/document_sync.py
    last_modified > last_synced OR last_synced IS NULL,
    or secondary_only_sync_pending
    -> one DOCUMENT_INDEX_METADATA_SYNC_TASK per document, up to
       DOCUMENT_INDEX_SYNC_MAX_TASKS, behind one tenant fence
document_index_metadata_sync_task               vespa_metadata_sync queue (light worker)
  read Document, get_access_for_document, document sets -> MetadataUpdateRequest
  OpenSearchIndexPair.update (primary and secondary), no re-embed
  mark_document_as_synced(synced_as_of=last_modified read in step 1)
```

The same beat task also syncs document sets and user groups through their own
fenced tasksets.

**A reindex.**

```
set_new_search_settings        server/manage/search_settings.py
  create FUTURE row (use_port_flow), mark PRESENT for reclaim, seed poll cursors
check_for_port / run_port_attempt          tasks/port/tasks.py
  copy PRESENT chunks to FUTURE, re-embedded (indexing/port_reembed.py), create-only
  all connector ports SUCCESS -> finalizing  db/port_attempt.py:reindex_finalizing
check_and_perform_index_swap               db/swap_index.py, run by check_for_indexing
  INSTANT: swap at once, the port keeps filling the live index
  REINDEX / ACTIVE_ONLY: swap when _port_swap_ready
_perform_index_swap: PRESENT -> PAST, FUTURE -> PRESENT, one commit
check_for_old_index_reclaim                tasks/index_reclaim/tasks.py
  PENDING -> SOAKING -> DELETING -> RECLAIMED (row kept), or BLOCKED
```

The reindex never fetches sources again. It copies and re-embeds stored chunks
(`document_index/opensearch/port_copy.py`), and connectors keep indexing new
changes into both generations. Once every connector port succeeds, the reindex
is finalizing. The swap then waits while any FUTURE index attempt of a required
pair runs (`db/swap_index.py:_no_writer_left_in_flight`).
[[indexing-pipeline#future-attempts-first]] keeps those attempts from waiting
behind PRESENT refreshes. Reclaim waits `OLD_INDEX_RETENTION_HOURS` in SOAKING,
then requires the new index to be not red and to answer a count query
(`background/celery/tasks/index_reclaim/tasks.py:_new_index_can_serve`) before
it deletes the old one.

## Contracts and traps

1. `bump-last-modified` **A per-document metadata change must bump
   `last_modified`.** A writer that changes a document's ACL inputs, boost,
   hidden state or cc-pair links in Postgres must bump `Document.last_modified`
   (`backend/onyx/db/document.py:mark_document_as_modified__no_commit` or
   `mark_cc_pair_documents_for_sync__no_commit`). Without it, the index keeps
   the old value and nothing reports an error. A document set or user group
   change syncs through its own taskset, keyed on the set's or group's
   `is_up_to_date` flag.
2. `sync-stamps-watermark` **Stamp the watermark, not the clock.**
   `backend/onyx/db/document.py:mark_document_as_synced` sets `last_synced` to the
   `last_modified` read before the index write. A document changed during the
   write stays stale and syncs again. Using `now()` loses that change.
3. `index-writes-primary-only` **A pair's `index` writes the primary only.**
   `document_index/opensearch/opensearch_document_index.py:OpenSearchIndexPair.index`
   ignores the secondary, so a caller that passes FUTURE as secondary does not
   get its chunks in FUTURE. Only the port fills it.
4. `port-orphan-record` **The port writes create-only, so a delete during a port
   needs an orphan record.** A copy can recreate a document that was deleted
   after the copy read it. The cleanup task records a port orphan candidate
   before it deletes
   (`background/celery/tasks/shared/tasks.py:document_by_cc_pair_cleanup_task`),
   and the port sweeps it.
5. `missing-secondary-defers-sync` **A sync to a document the port has not
   copied is deferred, not failed.** This applies to FUTURE, and to a PRESENT
   that an INSTANT reindex promoted while its port still runs.
   `document_index/opensearch/opensearch_document_index.py:OpenSearchIndexPair.update`
   raises `SecondaryIndexDocumentMissingError` in both cases. The sync then sets
   `secondary_only_sync_pending`, and the swap waits for those documents to
   drain. Clearing `needs_sync` instead lets the
   port install a stale ACL. A document with no indexable cc-pair
   (`backend/onyx/db/document.py:document_has_indexable_cc_pair`) is marked
   synced instead: the port never copies it, so its flag would hold the swap
   for ever.
6. `filters-in-one-place` **All index-side filtering goes through one
   builder.**
   `document_index/opensearch/search.py:DocumentQuery._get_search_filters` is
   the only place ACL and public visibility apply at the index. A query with a
   filter built by hand bypasses permissions. It raises `ValueError` when the ACL has more than
   `MAX_NUM_TERMS_ALLOWED_IN_TERMS_QUERY` (65,536) entries. The tenant clause,
   and the `tenant_id` field in the mapping, exist only when
   `tenant_state.multitenant` is true. Maintenance queries such as
   `DocumentQuery.delete_port_written_chunks_query` and `set_cc_pair_ids_query`
   build their own tenant clause. Keep them in step with `_get_search_filters`.
7. `hybrid-weights-positional` **The hybrid weights are positional.** The
   pipeline matches weights to subqueries by order, and
   `document_index/opensearch/search.py:_get_hybrid_search_normalization_weights`
   asserts they sum to 1. Change the subqueries and the weights together, and
   run a retrieval eval.
8. `strict-mapping` **The mapping is strict.**
   `document_index/opensearch/schema.py:DocumentSchema.get_document_schema`
   sets `"dynamic": "strict"`, so a chunk with an unmapped field fails on
   write. The pydantic `DocumentChunk` and the
   mapping are kept in step by hand. Index setup
   (`document_index/opensearch/opensearch_document_index.py:OpenSearchDocumentIndex.verify_and_create_index_if_necessary`,
   run by `setup.py:setup_document_index`) adds a new field to an existing
   index, but a changed field type fails there and needs a reindex. Chunks
   written before the change have no value for the new field.
9. `swap-one-commit` **Swap both statuses in one commit.**
   `db/swap_index.py:_perform_index_swap` uses
   `db/search_settings.py:update_search_settings_status__no_commit` twice and
   one commit. Two commits leave a moment with no PRESENT row, and
   `get_current_search_settings` raises.
10. `reclaim-forward-only` **Reclaim moves forward one step at a time.** Each
    `advance_to_*` helper in `db/search_settings.py` acts only from the exact
    prior status. Do not set `reclaim_status` outside those helpers. An
    abandoned FUTURE goes straight to DELETING
    (`db/search_settings.py:mark_abandoned_future_for_reclaim__no_commit`),
    because it never served search.
11. `registry-entries-immutable` **Do not change a model that indices use.** The
    dimension, prefixes and normalization of a registry entry are baked into
    every vector. Add a new entry instead.
    `web/src/lib/searchSettings/constants.ts` must match the registry
    (`backend/tests/unit/shared_configs/test_web_embedding_model_registry_parity.py`).
12. `contextual-rag-validator` **Contextual-RAG settings pass one validator, and
    the default flow follows PRESENT.**
    `server/manage/search_settings.py:validate_contextual_rag_model` rejects a
    model without the CHAT flow type, and rejects enabling the feature with no
    model and no tenant default. The reindex endpoint and
    `update_saved_search_settings` both call it. The default CONTEXTUAL_RAG LLM
    flow must match PRESENT:
    `server/manage/search_settings.py:_sync_default_contextual_model` resets it
    after an in-place change, and `db/swap_index.py:_perform_index_swap`
    resets it after a swap. A new writer of PRESENT contextual-RAG fields must
    do the same, or [[llm-providers]] shows a default that indexing does not use. The in-place
    endpoint refuses to turn the feature off while the `ENABLE_CONTEXTUAL_RAG`
    env flag is set ([[indexing-pipeline]]).

## Decisions

- **Reindex copies stored chunks instead of fetching sources again.** A full
  refetch is slow and fails when a connector is broken. The port re-embeds what
  PRESENT holds, and the reindex endpoint creates every FUTURE row with
  `use_port_flow`. The non-port branches of `check_and_perform_index_swap` serve
  only rows without the flag.
- **The old index is kept for a soak period.** It allows a rollback while the new
  model is judged, and the PAST row stays forever as a record.

## Known issues

- **`hybrid_alpha` is almost a no-op.** `context/search/retrieval/search_runner.py`
  maps it to a `QueryType` that `OpenSearchDocumentIndex.hybrid_retrieval`
  ignores. Only `hybrid_alpha == 0.0` changes behaviour: it skips embedding and
  runs a keyword query.
- **`RerankingModel` is dead code.** Its only constructor call is in
  `natural_language_processing/search_nlp_models.py:warm_up_cross_encoder`,
  which a comment marks unused. Search runs no reranker ([[internal-search]]).
- **Disk pressure looks like a connection error.** At the OpenSearch high
  watermark, index creation fails, and startup reports "Could not connect to a
  document index". Check disk and cluster health first. The dev compose file
  turns the disk threshold off, so dev stacks do not show this.

## Dependencies

- [[indexing-pipeline]]: the chunks and the counts of chunks per document.
- [[access-control]]: `get_access_for_document`, the ACL filter values, and the
  cc-pair access mode.
- [[background-jobs]]: the beat entries and the light worker that run the sync,
  port and reclaim.
- [[multi-tenancy]]: the tenant field, the tenant filter, and tenant-scoped
  fences.

## Recipes

- `chunk-field` **A chunk field.** Copy an existing optional field, such as the
  hierarchy ancestors, through `document_index/opensearch/schema.py`: add it to
  the mapping in `DocumentSchema.get_document_schema` and to `DocumentChunk`
  ([[#strict-mapping]]). If a metadata change can alter it, add it to
  `MetadataUpdateRequest` and the metadata sync.
- `add-filter` **A filter.** Copy a clause builder under `_get_search_filters`,
  such as the document set filter, so every query type gets it
  ([[#filters-in-one-place]]). Add the field to `IndexFilters`.
- `embedding-model` **An embedding model.** Add a `SELECTABLE` entry to the
  registry in `backend/shared_configs/embedding_models.py` and to
  `web/src/lib/searchSettings/constants.ts`. Copy an entry of the same provider.
  A new default also needs the model-server image to bake it.
- `investigate-ranking` **Investigate a ranking.** Set
  `OPENSEARCH_EXPLAIN_ENABLED=true` on the API server. Each hit of a hybrid
  query then carries OpenSearch's score breakdown in `SearchHit.explanation`;
  read it at the breakpoint that `OpenSearchDocumentIndex.hybrid_retrieval`
  marks. It slows queries; turn it off after.
- `investigate-stale-acl` **Investigate a stale ACL in search.** Compare
  `last_modified` and `last_synced` on the `document` row. `last_synced` behind
  means the sync has not run or failed; check the light worker. Equal values
  with a wrong chunk mean the writer did not bump `last_modified`
  ([[#bump-last-modified]]).
- `reproduce-reindex` **Reproduce a reindex.** Start a reindex from the Index
  Settings page. Search must keep working during the port. After the swap, the
  old `SearchSettings` row moves to RECLAIMED after the soak, and the row stays.

## Verification

- Unit tests: `backend/tests/unit/onyx/document_index/`.
- External dependency tests: `backend/tests/external_dependency_unit/document_index/`,
  `backend/tests/external_dependency_unit/opensearch/`,
  `backend/tests/external_dependency_unit/search_settings/`, and the sync tests
  in `backend/tests/external_dependency_unit/celery/`.
- Integration tests: `backend/tests/integration/tests/search_settings/` and
  `backend/tests/integration/tests/reindex_port/`.
