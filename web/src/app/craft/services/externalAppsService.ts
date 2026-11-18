/**
 * HTTP service for External Apps endpoints. UI components import from
 * here instead of calling `fetch` directly, so error shape + URL
 * construction live in one place.
 */

import { BUILD_API_BASE } from "@/app/craft/v1/constants";
import type { ErrorResponseBody } from "@/lib/fetcher";

async function readErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  const data: ErrorResponseBody = await res.json().catch(() => ({}));
  return data.detail ?? `${fallback} (HTTP ${res.status}).`;
}

export type ConnectAppDecision = "connected" | "declined";

/**
 * Resolve a parked `connect_app` request. The api-server is blocking the
 * agent's tool call on this decision: "connected" allows it, "declined" hands
 * the agent a rejection result so it can choose an alternative.
 */
export async function postConnectAppDecision(
  requestId: string,
  decision: ConnectAppDecision
): Promise<void> {
  const res = await fetch(
    `${BUILD_API_BASE}/apps/connect/${requestId}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }
  );
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, "Failed to resolve connection"));
  }
}
