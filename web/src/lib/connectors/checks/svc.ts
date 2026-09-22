import type { CapabilityReportSnapshot } from "@/lib/connectors/checks/types";

/** The stored report for a credential, scoped to a connector when given. */
export function capabilityReportUrl(
  credentialId: number,
  connectorId?: number | null
): string {
  const base = `/api/manage/admin/credential/${credentialId}/capability-report`;
  return connectorId == null ? base : `${base}?connector_id=${connectorId}`;
}

/**
 * Starts a capability-check run. The response is the row marked `running`;
 * poll `capabilityReportUrl` until `run_status` is `completed`.
 */
export async function runCapabilityCheck(
  credentialId: number,
  connectorId?: number | null
): Promise<CapabilityReportSnapshot> {
  const response = await fetch(
    `/api/manage/admin/credential/${credentialId}/capability-check`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        connectorId == null ? {} : { connector_id: connectorId }
      ),
    }
  );
  if (!response.ok) {
    throw new Error(`Capability check request failed: ${response.status}`);
  }
  return response.json();
}
