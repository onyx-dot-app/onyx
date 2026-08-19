import { INDEX_ATTEMPT_STAGES, IndexAttemptStage } from "@/lib/types";

// Human-readable label per stage. Explicit (rather than auto-cased) so that
// acronyms like DB / RAG render correctly.
export const STAGE_LABELS: Record<IndexAttemptStage, string> = {
  CONNECTOR_VALIDATION: "Connector validation",
  PERMISSION_VALIDATION: "Permission validation",
  CHECKPOINT_LOAD: "Checkpoint load",
  CONNECTOR_FETCH: "Connector fetch",
  HIERARCHY_UPSERT: "Hierarchy upsert",
  DOC_BATCH_STORE: "Doc batch store",
  DOC_BATCH_ENQUEUE: "Doc batch enqueue",
  QUEUE_WAIT: "Queue wait",
  DOCPROCESSING_SETUP: "Docprocessing setup",
  BATCH_LOAD: "Batch load",
  DOC_DB_PREPARE: "Doc DB prepare",
  IMAGE_PROCESSING: "Image processing",
  CHUNKING: "Chunking",
  CONTEXTUAL_RAG: "Contextual RAG",
  EMBEDDING: "Embedding",
  DOC_LOCK_ACQUIRE_WAIT: "Doc lock acquire wait",
  ENRICHMENT_PREP: "Enrichment prep",
  VECTOR_DB_WRITE: "Vector DB write",
  POST_INDEX_DB_UPDATE: "Post-index DB update",
  COORD_LOCK_ACQUIRE_WAIT: "Coord lock acquire wait",
  COORDINATION_UPDATE: "Coordination update",
  FINALIZATION: "Finalization",
  GC_COLLECT: "Garbage collection",
  BATCH_UNACCOUNTED: "Unaccounted",
  BATCH_TOTAL: "Batch total",
};

// Short explainer per stage, shown in a tooltip next to each row in the
// per-batch table so admins can interpret the timings without leaving the
// modal.
export const STAGE_DESCRIPTIONS: Record<IndexAttemptStage, string> = {
  CONNECTOR_VALIDATION:
    "Validates that the connector is configured correctly and reachable before fetching begins.",
  PERMISSION_VALIDATION:
    "Verifies the credential has the permissions needed to read documents from the source.",
  CHECKPOINT_LOAD:
    "Loads any prior checkpoint so a resumed attempt can pick up where the last one left off.",
  CONNECTOR_FETCH:
    "Time spent calling the upstream source to retrieve a batch of raw documents.",
  HIERARCHY_UPSERT:
    "Records hierarchy and metadata relationships (folders, parents, etc.) for the batch in Postgres.",
  DOC_BATCH_STORE:
    "Persists the fetched batch to the file store so the docprocessing worker can consume it asynchronously.",
  DOC_BATCH_ENQUEUE:
    "Submits a docprocessing task for the batch onto the Celery queue.",
  QUEUE_WAIT:
    "Time the docprocessing task spent waiting in the Celery queue before a worker picked it up.",
  DOCPROCESSING_SETUP:
    "One-time setup the docprocessing worker performs before processing batches (DB session, embedder, etc.).",
  BATCH_LOAD:
    "Reads the batch back from the file store inside the docprocessing worker.",
  DOC_DB_PREPARE:
    "Cleans, dedupes, and prepares documents for indexing — includes the DB lookups against existing document state.",
  IMAGE_PROCESSING:
    "Extracts and processes images embedded in document sections.",
  CHUNKING: "Splits documents into chunks sized for the embedding model.",
  CONTEXTUAL_RAG:
    "Optional LLM call that adds short contextual summaries to each chunk to improve retrieval quality.",
  EMBEDDING: "Calls the embedding model to produce vectors for each chunk.",
  DOC_LOCK_ACQUIRE_WAIT:
    "Time spent waiting to acquire the per-document row locks before writing — the wait only, not the write done while holding them (that is Vector DB write / Post-index DB update). High values mean documents are contended across connectors.",
  ENRICHMENT_PREP:
    "Per-batch DB lookups that enrich chunks before writing — access info, document sets, ancestors, and prior chunk counts.",
  VECTOR_DB_WRITE: "Writes the embedded chunks and their metadata to Vespa.",
  POST_INDEX_DB_UPDATE:
    "Updates Postgres with final document state after indexing (last-indexed timestamps, hashes, etc.).",
  COORD_LOCK_ACQUIRE_WAIT:
    "Time spent waiting to acquire the connector-wide coordination lock that every batch serializes on — the wait only, not the update done while holding it (that is Coordination update). High values mean batch-level contention.",
  COORDINATION_UPDATE:
    "Bookkeeping updates after a batch — progress counters, checkpoint advances, and similar.",
  FINALIZATION:
    "Post-coordination bookkeeping — failure recording, progress telemetry, and batch storage cleanup.",
  GC_COLLECT:
    "Per-batch garbage-collection pass (stop-the-world for the worker process).",
  BATCH_UNACCOUNTED:
    "Wall-clock inside the batch not attributed to any measured stage (BATCH_TOTAL minus the measured stages). A high value signals lock contention or an un-instrumented hotspot.",
  BATCH_TOTAL:
    "Total wall-clock time elapsed processing a single batch end-to-end.",
};

// Distinct background classes for the per-row average-time bar. Cycled by
// stage's pipeline-order index so the same stage gets the same color in both
// the bar and the table swatch regardless of the active sort mode.
export const STAGE_BAR_COLORS = [
  "bg-theme-blue-05",
  "bg-theme-green-05",
  "bg-theme-orange-05",
  "bg-theme-purple-05",
  "bg-theme-cyan-05",
  "bg-theme-red-05",
  "bg-theme-yellow-05",
  "bg-theme-primary-05",
] as const;

export const PIPELINE_ORDER: Record<IndexAttemptStage, number> =
  Object.fromEntries(
    INDEX_ATTEMPT_STAGES.map((stage, idx) => [stage, idx])
  ) as Record<IndexAttemptStage, number>;
