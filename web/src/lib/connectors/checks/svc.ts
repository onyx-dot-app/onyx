import type {
  DraftCheckRunRequest,
  DraftCheckRunSnapshot,
} from "@/lib/connectors/checks/types";

/** A draft run's current snapshot; poll it while `status` is `running`. */
export function draftCheckRunUrl(runId: string): string {
  return `/api/manage/admin/connector-checks/runs/${runId}`;
}

/**
 * Starts the capability checks for an unsaved connector form. Checks that
 * cannot run yet come back resolved (waiting, not applicable); poll
 * `draftCheckRunUrl` for the rest.
 */
export async function startDraftCheckRun(
  request: DraftCheckRunRequest
): Promise<DraftCheckRunSnapshot> {
  const response = await fetch("/api/manage/admin/connector-checks/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Capability check run request failed: ${response.status}`);
  }
  return response.json();
}
