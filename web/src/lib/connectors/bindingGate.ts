/**
 * The decision that unlocks the create form's configuration. The
 * credential-bound fields (such as a site URL) sit above the credential
 * section, and the rest of the form waits until the credential and those
 * fields are a valid combination.
 */

import type { ValidSources } from "@/lib/connectors/types/source";

/** Body of `POST /manage/admin/credential/{id}/binding-check`. */
export interface CredentialBindingCheckRequest {
  source: ValidSources;
  connector_specific_config: Record<string, unknown>;
}

/**
 * Why the backend rejects one bound field. The form shows a catalog message
 * for `kind`. `detail` is English text from the backend validation; it shows
 * only inside the message for `invalid`, where no catalog text can name the
 * exact problem.
 */
export interface CredentialBindingFieldError {
  kind: "missing" | "invalid";
  detail: string;
}

/**
 * Why the credential cannot be used with valid bound fields. The form shows a
 * catalog message for `code`, with the English `detail` (for example, the
 * site the credential is for) inside it.
 */
export interface CredentialBindingRejection {
  code: "binding_rejected";
  detail: string;
}

/**
 * Response of the binding-check endpoint. The bound fields are valid with the
 * credential when there are no field errors and no rejection.
 */
export interface CredentialBindingCheckResponse {
  /** Bound field name to its error. */
  field_errors: Record<string, CredentialBindingFieldError>;
  rejection: CredentialBindingRejection | null;
}

/**
 * The binding check for the current credential and bound values:
 * - `idle`: no check for this input yet. A bound field must lose focus, or
 *   the credential must change, to start one.
 * - `checking`: a check for this input is scheduled or in flight.
 * - `done`: the backend answered for this input.
 * - `unavailable`: the request failed, or there is no credential to check.
 *   Creation checks the binding again, so this does not lock the form.
 */
export type BindingCheckState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "done"; response: CredentialBindingCheckResponse }
  | { kind: "unavailable" };

/** Why the configuration is locked, or is waiting for a check. */
export type BindingGateReason =
  | { kind: "enterField"; label: string }
  | { kind: "fixField"; label: string }
  | { kind: "selectCredential" }
  | { kind: "awaitingCheck" }
  | { kind: "checking" }
  | { kind: "fieldRejected"; label: string; error: CredentialBindingFieldError }
  | { kind: "rejected"; rejection: CredentialBindingRejection }
  /** A reason from an extra condition, already translated. */
  | { kind: "custom"; message: string };

export type BindingGateStatus = "locked" | "checking" | "unlocked";

export interface BindingGate {
  status: BindingGateStatus;
  /** `null` only when `status` is `unlocked`. */
  reason: BindingGateReason | null;
}

/** One visible credential-bound field, as the gate reads it. */
export interface BoundFieldState {
  name: string;
  label: string;
  /** Required and empty. */
  missing: boolean;
  /** Filled, but the form validation rejects the value. */
  invalid: boolean;
}

export interface BindingGateInput {
  /** The source shows credential-bound fields on the create form. */
  hasBoundFields: boolean;
  /** A credential is selected, or the source needs none. */
  credentialSelected: boolean;
  /** The visible bound fields, in form order. */
  boundFields: BoundFieldState[];
  binding: BindingCheckState;
  /**
   * One more condition, applied after the others pass. For example, checks
   * that prove the credential works with the bound fields.
   */
  extra?: BindingGate;
}

export const UNLOCKED_GATE: BindingGate = { status: "unlocked", reason: null };

function locked(reason: BindingGateReason): BindingGate {
  return { status: "locked", reason };
}

const CHECKING_GATE: BindingGate = {
  status: "checking",
  reason: { kind: "checking" },
};

/** True when the admin has not filled in the field `name` of `values`. */
export function isEmptyField(
  values: Record<string, unknown>,
  name: string
): boolean {
  const value = values[name];
  if (value === undefined || value === null) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/**
 * Decides whether the configuration is unlocked. Without bound fields, a
 * selected credential is enough. With bound fields, each must be filled in
 * and valid, and the backend must accept them with the credential. The extra
 * condition applies last in both cases.
 */
export function decideBindingGate(input: BindingGateInput): BindingGate {
  if (!input.hasBoundFields) {
    return input.credentialSelected
      ? (input.extra ?? UNLOCKED_GATE)
      : locked({ kind: "selectCredential" });
  }
  const missing = input.boundFields.find((field) => field.missing);
  if (missing) return locked({ kind: "enterField", label: missing.label });
  const invalid = input.boundFields.find((field) => field.invalid);
  if (invalid) return locked({ kind: "fixField", label: invalid.label });
  if (!input.credentialSelected) return locked({ kind: "selectCredential" });

  const { binding } = input;
  if (binding.kind === "idle") return locked({ kind: "awaitingCheck" });
  if (binding.kind === "checking") return CHECKING_GATE;
  if (binding.kind === "done") {
    const [rejectedName, fieldError] =
      Object.entries(binding.response.field_errors)[0] ?? [];
    if (rejectedName !== undefined && fieldError !== undefined) {
      const label =
        input.boundFields.find((field) => field.name === rejectedName)?.label ??
        rejectedName;
      return locked({ kind: "fieldRejected", label, error: fieldError });
    }
    if (binding.response.rejection !== null) {
      return locked({
        kind: "rejected",
        rejection: binding.response.rejection,
      });
    }
  }
  return input.extra ?? UNLOCKED_GATE;
}

/**
 * The bound values the binding check sends, and the key that identifies a
 * credential and those values. A response for another key is stale.
 */
export function bindingCheckInput(
  /** Names the credential; `null` when none is selected. */
  credentialKey: string | null,
  boundFieldNames: string[],
  values: Record<string, unknown>
): { key: string; config: Record<string, unknown> } {
  const config: Record<string, unknown> = {};
  for (const name of [...boundFieldNames].sort()) {
    if (values[name] !== undefined) config[name] = values[name];
  }
  return { key: JSON.stringify({ credentialKey, config }), config };
}
