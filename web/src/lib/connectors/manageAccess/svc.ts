import { parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairManageAccessEntry,
  CCPairManageAccessRow,
} from "@/lib/connectors/manageAccess/types";

/**
 * Replaces the stored manage rows of a cc-pair. Fixed rows are not stored, so
 * leave them out. The server keeps rows of groups the caller cannot see.
 */
export async function setCCPairManageAccess(
  ccPairId: number,
  manageAccess: CCPairManageAccessEntry[],
  fallbackError: string
): Promise<CCPairManageAccessRow[]> {
  const response = await fetch(SWR_KEYS.ccPairManageAccess(ccPairId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manage_access: manageAccess }),
  });
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response, fallbackError));
  }
  const rows: CCPairManageAccessRow[] = await response.json();
  return rows;
}
