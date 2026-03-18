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

// Coalescing refresh gate: when multiple fetchers hit 403 simultaneously,
// only one refresh call is made and the others wait for it.
let refreshPromise: Promise<boolean> | null = null;

async function attemptTokenRefresh(): Promise<boolean> {
  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export const errorHandlingFetcher = async <T>(url: string): Promise<T> => {
  const res = await fetch(url);

  if (res.status === 403) {
    // Attempt a token refresh before giving up
    const refreshed = await attemptTokenRefresh();
    if (refreshed) {
      // Retry the original request with the new token
      const retryRes = await fetch(url);
      if (retryRes.ok) {
        return retryRes.json();
      }
      // Retry still failed — use retry response for error info
      throw new RedirectError(
        DEFAULT_AUTH_ERROR_MSG,
        retryRes.status,
        await retryRes.json().catch(() => ({}))
      );
    }

    // Refresh failed — use original response for error info
    throw new RedirectError(
      DEFAULT_AUTH_ERROR_MSG,
      res.status,
      await res.json().catch(() => ({}))
    );
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
