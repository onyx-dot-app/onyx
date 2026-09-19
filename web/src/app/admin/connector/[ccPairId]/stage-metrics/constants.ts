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

// Message key for the short explainer per stage, shown in a tooltip next to
// each row in the per-batch table so admins can interpret the timings without
// leaving the modal.
export const STAGE_DESCRIPTION_KEYS = {
  CONNECTOR_VALIDATION: "stageMetrics.stages.connectorValidation.description",
  PERMISSION_VALIDATION: "stageMetrics.stages.permissionValidation.description",
  CHECKPOINT_LOAD: "stageMetrics.stages.checkpointLoad.description",
  CONNECTOR_FETCH: "stageMetrics.stages.connectorFetch.description",
  HIERARCHY_UPSERT: "stageMetrics.stages.hierarchyUpsert.description",
  DOC_BATCH_STORE: "stageMetrics.stages.docBatchStore.description",
  DOC_BATCH_ENQUEUE: "stageMetrics.stages.docBatchEnqueue.description",
  QUEUE_WAIT: "stageMetrics.stages.queueWait.description",
  DOCPROCESSING_SETUP: "stageMetrics.stages.docprocessingSetup.description",
  BATCH_LOAD: "stageMetrics.stages.batchLoad.description",
  DOC_DB_PREPARE: "stageMetrics.stages.docDbPrepare.description",
  IMAGE_PROCESSING: "stageMetrics.stages.imageProcessing.description",
  CHUNKING: "stageMetrics.stages.chunking.description",
  CONTEXTUAL_RAG: "stageMetrics.stages.contextualRag.description",
  EMBEDDING: "stageMetrics.stages.embedding.description",
  DOC_LOCK_ACQUIRE_WAIT: "stageMetrics.stages.docLockAcquireWait.description",
  ENRICHMENT_PREP: "stageMetrics.stages.enrichmentPrep.description",
  VECTOR_DB_WRITE: "stageMetrics.stages.vectorDbWrite.description",
  POST_INDEX_DB_UPDATE: "stageMetrics.stages.postIndexDbUpdate.description",
  COORD_LOCK_ACQUIRE_WAIT:
    "stageMetrics.stages.coordLockAcquireWait.description",
  COORDINATION_UPDATE: "stageMetrics.stages.coordinationUpdate.description",
  FINALIZATION: "stageMetrics.stages.finalization.description",
  GC_COLLECT: "stageMetrics.stages.gcCollect.description",
  BATCH_UNACCOUNTED: "stageMetrics.stages.batchUnaccounted.description",
  BATCH_TOTAL: "stageMetrics.stages.batchTotal.description",
} as const satisfies Record<IndexAttemptStage, string>;

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
