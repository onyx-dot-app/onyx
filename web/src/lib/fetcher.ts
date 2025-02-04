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
