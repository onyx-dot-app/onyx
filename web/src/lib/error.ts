/**
 * Extract a human-readable error message from an SWR error object.
 * SWR errors from `errorHandlingFetcher` attach `info.message` or `info.detail`.
 */
export function getErrorMsg(
  error: { info?: { message?: string; detail?: string } } | null | undefined,
  fallback = "An unknown error occurred"
): string {
  return error?.info?.message || error?.info?.detail || fallback;
}
