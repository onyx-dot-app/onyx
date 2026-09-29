import type { ValidSources } from "@/lib/types";

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
