import type {
  DraftCheckPlan,
  DraftCheckPlanRequest,
  DraftCheckRunRequest,
  DraftCheckRunSnapshot,
} from "@/lib/connectors/checks/types";

/**
 * Starts the capability checks for an unsaved connector form. Checks that
 * cannot run yet come back resolved (waiting, not applicable); poll
 * `SWR_KEYS.connectorCheckRun` for the rest.
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

/**
 * Lists the checks a run would hold for an unsaved connector form, without a
 * credential and without running anything.
 */
export async function fetchDraftCheckPlan(
  request: DraftCheckPlanRequest
): Promise<DraftCheckPlan> {
  const response = await fetch("/api/manage/admin/connector-checks/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Capability check plan request failed: ${response.status}`);
  }
  return response.json();
}
