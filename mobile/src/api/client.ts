import { getBaseUrl } from "@/api/config";
import { getValidToken } from "@/api/auth/refreshState";
import { getToken } from "@/api/auth/tokenStore";
import { ApiError } from "@/api/errors";

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  // Plain objects are JSON-serialized; pass a string/FormData to send as-is.
  body?: unknown;
  // "stored" skips the wait on an in-flight refresh, so `refreshToken` doesn't await its own promise.
  auth?: boolean | "stored";
  // Includes credential resolution and reading the response body.
  timeoutMs?: number;
}

function isBodyInit(body: unknown): body is BodyInit {
  return (
    typeof body === "string" ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof Blob ||
    body instanceof ArrayBuffer ||
    /*
     * Typed arrays would otherwise be JSON.stringified into `{"0":1,...}`, corrupting binary
     * uploads. ReadableStream is left out: RN fetch can't stream request bodies.
     */
    ArrayBuffer.isView(body)
  );
}

export async function buildHeaders(
  init: ApiFetchInit | undefined,
  hasJsonBody: boolean,
): Promise<Headers> {
  const signal = init?.signal;
  const aborted = new Error("Request cancelled");
  aborted.name = "AbortError";
  if (signal?.aborted) throw aborted;
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (hasJsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (init?.auth !== false) {
    const credentials = init?.auth === "stored" ? getToken() : getValidToken();
    // Cancel this request's wait without cancelling the shared token refresh.
    const token = await (signal
      ? new Promise<string | null>((resolve, reject) => {
          const onAbort = () => reject(aborted);
          signal.addEventListener("abort", onAbort, { once: true });
          void credentials
            .then(resolve, reject)
            .finally(() => signal.removeEventListener("abort", onAbort));
        })
      : credentials);
    if (signal?.aborted) throw aborted;
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

function extractErrorCode(record: Record<string, unknown>): string | undefined {
  return typeof record.error_code === "string" ? record.error_code : undefined;
}

function extractDetail(record: Record<string, unknown>): string | undefined {
  if (typeof record.detail === "string") return record.detail;
  if (typeof record.message === "string") return record.message;
  // Raw FastAPI validation: array of { loc, msg, type }.
  if (Array.isArray(record.detail)) {
    const messages = record.detail
      .map((item) =>
        item && typeof item === "object"
          ? (item as Record<string, unknown>).msg
          : undefined,
      )
      .filter((msg): msg is string => typeof msg === "string");
    if (messages.length > 0) return messages.join("; ");
  }
  return undefined;
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }
  const record =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  return new ApiError({
    status: res.status,
    code: extractErrorCode(record),
    detail: extractDetail(record),
    body,
  });
}

export async function apiFetch<T>(
  path: string,
  init?: ApiFetchInit,
): Promise<T> {
  const {
    body,
    auth: _auth,
    timeoutMs,
    signal: callerSignal,
    ...rest
  } = init ?? {};
  const controller =
    timeoutMs === undefined ? undefined : new AbortController();
  const abort = () => controller?.abort();
  if (callerSignal?.aborted) abort();
  else if (controller)
    callerSignal?.addEventListener("abort", abort, { once: true });
  const timeout = controller ? setTimeout(abort, timeoutMs) : undefined;
  const signal = controller?.signal ?? callerSignal;

  try {
    const hasBody = body !== undefined && body !== null;
    const serializedBody: BodyInit | undefined = !hasBody
      ? undefined
      : isBodyInit(body)
        ? body
        : JSON.stringify(body);
    const hasJsonBody = hasBody && !isBodyInit(body);

    const headers = await buildHeaders({ ...init, signal }, hasJsonBody);

    const res = await fetch(`${getBaseUrl()}${path}`, {
      ...rest,
      headers,
      body: serializedBody,
      signal,
    });

    if (!res.ok) {
      throw await toApiError(res);
    }

    if (res.status === 204) {
      return undefined as T;
    }
    const text = await res.text();
    if (text.trim().length === 0) {
      return undefined as T;
    }
    // Without this, a non-JSON 2xx body throws a raw SyntaxError that escapes ApiError and gets retried.
    try {
      return JSON.parse(text) as T;
    } catch (parseError) {
      throw new ApiError({
        status: res.status,
        detail: `Expected a JSON response but received ${
          res.headers.get("content-type") ?? "an unknown content type"
        }.`,
        body: {
          responseText: text,
          parseError:
            parseError instanceof Error
              ? parseError.message
              : String(parseError),
        },
      });
    }
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
    if (controller) callerSignal?.removeEventListener("abort", abort);
  }
}
