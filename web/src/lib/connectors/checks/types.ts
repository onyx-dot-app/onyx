import type { AccessType } from "@/lib/types";
import type { ValidSources } from "@/lib/connectors/types/source";

/**
 * Mirrors the backend's capability-check models
 * (`onyx.connectors.capability_checks.models`) and the report row the
 * `/manage/admin/credential/{id}/capability-report` endpoint returns.
 */

/** What a credential may be able to do for its source. */
export type CredentialCapability =
  | "indexing"
  | "doc_permission_sync"
  | "external_group_sync";

/**
 * Outcome of one check. `indeterminate` is a transient or unknown failure
 * and must not be read as proof the credential is broken.
 */
export type CapabilityCheckStatus =
  | "passed"
  | "failed"
  | "indeterminate"
  | "skipped";

/** Per-capability roll-up of its checks. */
export type CapabilityVerdict =
  | "passed"
  | "passed_with_warnings"
  | "failed"
  | "indeterminate"
  | "skipped"
  | "not_applicable";

export type CapabilityCheckTrigger =
  | "manual"
  | "credential_created"
  | "cc_pair_validation"
  | "indexing_attempt";

/** Lifecycle of the stored row; the last completed report stays readable
 * while a re-run is `running`. */
export type CapabilityReportRunStatus = "running" | "completed";

export interface CapabilityCheckResult {
  capability: CredentialCapability;
  check_id: string;
  display_name: string;
  /** A required check that fails blocks the capability. */
  required: boolean;
  status: CapabilityCheckStatus;
  /** Failure text, skip reason, or empty on success. */
  message: string;
  error_type: string | null;
  /** A wrapper around the legacy validation rather than a named probe. */
  is_fallback: boolean;
  remediation: string | null;
  docs_link: string | null;
  duration_ms: number | null;
}

export interface CredentialCapabilityReport {
  credential_id: number;
  source: ValidSources;
  /** `null` for a config-less, credential-only run. */
  connector_id: number | null;
  checked_at: string;
  trigger: CapabilityCheckTrigger;
  verdicts: Record<CredentialCapability, CapabilityVerdict>;
  check_results: CapabilityCheckResult[];
}

/** One stored row: the latest run for a credential and connector scope. */
export interface CapabilityReportSnapshot {
  credential_id: number;
  connector_id: number | null;
  source: ValidSources;
  trigger: CapabilityCheckTrigger;
  run_status: CapabilityReportRunStatus;
  run_started_at: string | null;
  connector_config_hash: string | null;
  /** `null` until a run completes. */
  report: CredentialCapabilityReport | null;
}

// ---------------------------------------------------------------------------
// Draft runs: checks on an unsaved connector form
// (`onyx.connectors.capability_checks.draft_runs`)
// ---------------------------------------------------------------------------

/**
 * State of one check in a draft run. `waiting` means a field the check reads
 * is missing or invalid; `not_applicable` means the access type or the form
 * excludes the check.
 */
export type DraftCheckState =
  | "pending"
  | "running"
  | "passed"
  | "failed"
  | "indeterminate"
  | "skipped"
  | "waiting"
  | "not_applicable";

/** `superseded`: a newer run for the same draft key replaced this one. */
export type DraftRunStatus =
  | "running"
  | "completed"
  | "superseded"
  | "failed_to_run";

export interface DraftCheck {
  check_id: string;
  display_name: string;
  capability: CredentialCapability;
  required: boolean;
  state: DraftCheckState;
  message: string;
  /** Config fields the check needs that the form does not provide yet. */
  missing_fields: string[];
  /** Config fields the check needs whose value is invalid. */
  invalid_fields: string[];
  remediation: string | null;
  docs_link: string | null;
  duration_ms: number | null;
  from_cache: boolean;
  /** The check proves the credential works with the credential-bound fields. */
  validates_binding: boolean;
}

export interface DraftCheckRunSnapshot {
  run_id: string;
  draft_key: string;
  source: ValidSources;
  credential_id: number;
  access_type: AccessType | null;
  status: DraftRunStatus;
  /** Config field name to its validation error. */
  form_errors: Record<string, string>;
  unknown_fields: string[];
  checks: DraftCheck[];
}

export interface DraftCheckRunRequest {
  source: ValidSources;
  credential_id: number;
  access_type: AccessType;
  /** One form session; a newer run with the same key supersedes the older. */
  draft_key: string;
  /** The `connector_specific_config` the create request would send. */
  form_state: Record<string, unknown>;
  /** Run checks whose cached result failed again instead of reusing it. */
  rerun_failed?: boolean;
}

/**
 * Whether the required checks let the connector be created:
 * - `pending`: a required check has not finished yet.
 * - `failed`: a required check failed, or waits on an invalid field.
 * - `ok`: no required check blocks creation.
 * - `unavailable`: the draft run could not run; creation runs the checks.
 */
export type RequiredChecksStatus = "pending" | "failed" | "ok" | "unavailable";
