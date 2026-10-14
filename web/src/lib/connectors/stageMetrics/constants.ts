import { INDEX_ATTEMPT_STAGES, IndexAttemptStage } from "@/lib/types";

// Message key (inside the `admin.connector` namespace) for the human-readable
// label of each stage. Labels are explicit (rather than auto-cased) so that
// acronyms like DB / RAG render correctly. Modules cannot call hooks, so the
// maps hold keys and the consuming component resolves them with `t`.
export const STAGE_LABEL_KEYS = {
  CONNECTOR_VALIDATION: "stageMetrics.stages.connectorValidation.label",
  PERMISSION_VALIDATION: "stageMetrics.stages.permissionValidation.label",
  CHECKPOINT_LOAD: "stageMetrics.stages.checkpointLoad.label",
  CONNECTOR_FETCH: "stageMetrics.stages.connectorFetch.label",
  HIERARCHY_UPSERT: "stageMetrics.stages.hierarchyUpsert.label",
  DOC_BATCH_STORE: "stageMetrics.stages.docBatchStore.label",
  DOC_BATCH_ENQUEUE: "stageMetrics.stages.docBatchEnqueue.label",
  QUEUE_WAIT: "stageMetrics.stages.queueWait.label",
  DOCPROCESSING_SETUP: "stageMetrics.stages.docprocessingSetup.label",
  BATCH_LOAD: "stageMetrics.stages.batchLoad.label",
  DOC_DB_PREPARE: "stageMetrics.stages.docDbPrepare.label",
  IMAGE_PROCESSING: "stageMetrics.stages.imageProcessing.label",
  CHUNKING: "stageMetrics.stages.chunking.label",
  CONTEXTUAL_RAG: "stageMetrics.stages.contextualRag.label",
  EMBEDDING: "stageMetrics.stages.embedding.label",
  EMBEDDING_RATE_LIMIT_WAIT: "stageMetrics.stages.embeddingRateLimitWait.label",
  EMBEDDING_PROVIDER_THROTTLE_WAIT:
    "stageMetrics.stages.embeddingProviderThrottleWait.label",
  DOC_LOCK_ACQUIRE_WAIT: "stageMetrics.stages.docLockAcquireWait.label",
  ENRICHMENT_PREP: "stageMetrics.stages.enrichmentPrep.label",
  VECTOR_DB_WRITE: "stageMetrics.stages.vectorDbWrite.label",
  POST_INDEX_DB_UPDATE: "stageMetrics.stages.postIndexDbUpdate.label",
  COORD_LOCK_ACQUIRE_WAIT: "stageMetrics.stages.coordLockAcquireWait.label",
  COORDINATION_UPDATE: "stageMetrics.stages.coordinationUpdate.label",
  FINALIZATION: "stageMetrics.stages.finalization.label",
  GC_COLLECT: "stageMetrics.stages.gcCollect.label",
  BATCH_UNACCOUNTED: "stageMetrics.stages.batchUnaccounted.label",
  BATCH_TOTAL: "stageMetrics.stages.batchTotal.label",
} as const satisfies Record<IndexAttemptStage, string>;

export const PIPELINE_ORDER: Record<IndexAttemptStage, number> =
  Object.fromEntries(
    INDEX_ATTEMPT_STAGES.map((stage, idx) => [stage, idx])
  ) as Record<IndexAttemptStage, number>;
