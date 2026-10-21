import type { ActivityGroup } from "@/lib/connectors/ccPair/hooks";
import type { CCPairRun } from "@/lib/connectors/types";

/** Whether a closed run was resolved, by Retry or by an admin, rather than superseded by a newer run of its kind. The errors level closes a run only by resolving it. */
export function closedByResolution(
  run: Pick<CCPairRun, "resolved_at">,
  group: ActivityGroup
): boolean {
  return group === "errors" || run.resolved_at !== null;
}
