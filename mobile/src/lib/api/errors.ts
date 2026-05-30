// Ported verbatim from web/src/lib/fetcher.ts (FetchError + RedirectError).
// The SWR-coupled `skipRetryOnAuthError` helper stays in web (it references swr's
// SWRConfiguration); only these framework-neutral error classes move into the package.

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
