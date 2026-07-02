export class FetchError extends Error {
  status: number;
  info: any;
  constructor(message: string, status: number, info: any) {
    super(message);
    this.status = status;
    this.info = info;
  }
}

export class RedirectError extends FetchError {
  constructor(message: string, status: number, info: any) {
    super(message, status, info);
  }
}

const DEFAULT_AUTH_ERROR_MSG =
  "An error occurred while fetching the data, related to the user's authentication status.";

const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

/**
 * SWR `onErrorRetry` callback that suppresses automatic retries for
 * auth or tier-gated errors (401/402/403). Pass this to any SWR hook whose
 * endpoint requires auth or a specific tier so that unauthenticated /
 * under-tier pages don't spam the backend with retries.
 */
export const skipRetryOnAuthError: NonNullable<
  import("swr").SWRConfiguration["onErrorRetry"]
> = (error, _key, _config, revalidate, { retryCount }) => {
  if (
    error instanceof FetchError &&
    (error.status === 401 || error.status === 402 || error.status === 403)
  )
    return;
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

export const errorHandlingFetcher = async <T>(url: string): Promise<T> => {
  const res = await fetch(url);

  if (res.status === 403) {
    const redirect = new RedirectError(
      DEFAULT_AUTH_ERROR_MSG,
      res.status,
      await res.json()
    );
    throw redirect;
  }

  if (!res.ok) {
    const error = new FetchError(
      DEFAULT_ERROR_MSG,
      res.status,
      await res.json()
    );
    throw error;
  }

  return res.json();
};
