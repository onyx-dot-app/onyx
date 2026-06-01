import { resolveAuthHeaders } from "./authHeaders";
import { FetchError, RedirectError } from "./errors";
import type { ClientConfig } from "./config";

// Mirrors web errorHandlingFetcher (same error semantics).
// Transport-neutral: instead of the global `fetch` it uses config.fetchImpl +
// config.getAuthHeaders + config.baseUrl, so the identical code runs on web
// (browser fetch + cookies) and mobile (expo/fetch + bearer PAT).

const DEFAULT_AUTH_ERROR_MSG =
  "An error occurred while fetching the data, related to the user's authentication status.";
const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

function resolveUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return path.startsWith("/") ? `${baseUrl}${path}` : `${baseUrl}/${path}`;
}

// Shared transport for both fetchers: merge auth headers under any caller-provided
// headers, issue the request, and apply the 403 -> RedirectError / !ok -> FetchError
// semantics. The success-body handling (json vs. void) is left to the caller.
async function fetchWithErrorHandling(
  url: string,
  config: ClientConfig,
  init?: RequestInit
): Promise<Response> {
  const headers = await resolveAuthHeaders(config, init?.headers);

  const res = await config.fetchImpl(resolveUrl(config.baseUrl, url), {
    ...init,
    headers,
  });

  if (res.status === 403) {
    throw new RedirectError(DEFAULT_AUTH_ERROR_MSG, res.status, await res.json());
  }
  if (!res.ok) {
    throw new FetchError(DEFAULT_ERROR_MSG, res.status, await res.json());
  }

  return res;
}

export async function errorHandlingFetcher<T>(
  url: string,
  config: ClientConfig,
  init?: RequestInit
): Promise<T> {
  const res = await fetchWithErrorHandling(url, config, init);
  return (await res.json()) as T;
}

/**
 * Same auth + error semantics as `errorHandlingFetcher`, but for endpoints that
 * return an empty body (HTTP 204) — it does NOT call `res.json()`, which would
 * throw "Unexpected end of JSON input" on a no-content response. Used for
 * DELETE routes like delete-project / unlink-file (backend returns 204).
 */
export async function errorHandlingFetcherVoid(
  url: string,
  config: ClientConfig,
  init?: RequestInit
): Promise<void> {
  await fetchWithErrorHandling(url, config, init);
}
