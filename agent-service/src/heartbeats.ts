import { z } from "zod";

export interface RunLease {
  runId: string;
  attemptId: string;
}

/** Refresh tenant-scoped leases in a single API/database operation per batch. */
export async function heartbeatBatch(
  root: string,
  token: string,
  tenantId: string,
  runs: RunLease[],
) {
  const response = await fetch(`${root}/heartbeats`, {
    method: "POST",
    redirect: "error",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Onyx-Tenant-Id": tenantId,
    },
    body: JSON.stringify({ runs }),
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok)
    throw new Error(`Agent heartbeat failed (${response.status})`);
  return z
    .object({ cancelled: z.array(z.string()) })
    .parse(await response.json()).cancelled;
}
