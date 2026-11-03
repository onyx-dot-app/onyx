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
