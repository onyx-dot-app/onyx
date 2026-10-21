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
 * Outcome of one finished check. `incomplete` is a transient or unknown
 * failure and must not be read as proof the credential is broken.
 * `indeterminate` is its legacy value, still held by older stored results.
 */
export type CapabilityCheckStatus =
  | "passed"
  | "failed"
  | "incomplete"
  | "indeterminate"
  | "skipped";

/** What a discovery check lists, named by `CheckFindingKey` on the backend. */
export type CheckFindingKey =
  | "shared_drives"
  | "visible_organization_users"
  | "visible_spaces"
  | "readable_channels"
  | "readable_mailboxes"
  | "readable_drives";

/** One choice a listing offers a config field. */
export interface FindingOption {
  /** What the config field stores: an id or a URL. */
  value: string;
  /** What the admin reads. */
  label: string;
  detail: string | null;
}

export interface OptionsFinding {
  type: "options";
  key: CheckFindingKey;
  /** The config field the options are for. */
  field_name: string | null;
  options: FindingOption[];
  /** The listing stopped at the backend's option cap. */
  truncated: boolean;
}

export interface CountFinding {
  type: "count";
  key: CheckFindingKey;
  field_name: string | null;
  count: number;
  /** The listing stopped at a cap, so the real count is at least `count`. */
  at_least: boolean;
}

export type CheckFinding = OptionsFinding | CountFinding;

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
  /** What a passing discovery check listed. Empty for every other check. */
  findings: CheckFinding[];
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
  findings: CheckFinding[];
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
 * Body of `POST /manage/admin/cc-pair/{id}/edit/checks`: a dry run of the
 * checks on a proposed edit of the pair.
 */
export interface PairEditCheckRunRequest {
  connector_specific_config: Record<string, unknown>;
  access_type: AccessType;
  /** `null` keeps the pair's credential. */
  credential_id: number | null;
  rerun: DraftRerunMode;
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
