import { parseErrorDetail, type ErrorResponseBody } from "@/lib/fetcher";
import {
  ConnectorCredentialPairStatus,
  type CCPairRunKind,
  type CCPairRunLevel,
} from "@/lib/connectors/types";
import { toast } from "@opal/layouts";

export async function setCCPairStatus(
  ccPairId: number,
  ccPairStatus: ConnectorCredentialPairStatus,
  onUpdate?: () => void
) {
  try {
    const response = await fetch(
      `/api/manage/admin/cc-pair/${ccPairId}/status`,
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ status: ccPairStatus }),
      }
    );

    if (!response.ok) {
      const { detail }: ErrorResponseBody = await response.json();
      toast.error(`Failed to update connector status - ${detail}`);
      return;
    }

    toast.success(
      ccPairStatus === ConnectorCredentialPairStatus.ACTIVE
        ? "Enabled connector!"
        : "Paused connector!"
    );

    onUpdate?.();
  } catch (error) {
    console.error("Error updating CC pair status:", error);
    toast.error("Failed to update connector status");
  }
}

export const getCCPairStatusMessage = (
  isDisabled: boolean,
  isIndexing: boolean,
  ccPairStatus: ConnectorCredentialPairStatus
) => {
  if (ccPairStatus === ConnectorCredentialPairStatus.INVALID) {
    return "Connector is in an invalid state. Please update the credentials or configuration before re-indexing.";
  }
  if (ccPairStatus === ConnectorCredentialPairStatus.DELETING) {
    return "Cannot index while connector is deleting";
  }
  if (isIndexing) {
    return "Indexing is already in progress";
  }
  if (isDisabled) {
    return "Connector must be re-enabled before indexing";
  }
  return undefined;
};

/** Marks these runs of the pair resolved. They keep their status; the feeds move them out of the open failures and errors. */
export async function resolveCCPairRuns(
  ccPairId: number,
  runs: { kind: CCPairRunKind; attempt_id: number }[]
): Promise<void> {
  const response = await fetch(
    `/api/manage/admin/cc-pair/${ccPairId}/runs/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ runs }),
    }
  );
  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, `HTTP ${response.status}`)
    );
  }
}

/** The open runs of one activity level, or of every level when `level` is null, narrowed as the runs feed narrows them. */
export interface CCPairRunsMatchingFilter {
  level: CCPairRunLevel | null;
  q: string | null;
  since: string | null;
  until: string | null;
  kinds: CCPairRunKind[] | null;
}

export interface CCPairRunsResolveMatchingResponse {
  resolved_count: number;
  /** The pairs that had a run marked. */
  cc_pair_ids: number[];
}

/** Marks every open run the filter matches resolved, on the pair or, for null, on every pair the caller operates. */
export async function resolveMatchingRuns(
  ccPairId: number | null,
  filter: CCPairRunsMatchingFilter
): Promise<CCPairRunsResolveMatchingResponse> {
  const response = await fetch(
    ccPairId === null
      ? "/api/manage/admin/index-monitoring/runs/resolve"
      : `/api/manage/admin/cc-pair/${ccPairId}/runs/resolve-matching`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(filter),
    }
  );
  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, `HTTP ${response.status}`)
    );
  }
  return response.json();
}
