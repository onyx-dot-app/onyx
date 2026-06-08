// Mirrors web fetcher.ts (FetchError + RedirectError). The SWR-coupled
// `skipRetryOnAuthError` helper stays in web; only these neutral classes move here.

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
