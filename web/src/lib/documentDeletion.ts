import { toast } from "@opal/layouts";
import { ErrorResponseBody } from "@/lib/fetcher";
import { DeletionAttemptSnapshot } from "./types";

// Wire value of the backend code sent when the pair does not exist
// (`backend/onyx/error_handling/error_codes.py`).
export const CONNECTOR_NOT_FOUND_CODE = "CONNECTOR_NOT_FOUND";

export interface DeletionScheduleError {
  errorCode: string | undefined;
  detail: string;
}

export async function scheduleDeletionJobForConnector(
  connectorId: number,
  credentialId: number
): Promise<DeletionScheduleError | null> {
  // Will schedule a background job which will:
  // 1. Remove all documents indexed by the connector / credential pair
  // 2. Remove the connector (if this is the only pair using the connector)
  const response = await fetch(`/api/manage/admin/deletion-attempt`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      connector_id: connectorId,
      credential_id: credentialId,
    }),
  });
  if (response.ok) {
    return null;
  }
  const body: ErrorResponseBody = await response.json();
  return {
    errorCode: body.error_code,
    detail: body.detail ?? response.statusText,
  };
}

export async function deleteCCPair(
  connectorId: number,
  credentialId: number,
  onCompletion?: () => void
) {
  const deletionScheduleError = await scheduleDeletionJobForConnector(
    connectorId,
    credentialId
  );
  if (deletionScheduleError) {
    throw new Error(deletionScheduleError.detail);
  }
  toast.success("Scheduled deletion of connector!");
  onCompletion?.();
}

export function isCurrentlyDeleting(
  deletionAttempt: DeletionAttemptSnapshot | null
) {
  if (!deletionAttempt) {
    return false;
  }

  return (
    deletionAttempt.status === "PENDING" || deletionAttempt.status === "STARTED"
  );
}
