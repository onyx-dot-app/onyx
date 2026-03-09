/**
 * Extract a human-readable error message from an SWR error object.
 * SWR errors from `errorHandlingFetcher` attach `info.detail` (OnyxError / HTTPException).
 */
export function getErrorMsg(
  error: { info?: { detail?: string; message?: string } } | null | undefined,
  fallback = "An unknown error occurred"
): string {
  return error?.info?.detail || error?.info?.message || fallback;
}
