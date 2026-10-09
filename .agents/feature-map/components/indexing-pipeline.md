# Indexing Pipeline

> Turns a fetched document into indexed chunks. A two-phase Celery flow (docfetching,
> then docprocessing) chunks, embeds, and writes each document to the index of the
> attempt's own `SearchSettings`, then tracks the run as an `IndexAttempt`.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** indexing
**Edition:** CE, with EE-relevant usage-limit and hook checks inline (`USAGE_LIMITS_ENABLED`,
`onyx.hooks.points.document_ingestion`, `onyx.hooks.points.document_push`)
**Owns:**
`backend/onyx/indexing/` (`indexing_pipeline.py`, `chunker.py`, `chunking/`, `embedder.py`,
`models.py`, `vector_db_insertion.py`, `chunk_batch_store.py`, `persistent_indexing.py`,
`document_push.py`, `port_reembed.py`, `indexing_heartbeat.py`, `adapters/`),
`backend/onyx/background/celery/tasks/docfetching/`, `docprocessing/`, `pruning/`,
`connector_deletion/` (the document-removal half only), `index_reclaim/`, `port/`,
`backend/onyx/background/indexing/` (`run_docfetching.py`, `checkpointing_utils.py`,
`index_attempt_utils.py`, `job_client.py`, `memory_tracer.py`),
`backend/onyx/db/index_attempt.py`, `index_attempt_metrics.py`, `indexing_coordination.py`

**Does not own:** how a connector talks to a source and yields `Document` objects
([[connectors]]); the cc-pair/credential model, scheduling triggers, and admin
connect flow ([[cc-pairs-and-credentials]]); the `DocumentIndex` interface, the
OpenSearch schema, hybrid retrieval, and the embedding-model swap state
machine ([[document-index]], read first, this document does not repeat its §4.4
swap state machine); ACL computation ([[access-control]]); external permission
sync ([[permission-sync]]); user file upload/project storage
([[file-store-and-user-files]]); the generic Celery worker/queue topology
([[background-jobs]]); tenant scoping mechanics ([[multi-tenancy]]); LLM provider
resolution ([[llm-providers]]).

---

## 1. What the user experiences

An admin connects a source (Slack, Confluence, Google Drive, and so on) and Onyx
schedules an indexing run automatically. On the connector's status page the admin
watches document counts climb as batches complete, sees the run finish with a
document and chunk count, and can drill into individual failures with a document
link and an error message. If the connector supports incremental pulls, later runs
only touch documents that changed. A run that dies mid-flight (a worker restart, a
deploy) can resume from its checkpoint on the next scheduled attempt when the
connector supports checkpointing. Other connectors restart extraction. The admin
sees the interrupted run in history and a fresh attempt picks up automatically.

For an active cc-pair whose connector has `prune_freq` set
(`pruning/tasks.py:_is_pruning_due`), the next scheduled prune removes a vanished
source document from search results. Deleting a connector entirely, or removing a cc-pair, removes every
document that connector uniquely owned and clears the reference from documents
still held by another connector.

Uploading a file directly (Chat attachments, Projects) goes through the same
chunk/embed/write machinery but skips the connector-fetch phase entirely; the file
is already local.

---

## 2. Surfaces

### Celery tasks (no HTTP surface; driven by Celery beat, see `beat_schedule.py`)

| Task | Queue | Trigger | Notes |
|---|---|---|---|
| `CHECK_FOR_INDEXING` (`check_for_indexing`, `docprocessing/tasks.py`) | `celery` (primary) | beat, 15s | Kicks off docfetching for cc-pairs due for indexing; also monitors active attempts for completion and validates heartbeats. |
| `CONNECTOR_DOC_FETCHING_TASK` (`docfetching_proxy_task`, `docfetching/tasks.py`) | `connector_doc_fetching` | sent by `check_for_indexing` via `try_creating_docfetching_task` | The watchdog. Spawns `docfetching_task` in a subprocess and monitors it. |
| `DOCPROCESSING_TASK` (`docprocessing_task`, `docprocessing/tasks.py`) | `docprocessing` | sent by docfetching, once per document batch | Chunks, embeds, writes one batch. |
| `CHECK_FOR_CHECKPOINT_CLEANUP` / `CLEANUP_CHECKPOINT` | `celery` / `checkpoint_cleanup` | beat, 1h | Deletes checkpoint blobs older than `NUM_DAYS_TO_KEEP_CHECKPOINTS`. |
| `CHECK_FOR_INDEX_ATTEMPT_CLEANUP` / `CLEANUP_INDEX_ATTEMPT` | `celery` / `index_attempt_cleanup` | beat, 30m | Deletes `IndexAttempt` rows older than `NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS`, keeping the last `NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP` per cc-pair/search-settings pair. |
| `CHECK_FOR_PRUNING` / `CONNECTOR_PRUNING_GENERATOR_TASK` (`pruning/tasks.py`) | `celery` / `connector_pruning` | beat, 20s | Diffs the source's live doc-ID list against Postgres and queues per-doc cleanup for the difference. |
| `CHECK_FOR_CONNECTOR_DELETION` (`connector_deletion/tasks.py`) | `celery` / `connector_deletion` | beat, 20s | Fans out `DOCUMENT_BY_CC_PAIR_CLEANUP_TASK` for every document tied to a cc-pair marked `DELETING`. Blocks while indexing, pruning, or a port attempt is active on that cc-pair. |
| `CHECK_FOR_OLD_INDEX_RECLAIM` / `RUN_OLD_INDEX_RECLAIM` (`index_reclaim/tasks.py`) | `celery` | beat, 30m | Advances the `IndexReclaimStatus` state machine on PAST search-settings rows. Owned in detail by [[document-index]] §4.4; this component only writes the FUTURE-index docs the reclaim eventually deletes. |
| `CHECK_FOR_PORT` / `RUN_PORT_ATTEMPT` (`port/tasks.py`) | `celery` / `port` | beat, 30s | Backfills a secondary index by re-embedding stored PRESENT chunks (`port_reembed.py`), without re-fetching the source. See §4.6. |

### Environment configuration (`backend/onyx/configs/app_configs.py` unless noted)

| Variable | Default | Effect |
|---|---|---|
| `INDEX_BATCH_SIZE` | 16 | Documents per connector-fetch batch, and thus per `docprocessing` task. |
| `MAX_CHUNKS_PER_DOC_BATCH` | 1000 | Sub-batch size for the embed step inside one docprocessing task; see §4.4. |
| `MAX_DOCUMENT_CHARS` | set | A document above this char count is skipped with a `ConnectorFailure`, not chunked. |
| `PERSISTENT_INDEXING` | see configs | When true, an unhandled docprocessing batch exception is converted into per-doc failures and the attempt can finish (`COMPLETED_WITH_ERRORS`) instead of `FAILED`. Unhandled connector-generator exceptions in docfetching still mark the attempt `FAILED`. See `indexing/persistent_indexing.py` and §4.5. |
| `ENABLE_CONTEXTUAL_RAG` | see configs | Contextual RAG is on when this global flag or `SearchSettings.enable_contextual_rag` is true. A per-model false does not turn off a true global flag (`indexing_pipeline.py`). |
| `USE_DOCUMENT_SUMMARY` / `USE_CHUNK_SUMMARY` (`onyx/configs/app_configs.py`) | see configs | Which contextual-RAG LLM calls run; at least one must be true for `enable_contextual_rag`. |
| `CONTEXTUAL_RAG_LLM_TIMEOUT` (`chat_configs.py`) | see configs | Timeout for each contextual-RAG LLM call. |
| `MINI_CHUNK_SIZE`, `LARGE_CHUNK_RATIO`, `BLURB_SIZE`, `SKIP_METADATA_IN_CHUNK` | see configs | Multipass/large-chunk and blurb/metadata chunking knobs, `chunker.py`. |
| `STRICT_CHUNK_TOKEN_LIMIT` (`shared_configs/configs.py`) | see configs | Forces an oversized split chunk to be re-split at token boundaries in `text_section_chunker.py`. |
| `INDEXING_WORKER_HEARTBEAT_INTERVAL` (`configs/constants.py`) | see configs | Cadence of the DB heartbeat counter increment (§4.7). |
| `INDEXING_WORKER_MEMORY_LIMIT_MB` | see configs | Docfetching watchdog kills the subprocess if RSS exceeds this. |
| `CELERY_INDEXING_LOCK_TIMEOUT` | see configs | TTL of the cross-batch Redis lock, scoped to one connector pair and search settings (§4.5). |
| `NUM_DAYS_TO_KEEP_CHECKPOINTS`, `NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS` | see configs | Retention windows for the two cleanup beat tasks. |
| `DOCUMENT_PUSH_ENDPOINT_URL`, `DOCUMENT_PUSH_API_KEY`, `DOCUMENT_PUSH_TIMEOUT_SECONDS` | unset | Config-driven external sink; see §4.4 and `document_push.py`. Single-tenant only. |
| `CONNECTOR_CHECKS_ENABLED` | false | When true, a cc-pair's first index attempt waits for its required capability checks (§4.1). Pair it with `NEXT_PUBLIC_CONNECTOR_CHECKS_CARD_ENABLED`. |

---

## 3. Data model

### `IndexAttempt` (`onyx/db/models.py:IndexAttempt`)

One row per run of the pipeline for one cc-pair against one `SearchSettings`
generation. Key columns: `status` (`IndexingStatus`), `from_beginning`,
`checkpoint_pointer` (a file-store key, see §4.2), `total_batches` /
`completed_batches` (set by docfetching / incremented by docprocessing, §4.5),
`total_docs_indexed`, `new_docs_indexed`, `total_chunks`, `poll_range_start` /
`poll_range_end`, `heartbeat_counter` / `last_heartbeat_value` /
`last_heartbeat_time` (§4.7), `cancellation_requested`, `celery_task_id`,
`targeted_reindex_job_id` (non-null only for a synthetic reindex-triggered
attempt), `is_synthetic_seed` (marks the port flow's synthetic FUTURE poll-cursor
seed, not a real connector run).

### `IndexAttemptError` (`onyx/db/index_attempt.py:create_index_attempt_error`)

One row per failed document or entity within an attempt. Carries `document_id` or
`entity_id`, the failure message, and `is_resolved` (flipped when a later
successful index of the same document clears the error;
`_resolve_indexing_document_errors` and `_resolve_indexing_entity_errors`).

### `IndexAttemptStageMetric` (`onyx/db/models.py`, written via `onyx/db/index_attempt_metrics.py`)

Per-stage timing aggregates keyed by `(index_attempt_id, stage)`. `IndexAttemptStage`
(`onyx/db/index_attempt_metrics_models.py`) enumerates every timed stage across both
phases, in pipeline order: docfetching stages (`CONNECTOR_VALIDATION` through
`DOC_BATCH_ENQUEUE`) then docprocessing stages (`QUEUE_WAIT` through `GC_COLLECT`),
plus the aggregate `BATCH_TOTAL` and the derived, never-written
`BATCH_UNACCOUNTED`. `StageScope` marks each as `ATTEMPT_LEVEL` (one event) or
`BATCH_LEVEL` (many, per docprocessing task).

### `Document`, `DocumentByConnectorCredentialPair`, `Tag` (`onyx/db/models.py`, `onyx/db/document.py`, `onyx/db/tag.py`)

`Document` is the durable Postgres row per source document: `content_hash` (used by
the dedup gate, §4.3), `doc_updated_at`, `chunk_count`, `boost`, `file_id` (for a
staged/promoted blob), `parent_hierarchy_node_id`. `DocumentByConnectorCredentialPair`
is the many-to-many join that lets one document be owned by more than one cc-pair;
pruning and deletion only fully remove a document when its connector count drops to
zero (`get_document_connector_count`, in `onyx/background/celery/tasks/shared/tasks.py`).
`Tag` rows hold connector-supplied metadata key/values, upserted per document by
`onyx.db.tag:upsert_document_tags`.

### Chunk schema

Owned by [[document-index]]. This component produces the chunk objects
(`DocAwareChunk` -> `IndexChunk` -> `DocMetadataAwareIndexChunk`, all in
`onyx/indexing/models.py`) that cross the `DocumentIndex.index()` boundary; it does
not define the OpenSearch mapping those objects must match.

### Redis / cache

| Key family | Owner | Meaning |
|---|---|---|
| `RedisConnector(tenant_id, cc_pair_id).stop` | `redis_connector.py` | Fence checked by docfetching/docprocessing callbacks (`IndexingCallback.should_stop`) and by the watchdog before spawning. |
| `RedisConnector(...).delete` | `redis_connector.py` | Fence + taskset for connector deletion (§4.8). |
| `RedisConnector(...).prune` | `redis_connector_prune.py` | Fence + taskset for a pruning run (§4.8). |
| `RedisDocprocessing(index_attempt_id, redis_client)` | `redis_docprocessing.py` | Per-attempt `pending`/`in_flight` batch counters, incremented on enqueue and consulted by the heartbeat-staleness check (§4.7); `cleanup()` on terminal status. |
| `redis_connector.db_lock_key(search_settings_id)` | `docprocessing/tasks.py` | Cross-batch lock serializing `IndexingCoordination.update_batch_completion_and_docs` writes. The key is per `cc_pair_id` and `search_settings_id`, so it is wider than one attempt (§4.5). |

---

## 4. How it works

### 4.1 The two-phase split, end to end

```
 beat: check_for_indexing (15s)
   |
   v
 docfetching_proxy_task  [queue: connector_doc_fetching]  (watchdog, primary/docfetching worker)
   |  spawns subprocess -> docfetching_task -> run_docfetching_entrypoint
   |
   |  for each connector-yielded batch of Documents:
   |    1. strip_null_characters, resolve hierarchy parent ids
   |    2. batch_storage.store_batch(batch_num, docs)     -- FileStore, DocumentBatchStorage
   |    3. save_checkpoint(...)                            -- FileStore, connector's ConnectorCheckpoint
   |    4. app.send_task(DOCPROCESSING_TASK, batch_num, ...)
   |
   v
 docprocessing_task  [queue: docprocessing]  (docprocessing worker, one task per batch)
   |
   |  storage.get_batch(batch_num)                          -- load staged Documents
   |  index_doc_batch_prepare(...)                           -- upsert Document/Tag rows, dedup gate
   |  chunker.chunk(...)                                     -- DocAwareChunk list
   |  [optional] add_contextual_summaries(...)               -- LLM doc/chunk context
   |  embed_and_stream(...)                                  -- IndexChunk, spilled to local disk (ChunkBatchStore)
   |  adapter.lock_context(...)                               -- per-document Postgres row lock
   |    enricher.enrich_chunk(...)                            -- ACL, doc sets, boost, cc_pair_ids -> DocMetadataAwareIndexChunk
   |    write_chunks_to_vector_db_with_backoff(...)  x N      -- once, to the index of the attempt's SearchSettings
   |    adapter.post_index(...)                                -- chunk counts, indexed timestamps
   |  IndexingCoordination.update_batch_completion_and_docs    -- cross-batch Redis-locked counter update
   |
   v
 check_for_indexing (next tick): monitor_indexing_attempt_progress
   -> check_indexing_completion  (completed_batches >= total_batches)
   -> mark_attempt_succeeded / mark_attempt_partially_succeeded
```

### 4.2 Docfetching: fetch, stage, checkpoint

`run_docfetching_entrypoint` (`background/indexing/run_docfetching.py`) transitions
the attempt to `IN_PROGRESS` (`transition_attempt_to_in_progress`, row-locked, only
legal from `NOT_STARTED`), reaps orphaned STAGING files from a crashed prior attempt
on the same cc-pair (`file_store/staging.py:reap_prior_attempt_staged_files`), then
calls `connector_document_extraction`.

That function computes the poll window (`window_start`/`window_end`), decides
whether to resume from a checkpoint or start clean
(`get_latest_valid_checkpoint`, §4.6), and drives the connector's generator
(`ConnectorRunner.run(checkpoint)`, [[connectors]]) inside `_timed_connector_runs`,
which records one `CONNECTOR_FETCH` timing event per yielded batch. For every
yielded `(document_batch, hierarchy_node_batch, failure, next_checkpoint)`:

- a connector-level `failure` becomes an `IndexAttemptError`
  (`create_index_attempt_error`) and counts toward the failure-ratio threshold
  (`_check_failure_threshold`, disabled entirely when `PERSISTENT_INDEXING` is set);
- hierarchy nodes are persisted and cached in Redis
  (`cache_and_upsert_hierarchy_nodes`) so a document's ancestor path can be resolved
  without a DB hit during docprocessing enrichment;
- the document batch, after `strip_null_characters` and hierarchy-parent
  resolution, is written to **`DocumentBatchStorage`**
  (`onyx/file_store/document_batch_storage.py`, backed by the FileStore/S3
  abstraction, not Postgres) via `batch_storage.store_batch(batch_num, docs)`;
- a `docprocessing` task is enqueued with `{index_attempt_id, cc_pair_id,
  tenant_id, batch_num, enqueue_time_ms}` (`app.send_task(OnyxCeleryTask.DOCPROCESSING_TASK, ...)`),
  and `RedisDocprocessing.incr_pending()` bumps the per-attempt pending counter used
  by the heartbeat-staleness check (§4.7);
- the connector's own checkpoint object is serialized to the FileStore
  (`checkpointing_utils.py:save_checkpoint`) and `IndexAttempt.checkpoint_pointer`
  is updated to point at it.

**First-attempt hold.** `try_creating_docfetching_task` creates a cc-pair's first
`IndexAttempt` as usual. When `get_first_indexing_hold`
(`connectors/capability_checks/indexing_hold.py`) returns a hold, it creates the
attempt without a Celery task id and sends no docfetching task. A hold applies when
a capability-check run is in flight, a run failed to run, or a required and
applicable check `FAILED`. `CONNECTOR_CHECKS_ENABLED` off, a pair with a dispatched
attempt, and a source with no named checks never hold. Each `check_for_indexing` beat
calls `try_dispatching_waiting_attempt`. It sends the task once no hold applies. See
[[connectors]] §4.8.

When the connector's checkpoint reports no more work, docfetching calls
`IndexingCoordination.set_total_batches`, which is the signal `check_for_indexing`
polls to know extraction is done.

**Correction to a common assumption:** the data that crosses from docfetching to
docprocessing is `DocumentBatchStorage` (file-store-backed), not
`onyx/indexing/chunk_batch_store.py`. `ChunkBatchStore` is a different, narrower
mechanism entirely internal to one docprocessing task: it spills *embedded* chunks
to a local temp directory between the embed step and the vector-db-write step of a
single batch (§4.4), and is torn down when that task's `with` block exits. It never
crosses a process or task boundary.

### 4.3 Docprocessing: prepare and dedup

`docprocessing_task` starts a DB heartbeat thread (`docprocessing/heartbeat.py:start_heartbeat`,
§4.7), loads the staged batch (`storage.get_batch(batch_num)`), and opens a
short-lived session to resolve the embedder, the document index for the attempt's
`SearchSettings` (`document_index.factory:get_default_document_index`), and the `IndexAttemptMetadata`
for this batch, then closes that session before the slow work begins.

`run_indexing_pipeline` (`indexing_pipeline.py`) resolves which `SearchSettings`
generation applies (FUTURE if one is `IndexModelStatus.FUTURE`, else PRESENT),
builds a `Chunker` sized to that generation's multipass/contextual-RAG config, and
calls `index_doc_batch`, which:

1. `filter_documents` drops documents with no title and no content, or over
   `MAX_DOCUMENT_CHARS`.
2. `_apply_document_ingestion_hook` runs the EE `DOCUMENT_INGESTION` hook, which can
   rewrite a document's sections or drop it (`hooks/points/document_ingestion.py`).
3. `adapter.prepare` -> `index_doc_batch_prepare` -> `get_docs_to_update`: a
   **two-gate dedup**. Gate 1 (timestamp) skips a document whose `doc_updated_at`
   hasn't advanced past what's stored, with no hashing. Gate 2 (content hash)
   applies only when the timestamp hasn't advanced; it's skipped for a FUTURE/port
   write (`index_to_secondary=True`) so the FUTURE build doesn't cross-suppress
   against the PRESENT-only hash. Docprocessing always passes
   `ignore_time_skip=True` (the connector already filtered by recency at fetch
   time), so only gate 2 applies here in practice.
4. Documents that pass the gate are upserted (`upsert_documents`, `upsert_document_tags`),
   linked to the cc-pair (`upsert_document_by_connector_credential_pair`), and
   linked to their hierarchy node.

### 4.4 Chunking, embedding, and writing

**Chunking** (`chunker.py:Chunker.chunk` -> `chunking/document_chunker.py:DocumentChunker`).
A document's `processed_sections` (connector-level `Section`/`TextSection`/
`ImageSection`/`TabularSection` from `onyx.connectors.models`, distinct from the
retrieval-layer `InferenceSection` in the glossary) are dispatched per section
type to one of three `SectionChunker` implementations
(`chunking/section_chunker.py:SectionChunker`):

- `TextChunker` (`text_section_chunker.py`): accumulates section text into an
  `AccumulatorState` buffer up to `content_token_limit`, flushing to a `ChunkPayload`
  when the next section would overflow it; an oversized single section is split with
  `chonkie.SentenceChunker` and, if `STRICT_CHUNK_TOKEN_LIMIT` is set, hard-split at
  token boundaries as a last resort.
- `ImageChunker` (`image_section_chunker.py`): always flushes the buffer and emits
  its own one-section chunk carrying `image_file_id`; images never share a chunk
  with text.
- `TabularChunker` (`tabular_section_chunker/tabular_section_chunker.py`): streams a
  staged CSV twice (`file_store.read_file(csv_file_id)`), once to pack rows into
  token-bounded chunks (`parse_to_chunks`) and once through `analyze_sheet` to build
  descriptor/total summary chunks (`sheet_descriptor.py`, `total_descriptor.py`).
  The full sheet is never materialized in memory.

`DocumentChunker.chunk` assigns `chunk_id` sequentially over the section-ordered
payload stream, then `ChunkPayload.to_doc_aware_chunk` attaches the per-document
`title_prefix` (from the blurb splitter) and `metadata_suffix_semantic`/`_keyword`
(`get_metadata_suffix_for_document_index`), each computed once by `Chunker` before
dispatch. If the semantic metadata suffix would reach `MAX_METADATA_PERCENTAGE`
(25%) of the chunk budget, `Chunker._handle_single_document` drops it. The title
prefix and keyword suffix have no such check. `CHUNK_OVERLAP` is always 0 (no
sentence-level overlap between chunks); the only overlap-like behavior is in
multipass "large chunks" (`generate_large_chunks`), which concatenate
`LARGE_CHUNK_RATIO` consecutive normal chunks into one oversized chunk for a second
retrieval pass, referencing their original `chunk_id`s via
`large_chunk_reference_ids`.

**Contextual RAG** (`indexing_pipeline.py:add_contextual_summaries`, gated by
`enable_contextual_rag and llm_enrichment_allowed`) runs after chunking and before
embedding, using a dedicated LLM from
`llm.factory:get_contextual_rag_llm_for_search_settings`. `add_document_summaries`
generates one document-level summary per document (`LLMFlow.CONTEXTUAL_RAG_DOC_SUMMARY`);
`add_chunk_summaries` generates a per-chunk context string relating the chunk to the
document (`LLMFlow.CONTEXTUAL_RAG_CHUNK_CONTEXT`), run in parallel across chunks
(`MAX_CONTEXTUAL_RAG_WORKERS = 128`). Both are skipped per-chunk when
`chunk.contextual_rag_reserved_tokens == 0` (the chunker determined there was no
room). This step never fires for a document whose full content already fits in one
chunk (`single_chunk_fits`, computed in `Chunker._handle_single_document`) or when
the LLM-enrichment global spend limit is tripped
(`_system_llm_enrichment_is_allowed`, `check_global_token_rate_limits`), in which
case the document is instead diverted into a `ConnectorFailure` naming the blocked
enrichment (`_partition_documents_blocked_by_llm_spend_limit`).

**Embedding** (`embedder.py:DefaultIndexingEmbedder.embed_chunks`, called via
`embed_chunks_with_failure_handling` -> `_embed_chunks_to_store` in
`indexing_pipeline.py`). Chunks are split into sub-batches of at most
`MAX_CHUNKS_PER_DOC_BATCH` (1000) and each sub-batch is embedded in one call to
`EmbeddingModel.encode` (`natural_language_processing/search_nlp_models.py`), which
reaches the model server over HTTP at `INDEXING_MODEL_SERVER_HOST`/`_PORT`. Titles
get no separate embedding: the title reaches the vector only through the chunk's
`title_prefix`.
Each successfully embedded sub-batch is immediately pickled to disk via
`ChunkBatchStore.save` (`chunk_batch_store.py`) so the full embedded batch never
sits entirely in process memory; `store.stream()` re-reads it lazily for the write
step. If a document fails embedding, its chunks are stripped from every sub-batch
already written to disk (`store.scrub_failed_docs`), keeping the per-document
all-or-nothing invariant (§5).

**Writing** (`vector_db_insertion.py:write_chunks_to_vector_db_with_backoff`,
called once per batch). `docprocessing_task` builds the index with
`get_default_document_index(index_attempt.search_settings, None)`, so a batch
writes only to the index of the attempt's own `SearchSettings`: PRESENT or FUTURE.
It does not write to both generations. The port backfill (`port/tasks.py`) fills a
FUTURE index (see [[document-index]] §4.4). The write tries the whole
batch in one call to `DocumentIndex.index()`; on any exception it falls back to a
per-document retry loop so one bad document doesn't fail the batch. Before writing,
`adapter.lock_context` (`document.py:prepare_to_modify_documents` ->
`acquire_document_locks`) takes a Postgres row lock on every document in the batch,
so no other process can concurrently modify the same document's index entry during
the write.

### 4.5 Coordination across batches

Many `docprocessing` tasks (one per batch) run concurrently against the **same**
`IndexAttempt`. `IndexingCoordination` (`db/indexing_coordination.py`) is the sole
writer of the attempt's aggregate counters:

- `try_create_index_attempt` is the fencing mechanism that prevents two full-run
  attempts from starting for the same `(cc_pair_id, search_settings_id)`: it does a
  `SELECT ... FOR UPDATE NOWAIT` for any existing non-terminal attempt before
  inserting a new one, inside one transaction. A targeted-reindex attempt
  (`targeted_reindex_job_id` set) is explicitly excluded from this check and may run
  concurrently with a full crawl, relying instead on the per-document row locks in
  §4.4.
- `update_batch_completion_and_docs` increments `completed_batches`,
  `total_docs_indexed`, `new_docs_indexed`, `total_chunks` under a
  `SELECT ... FOR UPDATE` on the `IndexAttempt` row. Each `docprocessing_task` also
  wraps this call in a **Redis lock** keyed by
  `redis_connector.db_lock_key(search_settings_id)` (`CELERY_INDEXING_LOCK_TIMEOUT`
  TTL), acquired with a bounded `CROSS_BATCH_DB_LOCK_ACQUIRE_TIMEOUT_S = 300`
  timeout rather than an unbounded wait, specifically to avoid every docprocessing
  thread across the fleet wedging behind a lock left by a worker killed
  mid-section. A failed acquire raises and the task is redelivered.
- `check_cancellation_requested` / `request_cancellation` implement admin-triggered
  cancellation without Redis fencing: a boolean column on `IndexAttempt`, polled by
  both docfetching (`_check_connector_and_attempt_status`) and
  `check_for_indexing`'s monitor loop.

### 4.6 Checkpointing and resumption

A checkpointed connector (`connectors/interfaces.py:CheckpointedConnector`) yields
its own `ConnectorCheckpoint` alongside each document batch. `checkpointing_utils.py`
persists it to the FileStore keyed by `checkpoint_{index_attempt_id}.json`
(`save_checkpoint`) and points `IndexAttempt.checkpoint_pointer` at it. On a fresh
attempt for the same cc-pair, `get_latest_valid_checkpoint` looks back through up to
`_NUM_RECENT_ATTEMPTS_TO_CONSIDER = 50` recent attempts for one whose poll window
matches exactly and whose status `should_reuse_checkpoint()` (`FAILED`, `CANCELED`,
or `INTERRUPTED`, but not a successful terminal state, which always starts a fresh
window), then loads that attempt's checkpoint blob. If 50 consecutive attempts made
no progress at all, the checkpoint is discarded and the run starts from scratch
rather than replaying a permanently stuck cursor.

Checkpointing tracks **which batches were sent to the file store**, not which
batches finished processing (`run_docfetching.py` comment, verified in source). A
worker death after docfetching enqueued a batch but before docprocessing finished it
is handled separately, by `reissue_old_batches`: on resume, every batch still
sitting in `DocumentBatchStorage` for the cc-pair is re-issued as a fresh
`docprocessing` task under the new attempt's ID, and the new attempt's batch
numbering picks up after the reissued + already-completed count.

`check_checkpoint_size` enforces a 200MB cap on the serialized checkpoint
(`deep_getsizeof`), raising rather than silently truncating a runaway checkpoint
(e.g., a Slack connector accumulating too much per-channel cache state).

### 4.7 Heartbeats and dead-attempt detection

Two independent heartbeat threads exist, started by `start_heartbeat` /
`stop_heartbeat` in `docprocessing/heartbeat.py` and used identically by both
`docfetching_task` and `docprocessing_task`: a daemon thread ticks every
`INDEXING_WORKER_HEARTBEAT_INTERVAL` seconds and increments
`IndexAttempt.heartbeat_counter` in the DB. This is a liveness signal only; it says
nothing about progress rate.

`validate_active_indexing_attempts` (`docprocessing/tasks.py`, run from
`check_for_indexing`) compares each active attempt's `heartbeat_counter` against the
value it last observed. If the counter hasn't advanced for
`HEARTBEAT_TIMEOUT_SECONDS = 1800` (30 minutes):

- if docfetching hasn't finished (`total_batches is None`), the attempt is
  immediately marked `FAILED` ("No heartbeat received");
- if docfetching finished, the check reads `RedisDocprocessing.in_flight()` /
  `.pending()`: `in_flight > 0` means workers crashed while holding batches
  (`FAILED`); `in_flight == 0 and pending > 0` means batches are merely queued
  behind other work, so the attempt is left alone; `in_flight == 0 and pending == 0`
  with no forward progress is also `FAILED`.

Separately, an attempt stuck in `NOT_STARTED` for over
`NOT_STARTED_SCAN_THRESHOLD_HOURS = 12` (its heartbeat never started) is checked
against Celery's queued/unacked task IDs directly and marked `FAILED` if its task is
truly gone. The `docfetching_proxy_task` watchdog additionally polls the subprocess
every 5 seconds for worker shutdown (SIGTERM -> `mark_attempt_interrupted`, resumable),
memory-limit breach (`INDEXING_WORKER_MEMORY_LIMIT_MB` -> `mark_attempt_failed`,
terminates the subprocess before the kernel OOM-killer can take the whole pod), or
the `IndexAttempt` row reaching a terminal status written by someone else, in which
case it kills the now-orphaned subprocess.

### 4.8 Pruning and deletion

**Pruning** (`connector_pruning_generator_task`, `pruning/tasks.py`) does not touch
the indexing pipeline directly. It re-enumerates the source's live document IDs
(`extract_ids_from_runnable_connector`, a `SLIM_RETRIEVAL` connector call, no
content fetched), diffs them against `get_documents_for_connector_credential_pair`,
and for every ID present locally but absent from the source, dispatches
`DOCUMENT_BY_CC_PAIR_CLEANUP_TASK` (`redis_connector_prune.py:generate_tasks`) on the
`connector_deletion` queue.

**`document_by_cc_pair_cleanup_task`** (`background/celery/tasks/shared/tasks.py`) is
the actual removal path, shared by both pruning and connector deletion. It reads
`get_document_connector_count`: if this cc-pair is the document's only owner, it
deletes the document from every configured `DocumentIndex` and the Postgres `Document`
row; if other cc-pairs still reference it, it instead patches the index entry's
access list via `Updatable.update` to drop this cc-pair's contribution, leaving the
document itself intact.

**Connector deletion** (`check_for_connector_deletion_task` ->
`try_generate_document_cc_pair_cleanup_tasks`, `connector_deletion/tasks.py`) only
proceeds once a cc-pair is marked `DELETING`. It explicitly refuses to start while
an `IN_PROGRESS` index attempt, an active port attempt, or a fenced pruning run
exists for that cc-pair (raising `TaskDependencyError`, which the caller reacts to
by leaving the cc-pair fenced for the next beat tick rather than racing with an
in-flight write); an active port attempt is additionally asked to cancel
(`request_port_cancel`) so it stops writing to the index it would otherwise
resurrect documents into. Once clear, it fans out the same
`DOCUMENT_BY_CC_PAIR_CLEANUP_TASK` over every document tied to the cc-pair.

### 4.9 User files: the other adapter

User-uploaded files (Chat attachments, Projects) go through the same
`index_doc_batch`/chunk/embed/write pipeline but plug in
`UserFileIndexingAdapter` (`adapters/user_file_indexing_adapter.py`) instead of
`DocumentIndexingBatchAdapter`. Differences: `connector_id`/`credential_id` are
always `None` (no cc-pair); its `lock_context` locks `UserFile` rows directly
(`_acquire_user_file_locks`, `SELECT ... FOR UPDATE NOWAIT`, three retries) and
raises `UserFileDeletingSkip` (a `ConnectorStopSignal` subclass, so the pipeline
re-raises it rather than recording a failure) if the file is mid-delete, since a
write would resurrect a document the delete path is actively removing and no port
sweep exists to clean up a non-port chunk; its `post_index` sets `UserFile.status`
to `COMPLETED`, stores plaintext for fast retrieval
(`file_store/utils.py:store_user_file_plaintext`), and notifies assistant owners
once every file attached to their assistant is processed. On a FUTURE/secondary
write, `post_index` deliberately does nothing beyond the chunk write itself, leaving
status/notification side effects to the PRESENT pass. Full ownership of user file
storage, projects, and the upload flow belongs to [[file-store-and-user-files]];
this component only describes how a `UserFile` reaches the vector index.

---

## 5. Contracts and invariants

1. **An index attempt writes only to the index of its own `SearchSettings`.**
   Docprocessing builds a single-index handle with `get_default_document_index(...,
   None)`. The port backfill, not a second write, fills the FUTURE index; see
   [[document-index]] §5 for the retrieval-side half of this contract.
2. **A document's chunks are grouped per document, per index.** All
   chunks for one document must be passed to `DocumentIndex.index()` in a single
   call (never split across calls). The write is not atomic: the OpenSearch
   implementation flushes a large document in several bulk writes, so a late
   failure can leave earlier chunks indexed; `write_chunks_to_vector_db_with_backoff`'s
   per-document retry loop groups by document ID for exactly this reason, and
   `_embed_chunks_to_store` strips a failed document's chunks from every already-
   written sub-batch so a partial embedding failure never leaves stale successor
   chunks in `ChunkBatchStore`.
3. **A shortened re-indexed document's stale trailing chunks are the index
   backend's responsibility to delete**, driven by `IndexingMetadata.doc_id_to_chunk_cnt_diff`
   (computed here, from `doc_id_to_previous_chunk_cnt` vs. `doc_id_to_new_chunk_cnt`);
   this component supplies the diff, [[document-index]] enforces the deletion.
4. **Checkpoints must be resumable across a worker crash.** A checkpoint tracks
   what was staged to the file store, not what finished processing; the reissue path
   (§4.6) is what makes an in-flight batch survive a crash, not the checkpoint
   itself.
5. **A heartbeat must be refreshed or the attempt is reaped.** Any new long-running
   step inside `docfetching_task`/`docprocessing_task` that can block for more than
   `HEARTBEAT_TIMEOUT_SECONDS` without the heartbeat thread's DB write succeeding
   will eventually be killed as dead, even if it's still making real progress.
6. **ACLs are attached at index-write time, not read time.** `enrich_chunk` bakes
   `access`, `document_sets`, `boost`, `cc_pair_ids`, and ancestor hierarchy into the chunk at write.
   A permission change requires either a metadata-only `Updatable.update` patch (no
   re-embed) or a full reindex, depending on what changed; see [[access-control]].
7. **The chunk schema this component produces must match the index mapping
   exactly.** `DocMetadataAwareIndexChunk`'s fields and the OpenSearch schema are
   independently maintained; see [[document-index]] §5 for the enforcement (a hard
   write-time error under `"dynamic": "strict"`, not a silent drop).
8. **The two dedup gates in `get_docs_to_update` must not be reordered or merged.**
   A timestamp advance is authoritative and skips the content-hash check on purpose
   (some connectors replace image bytes in place under the same ID); breaking this
   makes those updates silently invisible to indexing.
9. **A FUTURE/secondary write must not touch the shared PRESENT-only content
   hash.** `index_to_secondary=True` disables both the hash gate and the
   post-write hash stamp; violating this cross-suppresses writes between the two
   generations during a swap.
10. **`try_create_index_attempt`'s fence excludes targeted-reindex attempts on
    purpose.** Any change that makes a full-run and a targeted-reindex attempt
    compete for the same fence row removes the concurrency this design relies on.

---

## 6. Relationships

**Depends on**
- [[connectors]]: supplies the `Document`/`Section` stream and the
  `ConnectorCheckpoint` model this component persists and resumes from.
- [[cc-pairs-and-credentials]]: owns the `ConnectorCredentialPair` row, its status
  (`ACTIVE`/`PAUSED`/`DELETING`), and the scheduling trigger `check_for_indexing`
  reads.
- [[document-index]]: the `DocumentIndex` interface this pipeline writes through,
  the embedding-model swap state machine that decides PRESENT vs. FUTURE, and the
  chunk schema this pipeline's output must match.
- [[access-control]]: supplies `get_access_for_documents` / `get_access_for_user_files`,
  baked into every chunk at enrichment time.
- [[permission-sync]]: a separate flow keeps ACLs current between full reindexes;
  this component only attaches whatever ACL state exists at index time.
- [[file-store-and-user-files]]: staged/uploaded file bytes
  (`get_default_file_store`), and the `UserFile` model the user-file adapter writes
  status back to.
- [[llm-providers]]: resolves the contextual-RAG LLM and the image-summarization
  vision LLM used during chunk enrichment.
- [[background-jobs]]: the Celery queue/worker/beat infrastructure every task here
  runs on.
- [[multi-tenancy]]: every DB/Redis access here is tenant-scoped
  (`get_session_with_current_tenant`, `TenantRedisClient`).

**Depended on by**
- [[document-index]]: waits on `check_and_perform_index_swap` to promote a FUTURE
  generation once this pipeline's attempts against it reach the swap criterion.
- [[cc-pairs-and-credentials]]: the admin connector-status page reads `IndexAttempt`
  rows this component writes.
- Nothing in the retrieval or chat path calls into this component directly; it is a
  write-only, background producer for [[document-index]].

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a chunk field | `onyx/indexing/models.py:DocAwareChunk`/`IndexChunk`/`DocMetadataAwareIndexChunk`, the chunker/embedder code that populates it, both `IndexingBatchAdapter` implementations' `enrich_chunk`, and [[document-index]]'s schema and migration story |
| changes the chunker (splitting, overlap, title/metadata prefix budget) | `chunker.py:Chunker`, all three `SectionChunker` implementations, `port_reembed.py` (the AUGMENTATION re-embed path reconstructs chunk text using the same budget logic and will silently drift if you change one without the other), and any admin-visible chunk-count/preview UI |
| changes a Celery task signature or queue | `docfetching/tasks.py`, `docprocessing/tasks.py`, `beat_schedule.py`'s queue/priority entries, and every `app.send_task` call site that constructs the kwargs by hand (there is no shared schema enforcing the two stay in sync across a rolling deploy) |
| changes the checkpoint format (`ConnectorCheckpoint` subclass fields) | `checkpointing_utils.py:load_checkpoint`/`get_latest_valid_checkpoint`, and every in-flight `IndexAttempt.checkpoint_pointer` written by the old format: a rolling deploy must tolerate reading both |
| changes `IndexAttempt` states (`IndexingStatus`) | `should_reuse_checkpoint()`, `is_terminal()`, `is_successful()`, every `mark_attempt_*` function in `db/index_attempt.py`, `validate_active_indexing_attempts`, and the admin connector-status UI that renders the enum |
| changes `IndexingCoordination` locking or the cross-batch Redis lock | every concurrent `docprocessing_task` for the same connector pair and search settings; verify the bounded-timeout behavior still fails a task cleanly rather than wedging on a fossil lock |
| changes dedup gating in `get_docs_to_update` | both the connector-triggered path (`ignore_time_skip=False`) and the docprocessing path (always `ignore_time_skip=True`), plus the FUTURE-write path (`ignore_content_hash_gate=True`) |
| changes pruning or deletion's document-removal task | both callers (`pruning/tasks.py` and `connector_deletion/tasks.py`) share `document_by_cc_pair_cleanup_task`; a change there affects both flows even though they trigger differently |
| changes the reindex-port re-embed logic | `port_reembed.py`'s two strategies must still match what the chunker/embedder currently produce for a fresh index, or the ported chunks will diverge from a true reindex |

---

## 8. How to verify a change

### Tests

```bash
# Unit tests for chunking/embedding internals
cd backend && uv run pytest tests/unit/onyx/indexing -x
cd backend && uv run pytest tests/unit -k "chunker or chunking or embedder"

# External dependency unit tests (real Postgres/Redis/OpenSearch, connector mocked)
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit/indexing

# Integration tests for the full docfetching -> docprocessing -> index flow
uv run --env-file .vscode/.env pytest backend/tests/integration -k "indexing or pruning or connector_deletion"
```

See `backend/AGENTS.md` for the authoritative commands and required env.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log
   backend/log/docfetching_debug.log backend/log/docprocessing_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`, and connect a small source (or trigger a reindex on an
   existing cc-pair from its status page).
3. Watch the connector status page: document count climbing, then a completed run
   with a final doc/chunk count. Trigger a failure (e.g. an oversized fake document)
   and confirm it surfaces as a per-document error with a link, not a run-wide
   failure.
4. Inspect the attempt directly:
   ```bash
   PGPASSWORD="${POSTGRES_PASSWORD:-password}" psql -h "${POSTGRES_HOST:-localhost}" -U postgres \
     -c "SELECT id, status, total_batches, completed_batches, total_docs_indexed, total_chunks, heartbeat_counter FROM index_attempt ORDER BY id DESC LIMIT 5;"
   ```
5. With a checkpoint-capable connector (a `CheckpointedConnector`), kill the
   docprocessing worker mid-run (or `docker stop` the container) and
   confirm: the attempt eventually flips to `FAILED` via the heartbeat check (up to
   `HEARTBEAT_TIMEOUT_SECONDS`), and a fresh scheduled attempt resumes from the
   saved checkpoint rather than re-fetching everything. Other connectors
   restart extraction by design.
6. Delete a document from the source and wait for the next prune cycle; confirm it
   drops out of search results and its `Document` row is removed (or its ACL
   patched, if another cc-pair still owns it).

### What "working" looks like

- `completed_batches` reaches `total_batches` and the attempt reaches a terminal
  `IndexingStatus` that matches whether any `IndexAttemptError` rows exist
  (`SUCCESS` vs. `COMPLETED_WITH_ERRORS`).
- No document is missing its chunks in the index while its `Document.chunk_count`
  in Postgres says otherwise (§5 contract 2/3).
- A resumed attempt after a crash does not re-process already-completed batches,
  and does not lose batches that were staged but never processed.
- Pruned/deleted documents disappear from search results within one cycle of the
  relevant beat task, not immediately (there is no synchronous propagation).

---

## 9. Footguns

- **The docfetching-to-docprocessing handoff is not `ChunkBatchStore`.** It is easy
  to conflate the two file-backed stores in this component: `DocumentBatchStorage`
  (file-store-backed, crosses the Celery task boundary, holds raw `Document`
  objects) versus `ChunkBatchStore` (local temp-dir pickle, never leaves one
  docprocessing task's process, holds embedded chunks). See §4.2.
- **Checkpointing tracks what was staged, not what finished indexing.** A batch can
  be checkpointed as "fetched" while its `docprocessing` task is still queued or
  even lost; `reissue_old_batches` (not the checkpoint) is what recovers a batch
  that never got processed after a crash.
- **`PERSISTENT_INDEXING` changes failure semantics for the whole attempt, not just
  logging.** With it on, an unhandled exception inside `_docprocessing_task` is
  caught, converted into a generic `ConnectorFailure` per document (or one
  `EntityFailure` if the batch never loaded), and the batch is marked "complete"
  with zero counts so the attempt can still reach `COMPLETED_WITH_ERRORS`. Without
  it, the same exception fails the task outright and Celery redelivers it.
- **The cross-batch coordination lock has a bounded acquire on purpose.**
  `CROSS_BATCH_DB_LOCK_ACQUIRE_TIMEOUT_S = 300` exists because an earlier unbounded
  `acquire()` let one killed worker's fossil lock (held for up to
  `CELERY_INDEXING_LOCK_TIMEOUT`, several hours) wedge every docprocessing thread
  across the entire fleet for that connector pair and search settings. A "fix" that removes the timeout
  reintroduces that production incident.
- **The targeted-reindex fence exclusion is deliberate, not an oversight.**
  `try_create_index_attempt`'s active-attempt check explicitly filters out
  `targeted_reindex_job_id IS NOT NULL` rows, so a targeted reindex and a full
  connector crawl can run concurrently against the same cc-pair. The per-document
  row lock in `prepare_to_modify_documents` is what actually prevents them from
  corrupting each other's writes, not the attempt-level fence.
- **`Chunker.chunk_token_limit * 2` is passed as the contextual-RAG chunk token
  limit**, a "fudge factor" the code comments as compensating for the chunker's
  tokenizer differing from the LLM's tokenizer. It is not a precise budget
  calculation.
- **A document-push destination is single-tenant only and fires on a cached local
  read.** `get_document_push_config()` is `lru_cache(maxsize=1)`, so changing
  `DOCUMENT_PUSH_ENDPOINT_URL` at runtime (without a process restart) will not be
  picked up.
