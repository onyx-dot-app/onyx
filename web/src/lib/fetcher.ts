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
 * authentication errors (401/403). Pass this to any SWR hook whose endpoint
 * requires auth so that unauthenticated pages don't spam the backend.
 */
export const skipRetryOnAuthError: NonNullable<
  import("swr").SWRConfiguration["onErrorRetry"]
> = (error, _key, _config, revalidate, { retryCount }) => {
  if (
    error instanceof FetchError &&
    (error.status === 401 || error.status === 403)
  )
    return;
  // For non-auth errors, fall back to SWR's default exponential backoff.
  setTimeout(
    () => revalidate({ retryCount }),
    Math.min(retryCount * 5000, 30000)
  );
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
