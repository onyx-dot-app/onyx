import type { CredentialRequest } from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { AccessType } from "@/lib/types";

/**
 * Mirrors the backend's capability-check models
 * (`onyx.connectors.capability_checks`), and the draft runs that
 * `/manage/admin/connector-checks/runs` serves for an unsaved connector form.
 */

/** What a credential may be able to do for its source. */
export type CredentialCapability =
  | "indexing"
  | "doc_permission_sync"
  | "external_group_sync";

/**
 * Outcome of one finished check. `indeterminate` is a transient or unknown
 * failure and must not be read as proof the credential is broken.
 */
export type CapabilityCheckStatus =
  | "passed"
  | "failed"
  | "indeterminate"
  | "skipped";

/** One finished check, as the checks card shows it. */
export interface CapabilityCheckResult {
  capability: CredentialCapability;
  check_id: string;
  display_name: string;
  /** A required check that fails blocks the capability. */
  required: boolean;
  status: CapabilityCheckStatus;
  /** Failure text, skip reason, or empty on success. */
  message: string;
  remediation: string | null;
  docs_link: string | null;
  duration_ms: number | null;
}

/** A check's state in a draft run. */
export type DraftCheckStateKind =
  | CapabilityCheckStatus
  | "pending"
  | "running"
  /** A required form field is missing or invalid; it runs once it is valid. */
  | "waiting"
  /** The access type or the check's own rule excludes it. */
  | "not_applicable";

export type DraftRunStatus =
  | "running"
  | "completed"
  /** A newer run for the same draft key replaced this one. */
  | "superseded"
  | "failed_to_run";

/**
 * Where the connector checks stand for the current form, as the checks card,
 * the configuration lock and the Connect button see them.
 */
export type ConnectorChecksStatus =
  /** No run yet: the Start Checks prompt shows. */
  | "notStarted"
  /** A run is starting or in flight. */
  | "running"
  /** The run completed, and no required check that could run is blocking. */
  | "passed"
  /** The run completed, and a required check failed or is unverified. */
  | "failed"
  /** The run itself broke: it could not start, crashed, or its worker died. */
  | "failedToRun";

/** Which cached results a new draft run ignores. */
export type DraftRerunMode = "none" | "failed" | "all";

export interface DraftCheckState {
  check_id: string;
  display_name: string;
  capability: CredentialCapability;
  required: boolean;
  state: DraftCheckStateKind;
  message: string;
  missing_fields: string[];
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
  /** The saved credential, or the draft that the run saved typed values in. */
  credential_id: number;
  access_type: AccessType | null;
  status: DraftRunStatus;
  /** Field name to error message, for the form. */
  form_errors: Record<string, string>;
  unknown_fields: string[];
  checks: DraftCheckState[];
}

/**
 * The checks a draft run would hold for a form, each in its state before
 * anything runs: pending, waiting or not applicable.
 */
export interface DraftCheckPlan {
  source: ValidSources;
  access_type: AccessType | null;
  form_errors: Record<string, string>;
  unknown_fields: string[];
  checks: DraftCheckState[];
}

/** Body of `POST /manage/admin/connector-checks/plan`. Needs no credential. */
export interface DraftCheckPlanRequest {
  source: ValidSources;
  access_type: AccessType | null;
  form_state: Record<string, unknown>;
}

/**
 * Body of `POST /manage/admin/connector-checks/runs`: a run on a saved
 * credential, or on a typed account, which the run saves as a draft.
 */
export type DraftCheckRunRequest = CredentialRequest & {
  source: ValidSources;
  access_type: AccessType | null;
  /** One form session. A new run for the same key supersedes the last. */
  draft_key: string;
  form_state: Record<string, unknown>;
  rerun: DraftRerunMode;
};
