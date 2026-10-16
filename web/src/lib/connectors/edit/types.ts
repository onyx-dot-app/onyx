import type { CCPairFullInfo } from "@/lib/connectors/types";
import type { CredentialCapability } from "@/lib/connectors/checks/types";
import type { AccessType } from "@/lib/types";

/** The pair that the connector form edits, as the page loaded it. */
export interface ConnectorEditTarget {
  ccPair: CCPairFullInfo;
  /** The pair's data-access groups that the user can see. */
  dataAccessGroupIds: number[];
}

/**
 * The full proposed state of a pair. Mirrors `ConnectorEditProposal` in
 * `backend/onyx/server/documents/connector_edit.py`.
 */
export interface ConnectorEditProposal {
  connector_specific_config: Record<string, unknown>;
  access_type: AccessType;
  /**
   * `null` keeps the pair's groups: the editor may see only some of them, so
   * an unchanged access section must not propose the visible ones.
   */
  data_access_group_ids: number[] | null;
  credential_id: number;
  indexing_start: string | null;
  name: string;
  refresh_freq: number | null;
  prune_freq: number | null;
}

/** Mirrors `EditStepKind` in `backend/onyx/connectors/edit_plan/models.py`. */
export type EditStepKind =
  | "access_groups"
  | "access_type"
  | "enter_perm_sync"
  | "leave_perm_sync"
  | "restart_attempt"
  | "full_reindex_then_prune"
  | "full_reindex"
  | "scoped_backfill"
  | "window_backfill"
  | "prune";

/** The steps an admin can add to a plan. */
export type AddableEditStepKind = Extract<
  EditStepKind,
  "full_reindex" | "prune" | "full_reindex_then_prune"
>;

export type EditStepReason =
  | "identity_changed"
  | "behavior_changed"
  | "scope_widened"
  | "scope_narrowed"
  | "items_added_or_changed"
  | "items_removed"
  | "opaque_scope_choice"
  | "indexing_start_earlier"
  | "indexing_start_later"
  | "credential_full_path"
  | "access_changed"
  | "permissions_fetched_during_indexing"
  | "attempt_running"
  | "scoped_backfill_superseded"
  | "admin_added";

export interface EditBackfill {
  window_start: string;
  window_end: string;
  connector_config_override: Record<string, unknown> | null;
}

export interface EditStep {
  kind: EditStepKind;
  /** A required step keeps the pair correct or secure; it cannot be dropped. */
  required: boolean;
  reasons: EditStepReason[];
  /** The config fields that caused the step. */
  field_names: string[];
  backfill: EditBackfill | null;
}

export type EditNoteSeverity = "info" | "warning";

export interface EditNote {
  kind: string;
  severity: EditNoteSeverity;
  message: string;
}

export type ReconciliationOption =
  | "prune"
  | "full_reindex"
  | "both"
  | "nothing";

export type CredentialPath = "keep_indexed" | "full_reindex_and_prune";

export interface ReconciliationChoice {
  field_names: string[];
  options: ReconciliationOption[];
}

export interface CredentialChoice {
  default: CredentialPath;
  options: CredentialPath[];
}

export type EditCheckStatus = "passed" | "failed" | "indeterminate" | "skipped";

export interface EditCheckResult {
  capability: CredentialCapability;
  check_id: string;
  display_name: string;
  required: boolean;
  status: EditCheckStatus;
  message: string;
  remediation: string | null;
  docs_link: string | null;
}

export interface ProposedPairingValidation {
  validation_error: string | null;
  check_results: EditCheckResult[];
  unfinished_check_ids: string[];
}

export interface ConfigFieldChange {
  field_name: string;
  field_class: "identity" | "scope" | "behavior" | "cosmetic";
}

export interface EditPlan {
  field_changes: ConfigFieldChange[];
  /** Pair settings that change and need no propagation (name, frequencies). */
  changed_settings: string[];
  steps: EditStep[];
  reconciliation_choice: ReconciliationChoice | null;
  credential_choice: CredentialChoice | null;
  notes: EditNote[];
  validation: ProposedPairingValidation | null;
  dry_run_results: EditCheckResult[];
  indexed_document_count: number;
}

export interface ConnectorEditPlanResponse {
  plan_id: string;
  cc_pair_id: number;
  created_at: string;
  expires_at: string;
  plan: EditPlan;
  validation_blocks_apply: boolean;
}

export interface ConnectorEditApplyRequest {
  plan_id: string;
  reconciliation: ReconciliationOption | null;
  credential_path: CredentialPath | null;
  added_steps: AddableEditStepKind[];
  dropped_steps: EditStepKind[];
}

export interface ConnectorEditApplyResponse {
  cc_pair_id: number;
  plan_id: string;
  steps: EditStep[];
  reactivated: boolean;
}
