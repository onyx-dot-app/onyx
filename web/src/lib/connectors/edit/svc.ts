import type { ErrorResponseBody } from "@/lib/fetcher";
import type { FileUploadResponse } from "@/lib/fileConnector";
import type {
  ConnectorEditApplyRequest,
  ConnectorEditApplyResponse,
  ConnectorEditPlanResponse,
  ConnectorEditProposal,
} from "@/lib/connectors/edit/types";

function editUrl(ccPairId: number, path: string): string {
  return `/api/manage/admin/cc-pair/${ccPairId}/edit/${path}`;
}

/** The error detail of a failed response, or its status when it has none. */
export async function errorDetailOf(response: Response): Promise<string> {
  try {
    const body: ErrorResponseBody = await response.json();
    return body.detail ?? body.message ?? `${response.status}`;
  } catch {
    return `${response.status}`;
  }
}

/**
 * Stages uploads for a file connector edit. Only an applied plan that
 * lists them indexes them. Pass the edit's metadata file id so that a
 * second zip merges into the first.
 */
export async function stageEditFiles(
  ccPairId: number,
  files: File[],
  draftZipMetadataFileId: string | null
): Promise<FileUploadResponse> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  if (draftZipMetadataFileId !== null) {
    formData.append("draft_zip_metadata_file_id", draftZipMetadataFileId);
  }
  const response = await fetch(editUrl(ccPairId, "files"), {
    method: "POST",
    body: formData,
  });
  if (!response.ok) throw new Error(await errorDetailOf(response));
  return response.json();
}

export type PlanEditOutcome =
  | { kind: "planned"; plan: ConnectorEditPlanResponse }
  | { kind: "error"; detail: string };

/** Computes and stores the plan for the proposed state. Writes nothing. */
export async function planConnectorEdit(
  ccPairId: number,
  proposal: ConnectorEditProposal
): Promise<PlanEditOutcome> {
  try {
    const response = await fetch(editUrl(ccPairId, "plan"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(proposal),
    });
    if (!response.ok) {
      return { kind: "error", detail: await errorDetailOf(response) };
    }
    return { kind: "planned", plan: await response.json() };
  } catch (error) {
    return { kind: "error", detail: String(error) };
  }
}

const EDIT_PLAN_STALE = "EDIT_PLAN_STALE";
// Apply gives NOT_FOUND for a plan that expired or was already applied.
const PLAN_NOT_FOUND = "NOT_FOUND";

/**
 * How an apply ended. `stale`: the pair changed after planning. `expired`:
 * the plan expired or was already applied. Both need a new plan.
 */
export type ApplyEditOutcome =
  | { kind: "applied"; response: ConnectorEditApplyResponse }
  | { kind: "stale"; detail: string }
  | { kind: "expired"; detail: string }
  | { kind: "error"; detail: string };

export async function applyConnectorEdit(
  ccPairId: number,
  request: ConnectorEditApplyRequest
): Promise<ApplyEditOutcome> {
  try {
    const response = await fetch(editUrl(ccPairId, "apply"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    if (response.ok) {
      return { kind: "applied", response: await response.json() };
    }
    let body: ErrorResponseBody = {};
    try {
      body = await response.json();
    } catch {
      // A body that is not JSON keeps the status as the detail.
    }
    const detail = body.detail ?? body.message ?? `${response.status}`;
    const stale =
      body.error_code === EDIT_PLAN_STALE ||
      (body.error_code === undefined && response.status === 409);
    if (stale) return { kind: "stale", detail };
    if (body.error_code === PLAN_NOT_FOUND) return { kind: "expired", detail };
    return { kind: "error", detail };
  } catch (error) {
    return { kind: "error", detail: String(error) };
  }
}
