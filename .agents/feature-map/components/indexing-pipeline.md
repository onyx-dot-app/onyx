# Indexing Pipeline

> Turns the documents a connector yields into chunks in the search index, in two
> Celery phases: docfetching runs the connector and stages batches, and
> docprocessing chunks, embeds and writes each batch. It owns the `IndexAttempt`
> record that the admin sees, and the chunking of spreadsheets.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. The cloud usage meter and the EE document-ingestion hook run
inline when they are on.

## User experience

- **An admin connects a source.** Onyx schedules the first run without a click.
  On the connector page the admin sees the document count go up as batches
  finish. The run ends with document and chunk counts. Each document that
  failed shows as its own error with a link and a message, resolved when a
  later run indexes that document. More than 3 failures that are also more than
  10% of the documents fail the run, unless `PERSISTENT_INDEXING` is on.
- **Later runs pick up changes only.** A connector that polls by time fetches
  what changed since the last run. An unchanged document costs no embedding.
- **A run that dies resumes.** After a deploy, a worker restart or a crash, the
  admin sees the interrupted attempt in the history. The next attempt starts by
  itself. A checkpointed connector continues from its checkpoint, and the next
  attempt processes the batches that were staged but not processed. Other
  connectors start the extraction again.
- **A stuck run fails.** A run whose workers stop sending heartbeats is marked
  failed after 30 minutes, so the admin sees "failed", not a run that never
  ends.
- **A spreadsheet is findable, but not row by row.** A search finds a workbook
  or CSV by its name, its sheets, its columns and a summary of its values. A
  query that names one row of a large sheet has little to match. With
  `SKIP_SPREADSHEET_CONTENT` on, a spreadsheet indexes as its title and a
  placeholder.
- **A user uploads a file** in chat or a project. It goes through the same
  chunk, embed and write steps with no fetch phase and no cc-pair
  (`UserFileIndexingAdapter`, [[file-store-and-user-files]]).
- **An embedding rate limit** slows indexing down, not search.

## Scope

This component owns the path from a connector's `Document` stream to chunks in
the index: the two phases, staging, checkpoints, the dedup gate, chunking
(text, image and tabular), contextual RAG, embedding, the write, the
`IndexAttempt` lifecycle and its errors, heartbeats, the tabular re-chunk
migration, and the user-file adapter.

Its neighbours own:
- [[connectors]]: how a connector reads a source and yields documents,
  checkpoints and tabular sections.
- [[cc-pairs-and-creds]]: the cc-pair, its status, and the admin connect
  flow.
- [[document-index]]: the `DocumentIndex` interface, the OpenSearch schema, the
  embedding-model swap, the reindex port, and the metadata sync that keeps
  ACLs and document sets current after a write.
- [[background-jobs]]: workers, queues, beat, task conventions, and the pruning
  and connector deletion flows.
- [[access-control]]: what ACL a document gets. This component only attaches it.
- [[file-store-and-user-files]]: the user-file lifecycle and the file store.

## Architecture

```
beat: check_for_indexing (primary)                docprocessing/tasks.py
  -> try_creating_docfetching_task                 creates IndexAttempt, sends task
docfetching_proxy_task (watchdog)                  docfetching/tasks.py
  -> spawned process: run_docfetching_entrypoint   background/indexing/run_docfetching.py
       connector generator -> per batch:
         store_batch(batch_num)                    DocumentBatchStorage (file store)
         save_checkpoint                           checkpointing_utils.py
         send DOCPROCESSING_TASK(batch_num)
       set_total_batches                           extraction is done
docprocessing_task, one per batch                  docprocessing/tasks.py
  -> run_indexing_pipeline                         indexing/indexing_pipeline.py
       prepare: upsert Document rows, dedup gate   get_docs_to_update
       chunk -> [contextual RAG] -> embed          ChunkBatchStore spills to local disk
       lock rows -> enrich (ACL, sets, boost) -> write_chunks_to_vector_db_with_backoff
  -> IndexingCoordination.update_batch_completion_and_docs   attempt row lock
  -> resolve_index_attempt_errors_for_documents              one UPDATE, no lock
check_for_indexing (next tick): completed_batches >= total_batches -> mark done
```

**Why two phases.** A connector is a serial generator that runs third-party
SDK code for minutes or hours. Docfetching runs it in a spawned process under a
watchdog (`background/indexing/job_client.py`), so the watchdog can kill it on
a memory limit or a terminal status without losing the worker. The work after
fetch is parallel and needs the model server. Docprocessing runs one task per
batch on its own worker pool, so embedding scales apart from fetching.
The staged batch file is the handoff and the recovery unit
([[#staged-batch-reissue]]). The spawned process ends with `os._exit`
(`background/celery/tasks/docfetching/tasks.py:_docfetching_task`), which skips
the `finally` block of `background/indexing/job_client.py:_initializer`; cleanup
that must run there goes before the exit.

**Two batch stores.** `file_store/document_batch_storage.py:DocumentBatchStorage`
holds raw batches in the file store; they cross the task boundary and survive a
crash. `indexing/chunk_batch_store.py:ChunkBatchStore` spills embedded chunks to
local disk inside one docprocessing task, so a large batch is never in memory.

**Dedup gate.** `indexing/indexing_pipeline.py:get_docs_to_update`
decides which documents to re-chunk. Gate 1 skips a document whose
`doc_updated_at` did not advance. Gate 2 skips one whose `content_hash()` is
unchanged. An ACL change bypasses both. Docprocessing turns gate 1 off, because
the connector already filtered by time. A FUTURE attempt turns gate 2 off.
`force_update` turns both off, for the per-document retry and the tabular
re-chunk migration.

**The write.** The enricher bakes access, document sets, boost, cc-pair IDs and
hierarchy ancestors into each chunk. A later permission change reaches the index
through the metadata sync ([[document-index]]), not through re-indexing. When
OpenSearch has a write block (`OpenSearchIndexWriteBlockedError`), every
document fails alike, so `indexing/vector_db_insertion.py:write_chunks_to_vector_db_with_backoff`
skips the per-document retry and records one failure per document.

**Coordination.** `db/indexing_coordination.py:IndexingCoordination` writes an
attempt's batch counters ([[#batch-completion-row-lock]]).
`try_create_index_attempt` is the per cc-pair and search-settings fence: a
`SELECT ... FOR UPDATE NOWAIT` on any open full-run attempt, in the insert's
transaction. Creators take the tenant Redis creation lock, then the cc-pair row
lock, then the attempt rows. Pause and delete take the same cc-pair row lock,
so they never miss an attempt that is being created.

**Liveness and outside stops.** `background/celery/tasks/docprocessing/heartbeat.py:start_heartbeat`
runs a thread in both phases that increments `IndexAttempt.heartbeat_counter`.
`background/celery/tasks/docprocessing/tasks.py:validate_active_indexing_attempts`
fails an attempt whose counter did not move for `HEARTBEAT_TIMEOUT_SECONDS`;
after fetch ends, it waits instead while batches are only queued
(`RedisDocprocessing`). It also fails a `NOT_STARTED` attempt older than
`NOT_STARTED_SCAN_THRESHOLD_HOURS` whose task Celery does not hold. An admin
cancel sets `IndexAttempt.cancellation_requested`, which docfetching and the
monitor poll. The watchdog kills the spawned process when its RSS passes
`INDEXING_WORKER_MEMORY_LIMIT_MB` (before the kernel OOM killer takes the pod)
or another writer sets a terminal status. It marks the attempt `INTERRUPTED` on
worker shutdown.

**Checkpoints and reissue.** `background/indexing/checkpointing_utils.py:get_latest_valid_checkpoint`
reuses the checkpoint of a recent failed, canceled or interrupted attempt with
the same poll window. Docfetching starts fresh when the attempt is from the
beginning, is a backfill, follows a success, or the connector config hash
changed. `background/indexing/run_docfetching.py:reissue_old_batches` sends every
batch still in storage for the cc-pair as a task of the new attempt. It runs
when a checkpointed connector resumes, or when the previous attempt finished
fetching. Otherwise docfetching throws those batches away, because it fetches
them again.

**Dispatch priority and the first-index hold.** `docfetching_priority` sends a
pair's first index at HIGH and refreshes at MEDIUM ([[#future-attempts-first]]);
priority orders the queue only. While
`connectors/capability_checks/indexing_hold.py:get_first_indexing_hold` returns
a hold, a pair's first attempt is created with no task, and each
`check_for_indexing` tick checks again (`try_dispatching_waiting_attempt`).
With `CONNECTOR_CHECKS_ENABLED` off (the default), nothing is held
([[connector-capability-checks]]).

**Tabular content.** A connector turns a CSV or a workbook sheet into a
`TabularSection` whose CSV is staged in the file store ([[connectors]]).
`indexing/chunking/document_chunker.py:DocumentChunker` groups a document's
tabular sections by `link` and sends each group to
`TabularChunker.chunk_workbook` once, so a document with two attachments yields
two sets of chunks. `indexing/chunking/tabular_section_chunker/workbook_chunks.py:build_workbook_chunks`
emits an overview, the full rows of small sheets, and a bounded profile of large
sheets. With `SKIP_SPREADSHEET_CONTENT` on, connectors replace the sections with
one placeholder, and `indexing/indexing_pipeline.py:skip_tabular_content` does
the same in docprocessing and targeted reindex. User files and the ingestion API
keep their content.

**The tabular re-chunk migration** (`background/indexing/run_tabular_rechunk.py`,
on beat only with `TABULAR_RECHUNK_ENABLED`) re-chunks stored tabular documents
that hold more chunks than the chunker can produce. It reads the raw file from
the file store, never the connector. It passes `force_update`, so its adapter
re-reads `file_id` and `chunk_count` under the document lock and raises when a
crawl rewrote the document while the batch embedded. It runs once: a stored
record (`KV_TABULAR_RECHUNK_PROGRESS_KEY`) stops it even while the variable
stays set. To run it again, delete that record through the KV store.

**Contextual RAG.** The pipeline asks an LLM for a document summary
(`indexing/indexing_pipeline.py:add_document_summaries`) and a context line per
chunk, and embeds both. `SearchSettings.enable_contextual_rag` or the
`ENABLE_CONTEXTUAL_RAG` env flag turns it on; the setting cannot turn the flag
off ([[document-index#contextual-rag-validator]]).

**Hooks and push.** The document-ingestion hook and the document-push sink
call the customer endpoint once per document, in sequence. The push runs only
for PUBLIC cc-pairs, never in a from-beginning index, and never under
`MULTI_TENANT` (`indexing/indexing_pipeline.py:_maybe_push_documents`, [[hooks]]).
`indexing/document_push.py:get_document_push_config` is cached per process, so
a changed push endpoint needs a restart.

**Credential errors.** A connector that raises `ConnectorValidationError`
cancels the attempt. When the 5 most recent completed attempts of a PRESENT,
non-backfill run all ended this way, `connector_document_extraction` marks the
cc-pair `INVALID`. A `RuntimeError` fails the attempt and does neither, so pick
the error type on purpose in auth code.

## Contracts and traps

1. `one-index-per-batch` **A batch writes to one index only:** the index of its
   attempt's own `SearchSettings`. During a REINDEX or ACTIVE_ONLY reindex,
   `background/celery/tasks/docprocessing/tasks.py:check_for_indexing` creates
   attempts for both generations; an INSTANT reindex creates none for FUTURE.
   Do not make docprocessing write both: the port fills FUTURE, and a second
   writer would race its create-only copy.
2. `document-written-whole` **A document's chunks go to `DocumentIndex.index()`
   in one call.** The index deletes stale trailing chunks from
   `IndexingMetadata.doc_id_to_chunk_cnt_diff`. The write is not atomic, so the
   per-document retry in
   `indexing/vector_db_insertion.py:write_chunks_to_vector_db_with_backoff`
   groups by document. An embedding failure in a later sub-batch makes
   `indexing/chunk_batch_store.py:ChunkBatchStore.scrub_failed_docs` remove the
   document's earlier chunks, so a document is written whole or not at all.
3. `staged-batch-reissue` **A checkpoint records what was staged, not what was
   processed.** Only `background/indexing/run_docfetching.py:reissue_old_batches`
   recovers a staged batch that was never processed. A change to batch numbering
   must keep its arithmetic: it moves old batches first, then reads the old
   `completed_batches` again, because old tasks can still finish during the move.
4. `staged-data-crosses-deploys` **Staged batches and checkpoints outlive the
   code that wrote them.** A newer docprocessing pod reads a batch that an
   older docfetching pod staged, and a reissue can read one from days before.
   A change to `Document` or a section model must still validate old batch
   JSON; `file_store/document_batch_storage.py:DocumentBatchStorage._deserialize_documents`
   normalizes or skips the old shapes it knows. A checkpoint that fails
   validation does not fail the attempt: `get_latest_valid_checkpoint` logs it
   and starts the run from the beginning.
5. `acks-on-receipt` **`docprocessing_task` acks on receipt
   (`acks_late=False`), as docfetching does.** With late acks, the broker
   redelivers a batch that runs past the visibility timeout, and the duplicate
   completion ends the attempt early. A lost batch is safe: its file stays in
   storage for the next attempt.
6. `batch-completion-row-lock` **Batch completion takes only the attempt row
   lock.** `db/indexing_coordination.py:IndexingCoordination.update_batch_completion_and_docs`,
   called from `background/celery/tasks/docprocessing/tasks.py:_docprocessing_task`,
   increments the counters under `SELECT ... FOR UPDATE` on the `IndexAttempt` row.
   Postgres serializes concurrent batches and releases the lock when a worker's
   connection dies. Do not add a Redis or other cross-process lock around this
   section: a lock that outlives a holder killed mid-section stops completions
   for every docprocessing thread of the pair until it expires. Keep slow work,
   such as `db/index_attempt.py:resolve_index_attempt_errors_for_documents`,
   out of the row-lock transaction.
7. `heartbeat-must-advance` **A long new step must not stop the heartbeat.** A
   step that blocks the database write of
   `background/celery/tasks/docprocessing/heartbeat.py:start_heartbeat` for
   `HEARTBEAT_TIMEOUT_SECONDS` gets its attempt failed while it still works.
8. `dedup-gate-order` **Do not reorder or merge the two dedup gates** in
   `indexing/indexing_pipeline.py:get_docs_to_update`. A timestamp advance is
   authoritative. Some connectors replace image bytes in place under the same
   ID, and the content hash cannot see that.
   `connectors/models.py:DocumentBase.content_hash` walks text and image
   sections only, so a changed spreadsheet looks unchanged to gate 2.
9. `future-ignores-content-hash` **A FUTURE write must not read or stamp the
   content hash.** The hash column is shared and belongs to PRESENT. If FUTURE
   uses it, the two generations suppress each other's writes during a reindex.
10. `targeted-reindex-outside-fence` **The attempt fence excludes targeted
   reindex on purpose.**
   `db/indexing_coordination.py:IndexingCoordination.try_create_index_attempt`
   ignores rows with `targeted_reindex_job_id`. A targeted reindex and a full
   crawl run at the same time. The per-document row lock in
   `backend/onyx/db/document.py:prepare_to_modify_documents` keeps their writes
   apart. The heartbeat check skips these attempts too; the targeted-reindex
   job owns their lifecycle.
11. `chunk-text-second-copy` **The chunk text recipe has a second copy.**
    `indexing/port_reembed.py` rebuilds the embedding input from stored chunks
    for the reindex port. A change to title prefix, metadata suffix or
    contextual-RAG text in the chunker must change it too, or ported chunks
    differ from freshly indexed ones.
12. `checkpoint-reuse-guards` **Keep the three guards on checkpoint reuse.**
    `db/index_attempt.py:get_recent_completed_attempts_for_cc_pair` skips
    attempts with no `poll_range_end`. Without the skip, an attempt that a pause
    canceled before docfetching set its window makes the next attempt take a
    fresh window, find no checkpoint and delete the staged batches.
    `background/indexing/checkpointing_utils.py:get_latest_valid_checkpoint`
    drops the checkpoint after `_NUM_RECENT_ATTEMPTS_TO_CONSIDER` attempts in a
    row with no progress.
    `background/indexing/checkpointing_utils.py:check_checkpoint_size` fails the
    attempt above `CHECKPOINT_SIZE_LIMIT_BYTES`; a connector must cap its own
    checkpoint state.
13. `future-attempts-first` **Do not starve FUTURE attempts of a finalizing
    reindex.** While a port-flow reindex is finalizing
    (`db/port_attempt.py:reindex_finalizing`: every connector port succeeded),
    `background/celery/tasks/docfetching/task_creation_utils.py:docfetching_priority`
    sends FUTURE attempts at HIGH. `background/indexing/run_docfetching.py`
    applies the same rule to the docprocessing sends and checks it again during
    a long FUTURE run. The index swap waits until no FUTURE attempt of a
    required pair runs ([[document-index]]). A change to attempt creation or
    priority that delays FUTURE attempts stalls the swap.
14. `tabular-chunks-bounded` **Tabular chunk count does not grow with row
    count.** `TABULAR_MAX_CHUNKS_PER_WORKBOOK` caps the chunks of each file, and
    there is no per-row chunking.
    `indexing/chunking/tabular_section_chunker/workbook_chunks.py:build_workbook_chunks`
    queues one block per sheet before any sheet gets extras, and the overview
    names every sheet, so a full budget costs detail, not whole sheets. A file
    that yields no chunks still gets the empty payload of
    `indexing/chunking/document_chunker.py:DocumentChunker.chunk`, so it is
    findable by title and metadata only. Stream sheets from the staged CSV; do
    not materialize a sheet in memory.
15. `tabular-summaries-honest` **A tabular chunk never claims more than the data
    proves.** Only a column's own values settle the day and month order of a
    date (`indexing/chunking/tabular_section_chunker/cell_values.py:DateOrder`);
    never assume a locale. Percentages and mixed currencies are never summed,
    and a clipped breakdown says how much it shows. The tests in
    `backend/tests/unit/onyx/indexing/test_workbook_chunks.py` hold the cases.

## Decisions

- **`PERSISTENT_INDEXING` trades a failed attempt for per-document errors.**
  With it on, an unexpected docprocessing exception becomes one failure per
  document, and the batch counts as complete, so the attempt can end
  `COMPLETED_WITH_ERRORS` (`indexing/persistent_indexing.py`). Without it, the
  task fails and the next attempt reissues the batch. Connector generator
  exceptions in docfetching fail the attempt either way.
- **The embedding rate limit blocks instead of failing.** The limit is one
  sliding window per tenant in Redis
  (`natural_language_processing/embedding_rate_limit.py`). A full window or a
  provider 429 makes the worker thread wait, so it takes no new task.
  Self-hosted waits up to hours. Cloud workers are shared by all tenants, so
  cloud backs off for about a minute and then fails the batch.
- **LLM enrichment respects the global spend limit.** When the global token
  budget is spent, documents that need contextual RAG or an image summary
  become per-document failures. They are not indexed without enrichment.
  [[rate-and-usage-limits]] owns the budget.

## Known issues

- **A PRESENT attempt can chunk with FUTURE settings.**
  `run_indexing_pipeline` takes multipass and contextual-RAG settings from the
  FUTURE `SearchSettings` whenever one exists, but `docprocessing_task` embeds
  with the attempt's own. It is unconfirmed as a bug; check before you rely on
  either behaviour.
- **Index-time LLM steps skip the provider cost limit.** Contextual RAG
  (`llm/factory.py:get_llm_for_contextual_rag`) and image summarization
  (`llm/factory.py:get_default_llm_with_vision`) do not call
  `check_llm_cost_limit_for_provider`. Only the global token budget gates them.
  Whether that is on purpose is open; [[rate-and-usage-limits]] decides.

## Dependencies

- [[connectors]]: the document stream, checkpoints, tabular sections, failures.
- [[cc-pairs-and-creds]]: the cc-pair, its status and its schedule.
- [[document-index]]: `DocumentIndex.index()`, the chunk schema, and which
  `SearchSettings` generations exist.
- [[access-control]]: the ACL that the enricher attaches.
- [[background-jobs]]: queues, beat, `TenantAwareTask` and the task conventions.
- [[llm-providers]]: the contextual-RAG and image-summary models.
- [[file-store-and-user-files]]: storage for batches, checkpoints and CSVs.
- [[rate-and-usage-limits]]: the global budget check and the chunk usage meter.

## Recipes

- `chunk-field` **A chunk field.** Copy how `doc_summary` flows: add the field
  to the chunk models in `indexing/models.py`, and fill it in the chunker or the
  enricher. Check every adapter (`git ls-files backend/onyx/indexing/adapters`).
- `docprocessing-long-step` **A long step in docprocessing.** Copy the
  `time_stage_if_set(IndexAttemptStage.CONTEXTUAL_RAG, ...)` block of
  `run_indexing_pipeline`. Add the
  stage to `db/index_attempt_metrics_models.py:IndexAttemptStage` and to its
  hand mirror `web/src/lib/types.ts:INDEX_ATTEMPT_STAGES`, in the same order.
  Keep the heartbeat moving ([[#heartbeat-must-advance]]), and make a failure a
  per-document failure, not a task failure.
- `llm-enrichment-step` **An LLM enrichment step.** Copy contextual RAG
  (`add_contextual_summaries`), and check for an existing output first
  (`doc_summary`, image summaries). Add the step to `llm_enrichment_configured`
  in `run_indexing_pipeline`, so the `INDEXING_PIPELINE_TRACE_NAME` root trace
  opens and usage is recorded. Gate it on `_system_llm_enrichment_is_allowed`.
  Give `_partition_documents_blocked_by_llm_spend_limit` a keyword flag and a
  `*_ENRICHMENT_NAME` constant for the step. Call the LLM with
  `TraceContentMode.METADATA_ONLY`, so document text does not reach the trace
  backends. Give it an `LLMFlow` and add the flow to
  `tracing/flows.py:SYSTEM_TEXT_GENERATION_FLOWS`. Let a failed call raise, so
  the document fails alone (`_summarize_document`). If it changes the embedded
  text, change `indexing/port_reembed.py` too ([[#chunk-text-second-copy]]).
- `pipeline-caller` **A new caller of `run_indexing_pipeline`.** Copy
  `background/indexing/run_targeted_reindex.py`. Pass the right gate flags
  ([[#dedup-gate-order]], [[#future-ignores-content-hash]]) and an adapter. Pass
  `skip_spreadsheet_content` only for connector content. List the callers with
  `git grep -l 'run_indexing_pipeline(' backend/onyx backend/ee`.
- `tabular-chunking-change` **A change to tabular chunking.** Change the profile
  in `indexing/chunking/tabular_section_chunker/workbook_chunks.py`, keep
  [[#tabular-summaries-honest]], and add a case to the tests it names. Chunks in
  the index keep the old shape until the document changes. To rewrite them, run
  the tabular re-chunk migration (Architecture); it re-chunks documents whose
  chunk count passes the new ceiling.
- `investigate-stuck-attempt` **Investigate a stuck or slow attempt.** Read the
  pair's latest `index_attempt` rows. An empty `total_batches` means docfetching
  still runs. A `heartbeat_counter` that does not move means no worker holds the
  attempt. `completed_batches` that stops below `total_batches` means batches
  wait in the queue or were lost; the `RedisDocprocessing` counters tell which.
  The `index_attempt_stage_metric` rows show the slow stage.
- `reproduce-resume` **Reproduce a resume.** Start a run of a checkpointed
  connector, not the file connector; list them with
  `git grep -l CheckpointedConnector backend/onyx/connectors`. Kill the
  docprocessing worker during the run. The attempt fails after the heartbeat timeout, and the next attempt resumes from
  the checkpoint and reissues the staged batches. At the end,
  `completed_batches` equals `total_batches`.

## Verification

- Unit tests: `backend/tests/unit/onyx/indexing/`, `backend/tests/unit/onyx/background/`.
- External dependency tests: `backend/tests/external_dependency_unit/indexing/`
  and `backend/tests/external_dependency_unit/db/`.
- Integration tests: `backend/tests/integration/tests/indexing/`.
