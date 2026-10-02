import type {
  DraftCheck,
  DraftCheckRunSnapshot,
  RequiredChecksStatus,
} from "@/lib/connectors/checks/types";
import { UNLOCKED_GATE, type BindingGate } from "@/lib/connectors/bindingGate";

/** True once the run will not change any more. */
export function isDraftRunSettled(snapshot: DraftCheckRunSnapshot): boolean {
  return snapshot.status !== "running";
}

/**
 * A waiting check blocks creation only when it waits on an invalid field.
 * Creation fails such a check, but skips a check whose fields are missing.
 */
function blocksAsFailed(check: DraftCheck): boolean {
  return (
    check.state === "failed" ||
    (check.state === "waiting" && check.invalid_fields.length > 0)
  );
}

function isUnfinished(check: DraftCheck): boolean {
  return check.state === "pending" || check.state === "running";
}

/** Whether the required checks of a run let the connector be created. */
export function requiredChecksStatus(
  snapshot: DraftCheckRunSnapshot | null
): RequiredChecksStatus {
  if (snapshot === null) return "pending";
  const required = snapshot.checks.filter((check) => check.required);
  if (required.some(blocksAsFailed)) return "failed";
  if (snapshot.status === "failed_to_run") return "unavailable";
  if (snapshot.status !== "completed" || required.some(isUnfinished)) {
    return "pending";
  }
  return "ok";
}

/**
 * How the checks that prove the credential works with the credential-bound
 * fields (`validates_binding`) stand in a run. Only required checks that
 * apply count; `indeterminate` counts as passed.
 * - `none`: the run has no such check.
 * - `unavailable`: the run could not run; creation runs the checks.
 */
export type BindingChecksVerdict =
  | "none"
  | "passed"
  | "checking"
  | "failed"
  | "unavailable";

export function bindingChecksVerdict(
  snapshot: DraftCheckRunSnapshot
): BindingChecksVerdict {
  if (snapshot.status === "failed_to_run") return "unavailable";
  const checks = snapshot.checks.filter(
    (check) =>
      check.validates_binding === true &&
      check.required &&
      check.state !== "not_applicable" &&
      check.state !== "skipped"
  );
  if (checks.length === 0) return "none";
  if (checks.some(blocksAsFailed)) return "failed";
  if (
    checks.every(
      (check) => check.state === "passed" || check.state === "indeterminate"
    )
  ) {
    return "passed";
  }
  return "checking";
}

export interface BindingChecksGateInput {
  /** The shown run, or `null` before the first run. */
  snapshot: DraftCheckRunSnapshot | null;
  /** The shown run had the current credential and bound values. */
  current: boolean;
  /** The binding checks passed before for the current credential and bound values. */
  passedBefore: boolean;
  /** The draft-run request failed; creation runs the checks. */
  requestFailed: boolean;
  /** The translated reason for a failed binding check. */
  failedMessage: string;
}

/**
 * The create form's extra unlock condition: the binding checks passed for
 * the current credential and bound values. A later run for other config
 * values keeps an earlier pass unless a binding check fails.
 */
export function bindingChecksGate({
  snapshot,
  current,
  passedBefore,
  requestFailed,
  failedMessage,
}: BindingChecksGateInput): BindingGate {
  if (requestFailed) return UNLOCKED_GATE;
  const verdict =
    current && snapshot !== null ? bindingChecksVerdict(snapshot) : "checking";
  if (verdict === "failed") {
    return {
      status: "locked",
      reason: { kind: "custom", message: failedMessage },
    };
  }
  if (verdict === "checking" && !passedBefore) {
    return { status: "checking", reason: { kind: "checking" } };
  }
  return UNLOCKED_GATE;
}
