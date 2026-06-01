import { resolveAuthHeaders } from "./authHeaders";
import { FetchError, RedirectError } from "./errors";
import type { ClientConfig } from "./config";

// Mirrors web errorHandlingFetcher. Transport-neutral: uses config.fetchImpl +
// config.getAuthHeaders + config.baseUrl instead of the global `fetch`.

const DEFAULT_AUTH_ERROR_MSG =
  "An error occurred while fetching the data, related to the user's authentication status.";
const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

function resolveUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return path.startsWith("/") ? `${baseUrl}${path}` : `${baseUrl}/${path}`;
}

// Shared transport: merge auth headers, request, apply 403 -> RedirectError /
// !ok -> FetchError. Success-body handling (json vs. void) is left to the caller.
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

// Like errorHandlingFetcher but for 204 endpoints: skips res.json(), which would
// throw "Unexpected end of JSON input" on a no-content response (delete-project etc).
export async function errorHandlingFetcherVoid(
  url: string,
  config: ClientConfig,
  init?: RequestInit
): Promise<void> {
  await fetchWithErrorHandling(url, config, init);
}
