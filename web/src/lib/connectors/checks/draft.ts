import type {
  DraftCheck,
  DraftCheckRunSnapshot,
  RequiredChecksStatus,
} from "@/lib/connectors/checks/types";

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
