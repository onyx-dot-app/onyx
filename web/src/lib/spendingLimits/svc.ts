import { parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CardPath,
  SpendingLimitCard,
  SpendingLimitRequest,
} from "@/lib/spendingLimits/types";

/** Replaces every limit on one card. */
export async function saveSpendingLimitCard(
  path: CardPath,
  enabled: boolean,
  limits: SpendingLimitRequest[]
): Promise<SpendingLimitCard> {
  const response = await fetch(`${SWR_KEYS.spendingLimits}/${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, limits }),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, response.statusText));
  }
  return response.json();
}

/** Counts one limit's usage from now until its next reset. A group pool limit
 *  resets through its group's route, which group managers can use; every
 *  other limit needs an admin. Returns the limit's card. */
export async function resetSpendingLimitUsage(
  path: CardPath,
  limitId: number
): Promise<SpendingLimitCard> {
  const isGroupPool = path.startsWith("groups/") && path.endsWith("/pool");
  const route = isGroupPool
    ? `${path}/limits/${limitId}/reset-usage`
    : `limits/${limitId}/reset-usage`;
  const response = await fetch(`${SWR_KEYS.spendingLimits}/${route}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, response.statusText));
  }
  return response.json();
}
