import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CardPath,
  SpendingLimitCard,
  SpendingLimitRequest,
} from "@/lib/spendingLimits/types";

async function errorDetail(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (body && typeof body === "object" && "detail" in body) {
    return String(body.detail);
  }
  return response.statusText;
}

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
    throw new Error(await errorDetail(response));
  }
  return response.json();
}

export async function deleteGroupSpendingLimits(
  groupId: number
): Promise<void> {
  const response = await fetch(`${SWR_KEYS.spendingLimits}/groups/${groupId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await errorDetail(response));
  }
}
