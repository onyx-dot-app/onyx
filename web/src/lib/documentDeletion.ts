import { toast } from "@/hooks/useToast";
import { DeletionAttemptSnapshot } from "./types";

export async function scheduleDeletionJobForConnector(
  connectorId: number,
  credentialId: number
) {
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
  return (await response.json()).detail;
}

export async function deleteCCPair(
  connectorId: number,
  credentialId: number,
  onCompletion: () => void
) {
  const deletionScheduleError = await scheduleDeletionJobForConnector(
    connectorId,
    credentialId
  );
  if (deletionScheduleError) {
    toast.error(
      "Failed to schedule deletion of connector - " + deletionScheduleError
    );
  } else {
    toast.success("Scheduled deletion of connector!");
  }
  onCompletion();
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
