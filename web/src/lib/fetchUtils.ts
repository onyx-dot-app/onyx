import type { ErrorResponseBody } from "@/lib/fetcher";

export async function getErrorMsg(response: Response): Promise<string | null> {
  if (response.ok) {
    return null;
  }
  const responseJson: ErrorResponseBody = await response.json();
  return responseJson.message || responseJson.detail || "Unknown error";
}
