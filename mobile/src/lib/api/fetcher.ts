import { FetchError, RedirectError } from "./errors";
import type { ClientConfig } from "./config";

// Transport-neutral port of web's errorHandlingFetcher (web/src/lib/fetcher.ts).
// Same error semantics (403 -> RedirectError, other !ok -> FetchError, else res.json()),
// but instead of the global `fetch` it uses config.fetchImpl + config.getAuthHeaders +
// config.baseUrl — so the identical code runs on web (browser fetch + cookies) and
// mobile (expo/fetch + bearer PAT).

const DEFAULT_AUTH_ERROR_MSG =
  "An error occurred while fetching the data, related to the user's authentication status.";
const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

function resolveUrl(baseUrl: string, path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return path.startsWith("/") ? `${baseUrl}${path}` : `${baseUrl}/${path}`;
}

export async function errorHandlingFetcher<T>(
  url: string,
  config: ClientConfig,
  init?: RequestInit
): Promise<T> {
  // Merge auth headers under any caller-provided headers (any HeadersInit shape).
  const headers = new Headers(init?.headers);
  new Headers(await config.getAuthHeaders()).forEach((value, key) => {
    headers.set(key, value);
  });

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

  return (await res.json()) as T;
}
