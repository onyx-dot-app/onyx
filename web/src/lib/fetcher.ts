import type { EndpointLineError } from "@/lib/integrations/types";

/** JSON body of a backend error response. `OnyxError` and the request
 * validation handler both send `error_code` and a string `detail`; the
 * validation and `ValueError` handlers also send `message`. */
export interface ErrorResponseBody {
  detail?: string;
  error_code?: string;
  message?: string;
  line_errors?: EndpointLineError[];
}

export class FetchError extends Error {
  status: number;
  info: ErrorResponseBody | null;
  constructor(message: string, status: number, info: ErrorResponseBody | null) {
    super(message);
    this.status = status;
    this.info = info;
  }
}

export class RedirectError extends FetchError {
  constructor(message: string, status: number, info: ErrorResponseBody | null) {
    super(message, status, info);
  }
}

/** Extract the backend error `detail` from a failed Response, falling back
 * to `fallback` when the body isn't JSON or carries no text detail. */
export async function parseErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  const body: unknown = await res.json().catch((): null => null);
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string" &&
    body.detail !== ""
  ) {
    return body.detail;
  }
  return fallback;
}

/** A `FetchError` for a failed Response, keeping its JSON body when it has one. */
export async function fetchErrorFrom(
  res: Response,
  message: string
): Promise<FetchError> {
  const info: ErrorResponseBody | null = await res
    .json()
    .catch((): null => null);
  return new FetchError(message, res.status, info);
}

/** The backend's text `detail` of a failed request; `null` when it gave none. */
export function fetchErrorDetail(error: unknown): string | null {
  if (!(error instanceof FetchError)) return null;
  const detail: unknown = error.info?.detail;
  return typeof detail === "string" && detail !== "" ? detail : null;
}

const DEFAULT_AUTH_ERROR_MSG =
  "An error occurred while fetching the data, related to the user's authentication status.";

const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

export function isAuthStatusError(error: unknown): boolean {
  return (
    error instanceof FetchError &&
    (error.status === 401 || error.status === 402 || error.status === 403)
  );
}

export function isNotFoundError(error: unknown): boolean {
  return error instanceof FetchError && error.status === 404;
}

/**
 * SWR `onErrorRetry` callback that suppresses automatic retries for
 * auth or tier-gated errors (401/402/403). Pass this to any SWR hook whose
 * endpoint requires auth or a specific tier so that unauthenticated /
 * under-tier pages don't spam the backend with retries.
 */
export const skipRetryOnAuthError: NonNullable<
  import("swr").SWRConfiguration["onErrorRetry"]
> = (error, _key, _config, revalidate, { retryCount }) => {
  if (isAuthStatusError(error)) return;
  // For non-auth errors, retry with exponential backoff
  if (
    _config.errorRetryCount !== undefined &&
    retryCount >= _config.errorRetryCount
  )
    return;
  const delay = Math.min(2000 * 2 ** retryCount, 30000);
  setTimeout(() => {
    if (typeof document === "undefined" || !document.hidden) {
      revalidate({ retryCount });
      return;
    }
    // Hidden at retry time: defer until the tab is visible again, so hidden
    // tabs stay quiet without permanently dropping the retry chain (which
    // would strand consumers that disable revalidateOnFocus).
    const retryOnVisible = () => {
      if (document.hidden) return;
      document.removeEventListener("visibilitychange", retryOnVisible);
      revalidate({ retryCount });
    };
    document.addEventListener("visibilitychange", retryOnVisible);
  }, delay);
};

async function parseFetcherResponse<T>(res: Response): Promise<T> {
  if (res.status === 403) {
    const error = await fetchErrorFrom(res, DEFAULT_AUTH_ERROR_MSG);
    throw new RedirectError(
      fetchErrorDetail(error) ?? error.message,
      error.status,
      error.info
    );
  }

  if (!res.ok) {
    const error = await fetchErrorFrom(res, DEFAULT_ERROR_MSG);
    error.message = fetchErrorDetail(error) ?? error.message;
    throw error;
  }

  if (res.status === 204) {
    // SAFETY: a 204 has no body; callers of a no-content endpoint type T as null.
    return null as T;
  }
  return res.json();
}

// One argument only: SWR spreads an array key into its fetcher's arguments.
export const errorHandlingFetcher = async <T>(url: string): Promise<T> =>
  parseFetcherResponse<T>(await fetch(url));

/** `errorHandlingFetcher` with request options, such as an abort signal. */
export async function errorHandlingFetchWith<T>(
  url: string,
  init: RequestInit
): Promise<T> {
  return parseFetcherResponse<T>(await fetch(url, init));
}
