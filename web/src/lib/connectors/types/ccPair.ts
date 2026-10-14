import type { ConnectorManageRole } from "@/lib/connectors/accessType";
import type { UUID } from "crypto";
import type { PermissionsOf } from "@/lib/permissions/resource-actions";
import type {
  AccessType,
  DeletionAttemptSnapshot,
  IndexAttemptSnapshot,
  ValidStatuses,
} from "@/lib/types";
import type { Connector } from "@/lib/connectors/types/connector";
import type { Credential } from "@/lib/credentials/types";

export enum ConnectorCredentialPairStatus {
  SCHEDULED = "SCHEDULED",
  INITIAL_INDEXING = "INITIAL_INDEXING",
  ACTIVE = "ACTIVE",
  PAUSED = "PAUSED",
  DELETING = "DELETING",
  INVALID = "INVALID",
}

export enum PermissionSyncStatusEnum {
  CANCELED = "canceled",
  COMPLETED_WITH_ERRORS = "completed_with_errors",
  FAILED = "failed",
  IN_PROGRESS = "in_progress",
  NOT_STARTED = "not_started",
  SUCCESS = "success",
}

export interface CCPairFullInfo {
  id: number;
  name: string;
  status: ConnectorCredentialPairStatus;
  in_repeated_error_state: boolean;
  num_docs_indexed: number;
  connector: Connector<any>;
  credential: Credential<any>;
  number_of_index_attempts: number;
  last_index_attempt_status: ValidStatuses | null;
  latest_deletion_attempt: DeletionAttemptSnapshot | null;
  access_type: AccessType;
  is_editable_for_current_user: boolean;
  // per-action affordance map for the requesting user (mirrors the write-side gate)
  permissions: PermissionsOf<"CCPair">;
  deletion_failure_message: string | null;
  indexing: boolean;
  creator: UUID | null;
  creator_email: string | null;

  last_indexed: string | null;
  last_pruned: string | null;
  last_full_permission_sync: string | null;
  overall_indexing_speed: number | null;
  latest_checkpoint_description: string | null;

  // permission sync attempt status
  last_permission_sync_attempt_status: PermissionSyncStatusEnum | null;
  permission_syncing: boolean;
  last_permission_sync_attempt_finished: string | null;
  last_permission_sync_attempt_error_message: string | null;

  // True if the connector implements `Resolver.reindex` (targeted reindex).
  // False -> Resolve All falls back to a full connector reindex.
  supports_targeted_reindex: boolean;

  // Backfills that applied edits requested, until an attempt of each succeeds.
  pending_backfills: PendingBackfillSnapshot[];
}

/** Mirrors `CCPairDataAccess` in `backend/ee/onyx/server/documents/models.py`. */
export interface CCPairDataAccess {
  /** Only the groups the caller can see. */
  groups: { id: number; name: string; is_default: boolean }[];
}

/** Mirrors `CCPairManageAccessRow` in `backend/ee/onyx/server/documents/manage_access.py`. */
export interface CCPairManageAccessRow {
  group_id: number;
  group_name: string;
  role: ConnectorManageRole;
  /** Granted by a global connector-management grant: not stored, cannot be removed. */
  is_fixed: boolean;
}

/** Mirrors `PendingBackfillSnapshot` in `backend/onyx/server/documents/models.py`. */
export interface PendingBackfillSnapshot {
  window_start: string;
  window_end: string;
  requested_at: string;
  /** It runs with a config other than the saved one. */
  scoped: boolean;
  attempt_id: number | null;
  failure_count: number;
  /** A failed backfill is retried after this time. */
  retry_after: string | null;
}

/** Mirrors `PaginatedReturn[IndexAttemptSnapshot]`. */
export interface PaginatedIndexAttempts {
  items: IndexAttemptSnapshot[];
  total_items: number;
}

/**
 * One row of the document-permission-sync attempt history. Mirrors
 * `DocPermissionSyncAttemptSnapshot` in
 * `backend/onyx/server/documents/models.py`.
 *
 * Note: timestamps are pre-serialized to ISO strings on the backend
 * (matching `IndexAttemptSnapshot.time_started`/`time_updated`), so the
 * frontend never has to handle `Date` objects directly here.
 */
export interface DocPermissionSyncAttemptSnapshot {
  id: number;
  status: PermissionSyncStatusEnum;
  error_message: string | null;
  full_exception_trace: string | null;
  total_docs_synced: number;
  docs_with_permission_errors: number;
  time_created: string;
  time_started: string | null;
  time_finished: string | null;
}

/**
 * One row of the external-group-sync attempt history. Mirrors
 * `ExternalGroupSyncAttemptSnapshot` in
 * `backend/onyx/server/documents/models.py`. The progress fields differ
 * from the doc-sync shape because group sync tracks user/group/membership
 * counts rather than document-level counts.
 */
export interface ExternalGroupSyncAttemptSnapshot {
  id: number;
  status: PermissionSyncStatusEnum;
  error_message: string | null;
  full_exception_trace: string | null;
  total_users_processed: number;
  total_groups_processed: number;
  total_group_memberships_synced: number;
  time_created: string;
  time_started: string | null;
  time_finished: string | null;
}

/** Mirrors `CCPairRunKind` in `backend/onyx/server/documents/models.py`. */
export type CCPairRunKind = "indexing" | "doc_permission_sync" | "group_sync";

/** Mirrors `CCPairRunStatusGroup`: how the run list buckets every kind's statuses. */
export type CCPairRunStatusGroup =
  | "running"
  | "succeeded"
  | "failed"
  | "canceled";

/** Mirrors `CCPairRunErrors`: runs with open document errors, or with all of them resolved. */
export type CCPairRunErrors = "unresolved" | "resolved";

/** One run of a pair, told apart by `kind`. Mirrors `CCPairRun`. */
export type CCPairRun =
  | { kind: "indexing"; time_created: string; attempt: IndexAttemptSnapshot }
  | {
      kind: "doc_permission_sync";
      time_created: string;
      attempt: DocPermissionSyncAttemptSnapshot;
    }
  | {
      kind: "group_sync";
      time_created: string;
      attempt: ExternalGroupSyncAttemptSnapshot;
    };

/** Mirrors `CCPairRunsResponse`. `status_counts` ignores the status filter. */
export interface CCPairRunsResponse {
  items: CCPairRun[];
  total_items: number;
  kinds: CCPairRunKind[];
  status_counts: Record<CCPairRunStatusGroup, number>;
}

/** The run list's query, as `GET /admin/cc-pair/{id}/runs` takes it. */
export interface CCPairRunsQuery {
  pageNum: number;
  pageSize: number;
  /** ISO time. Runs created before it are left out. */
  since: string | null;
  kinds: CCPairRunKind[] | null;
  statusGroups: CCPairRunStatusGroup[] | null;
  /** Matched against error messages. */
  q: string;
  /** Keeps only runs with document errors, open or resolved. */
  errors: CCPairRunErrors | null;
}

export interface IndexAttemptError {
  id: number;
  connector_credential_pair_id: number;

  document_id: string | null;
  document_link: string | null;

  entity_id: string | null;
  failed_time_range_start: string | null;
  failed_time_range_end: string | null;

  failure_message: string;
  is_resolved: boolean;

  time_created: string;

  index_attempt_id: number;

  error_type: string | null;
}

export interface PaginatedIndexAttemptErrors {
  items: IndexAttemptError[];
  total_items: number;
}

/** Request body for `POST /manage/admin/indexing/targeted-reindex`. */
export interface TargetedReindexRequest {
  error_ids?: number[];
  targets?: { cc_pair_id: number; document_id: string }[];
}

/** Response from `POST /manage/admin/indexing/targeted-reindex`. */
export interface TargetedReindexResponse {
  targeted_reindex_job_id: number;
  queued_count: number;
  skipped_count: number;
}

/** Job status payload from `GET /manage/admin/indexing/targeted-reindex/{job_id}`. */
export interface TargetedReindexJobStatus {
  id: number;
  status:
    | "not_started"
    | "in_progress"
    | "success"
    | "failed"
    | "completed_with_errors"
    | "canceled";
  requested_at: string;
  completed_at: string | null;
  target_count: number;
  resolved_count: number;
  still_failing_count: number;
  skipped_count: number;
  resolved_summary: { id: number; document_id: string }[];
}

/** How far back the status card's throughput chart reaches. */
export type CCPairThroughputWindow = "12h" | "24h" | "7d";

/** Mirrors `CCPairThroughputResponse`: an estimate of the documents per equal slice of the window, oldest first. Each run's total is spread evenly over its span. */
export interface CCPairThroughputResponse {
  window_start: string;
  window_end: string;
  docs_indexed: number[];
  runs: { started: string; status: ValidStatuses }[];
}
