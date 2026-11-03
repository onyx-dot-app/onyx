import type { CCPairRun } from "@/lib/connectors/types";

/** Whether a closed run left its open level only because a newer run of its kind superseded it. A run that Retry or an admin resolved reads as resolved. */
export function closedBySupersede(
  run: Pick<CCPairRun, "resolved_at" | "superseded">
): boolean {
  return run.superseded && run.resolved_at === null;
}
