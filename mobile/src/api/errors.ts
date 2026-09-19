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

// 401/403, plus 402 for tier-gated routes; skips retries and drives the auth-gate.
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
