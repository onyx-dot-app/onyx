// Normalized API error model.
//
// The Onyx backend returns errors as `{ error_code, detail }` (the global
// OnyxError handler) or occasionally `{ detail }` / `{ message }`. `apiFetch`
// flattens whichever shape it gets into these typed fields so call sites never
// have to dig into a raw body. Mirrors the intent of web's `FetchError` while
// exposing `status`/`code`/`detail` as first-class fields.

interface ApiErrorArgs {
  status: number;
  code?: string;
  detail?: string;
  body?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail?: string;
  readonly body?: unknown;

  constructor({ status, code, detail, body }: ApiErrorArgs) {
    super(detail ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.body = body;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

// 401 (unauthenticated) / 403 (forbidden) — used both to skip retries and,
// later, to drive the router auth-gate. 402 is included for tier-gated routes,
// matching web's `skipRetryOnAuthError`.
export function isAuthError(error: unknown): boolean {
  return (
    isApiError(error) &&
    (error.status === 401 || error.status === 402 || error.status === 403)
  );
}

export function getErrorMessage(
  error: unknown,
  fallback = "Something went wrong.",
): string {
  if (isApiError(error)) return error.detail ?? error.message ?? fallback;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}
