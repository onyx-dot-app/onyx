import { API_TOKENS_URL } from "@/lib/api-tokens/constants";
import type { ApiTokenView } from "@/lib/api-tokens/types";
import { parseErrorDetail } from "@/lib/fetcher";

/** Replaces a saved key's value. Every feature that uses it gets the new value. */
export async function rotateApiToken(
  tokenId: number,
  value: string
): Promise<ApiTokenView> {
  const response = await fetch(`${API_TOKENS_URL}/${tokenId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!response.ok) {
    throw new Error(
      await parseErrorDetail(response, "Failed to update API key")
    );
  }
  return response.json();
}
