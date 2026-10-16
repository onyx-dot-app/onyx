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
import type { CapabilityCheckResult } from "@/lib/connectors/checks/types";
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

  // The source names checks of its own, which can run on a schedule.
  has_named_checks: boolean;
  // Why the first index attempt waits, or null once it can start.
  indexing_hold: IndexingHold | null;
}

/** Mirrors `IndexingHoldReason` in `backend/onyx/connectors/capability_checks/indexing_hold_models.py`. */
export type IndexingHoldReason =
  | "checks_running"
  | "checks_failed_to_run"
  | "required_checks_failed";

/** A required check that failed. Mirrors `HeldCheck`. */
export interface HeldCheck {
  check_id: string;
  capability: string;
  display_name: string;
  message: string;
  remediation: string | null;
  docs_link: string | null;
}

/** Mirrors `IndexingHold`. */
export interface IndexingHold {
  reason: IndexingHoldReason;
  failed_checks: HeldCheck[];
  index_attempt_id: number | null;
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
  total_groups_failed: number;
  time_created: string;
  time_started: string | null;
  time_finished: string | null;
}

/** Mirrors `CCPairRunKind` in `backend/onyx/db/enums.py`. */
export type CCPairRunKind =
  | "indexing"
  | "doc_permission_sync"
  | "group_sync"
  | "pruning"
  | "checks";

/** Mirrors `SyncStatus`: how a prune stands. */
export type PruneRunStatus = "in_progress" | "success" | "failed" | "canceled";

/** Mirrors `CapabilityCheckRunStatus`. `failed` means a required check failed. */
export type CheckRunStatus = "running" | "passed" | "failed" | "failed_to_run";

/** One prune of the pair. Mirrors `PruneRunSnapshot` in `backend/onyx/server/documents/models.py`. */
export interface PruneRunSnapshot {
  id: number;
  status: PruneRunStatus;
  docs_removed: number;
  docs_failed: number;
  error_message: string | null;
  time_created: string;
  time_started: string | null;
  time_finished: string | null;
}

/** One run of the pair's connector checks. Mirrors `CheckRunSnapshot`. */
export interface CheckRunSnapshot {
  id: number;
  status: CheckRunStatus;
  trigger: string;
  /** Empty until the run completes, and for a run that broke. */
  check_results: CapabilityCheckResult[];
  /** Why a run broke. */
  error_message: string | null;
  time_created: string;
  time_started: string | null;
  time_finished: string | null;
}

/** Mirrors `CCPairRunStatusGroup`: how the run list buckets every kind's statuses. */
export type CCPairRunStatusGroup =
  | "running"
  | "succeeded"
  | "failed"
  | "canceled";

/** Mirrors `HierarchyNodeType` in `backend/onyx/db/enums.py`. */
export type HierarchyNodeType =
  | "folder"
  | "source"
  | "stub"
  | "shared_drive"
  | "my_drive"
  | "space"
  | "page"
  | "project"
  | "database"
  | "workspace"
  | "site"
  | "drive"
  | "channel"
  | "mailbox";

/** One breakdown row: a node the config names or the hierarchy has, and the pair's documents under it. Mirrors `HierarchyBreakdownEntry`. */
export interface HierarchyBreakdownEntry {
  /** The id the connector config uses for the node, such as a Confluence space key. */
  raw_node_id: string;
  /** `null` when the config names a node the hierarchy does not have. */
  display_name: string | null;
  link: string | null;
  /** `null` when the config names the node but no document sits under it. `0` for a node the config does not name. */
  doc_count: number | null;
}

/** Where a pair's documents come from, by node type. Mirrors `CCPairHierarchyBreakdown`. */
export interface CCPairHierarchyBreakdown {
  nodes_by_type: Partial<Record<HierarchyNodeType, HierarchyBreakdownEntry[]>>;
  /** Documents in no listed node's subtree. Rows can overlap (a page inside a listed space), so rows plus this can exceed the pair's total. */
  other_doc_count: number;
  /** Config fields whose values the rows list, so the page shows no row for them. */
  config_fields: string[];
}

/** Mirrors `CCPairRunErrors`: runs with open document errors, with all of them resolved, or with none. */
export type CCPairRunErrors = "unresolved" | "resolved" | "none";

/** One run of a pair, told apart by `kind`. Mirrors `CCPairRun`. */
/** When an admin resolved the run, on every run. A resolved run keeps its status. */
interface CCPairRunResolution {
  resolved_at: string | null;
}

export type CCPairRun = CCPairRunResolution &
  (
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
      }
    | { kind: "pruning"; time_created: string; attempt: PruneRunSnapshot }
    | { kind: "checks"; time_created: string; attempt: CheckRunSnapshot }
  );

/** Mirrors `CCPairRunsResponse`. `status_counts` ignores the status filter. */
export interface CCPairRunsResponse {
  items: CCPairRun[];
  total_items: number;
  kinds: CCPairRunKind[];
  status_counts: Record<CCPairRunStatusGroup, number>;
}

/** An activity level that holds open runs, as the batch resolve routes take it. */
export type CCPairRunLevel = "failures" | "errors";

/** The run list's query, as `GET /admin/cc-pair/{id}/runs` takes it. */
export interface CCPairRunsQuery {
  pageNum: number;
  pageSize: number;
  /** ISO time. Runs created before it are left out. */
  since: string | null;
  /** ISO time. Runs created at or after it are left out. */
  until: string | null;
  kinds: CCPairRunKind[] | null;
  statusGroups: CCPairRunStatusGroup[] | null;
  /** Matched against error messages. */
  q: string;
  /** Keeps only runs with document errors, open or resolved, or only runs without any. */
  errors: CCPairRunErrors | null;
  /** Leaves out (`false`) or keeps only (`true`) the failed runs a newer run of their kind followed. With `errors`, `true` keeps the runs either matches. */
  superseded: boolean | null;
  /** Reads the runs an admin resolved the way `superseded` reads the superseded ones. */
  resolved: boolean | null;
}

export interface IndexAttemptError {
  id: number;
  connector_credential_pair_id: number;

  document_id: string | null;
  document_link: string | null;
  /** The indexed document's title, `null` until the document lands. */
  document_name: string | null;

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

/** How far back a throughput chart reaches. */
export type CCPairThroughputWindow = "1h" | "12h" | "24h" | "7d";

/** Mirrors `CCPairThroughputResponse`: an estimate of the documents per equal slice of the window, oldest first. Each run's total is spread evenly over its span. */
export interface CCPairThroughputResponse {
  window_start: string;
  window_end: string;
  docs_indexed: number[];
  /** `ended` is null while the run is still going. */
  runs: { started: string; ended: string | null; status: ValidStatuses }[];
}
