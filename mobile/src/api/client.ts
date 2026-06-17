// The single HTTP transport choke point. Every query/mutation goes through
// `apiFetch`, so base-URL resolution, auth-header injection, JSON
// (de)serialization, and error normalization all live in one place.
import { getBaseUrl } from "@/api/config";
import { getToken } from "@/api/auth/tokenStore";
import { ApiError } from "@/api/errors";

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  // Plain objects are JSON-serialized; pass a string/FormData to send as-is.
  body?: unknown;
  // Inject `Authorization: Bearer <token>` when a token exists. Default true;
  // set false for public endpoints.
  auth?: boolean;
}

function isBodyInit(body: unknown): body is BodyInit {
  return (
    typeof body === "string" ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof Blob ||
    body instanceof ArrayBuffer ||
    // Typed arrays / DataView (Uint8Array, etc.) — without this they'd be
    // JSON.stringified into `{"0":1,...}` and sent as application/json,
    // silently corrupting binary uploads. (ReadableStream is intentionally
    // omitted: RN's fetch doesn't support streamed request bodies.)
    ArrayBuffer.isView(body)
  );
}

async function buildHeaders(
  init: ApiFetchInit | undefined,
  hasJsonBody: boolean,
): Promise<Headers> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (hasJsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (init?.auth !== false) {
    const token = await getToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

// The Onyx backend returns errors in a few different JSON shapes depending on
// which handler caught the error (see backend/onyx/main.py +
// backend/onyx/error_handling). We normalize all of them into ApiError:
//
//   OnyxError (global handler):         { error_code: string, detail: string }
//   HTTPException (4xx/5xx log_http_error): { detail: string }   (detail may be non-string)
//   RequestValidationError (422):       { status_code, message: string, data: null }
//   ValueError (400):                   { message: string }
//   raw FastAPI validation (sub-apps):  { detail: [{ loc, msg, type }, ...] }
//   non-JSON / empty body:              no parseable body
//
// `error_code` (machine code) comes only from OnyxError; the human message
// lives in `detail` (string) or `message`, or — for raw FastAPI validation —
// in the joined `msg` fields of the `detail` array.
function extractErrorCode(record: Record<string, unknown>): string | undefined {
  return typeof record.error_code === "string" ? record.error_code : undefined;
}

function extractDetail(record: Record<string, unknown>): string | undefined {
  // OnyxError / HTTPException string detail.
  if (typeof record.detail === "string") return record.detail;
  // Onyx validation (422) / ValueError (400) use `message`.
  if (typeof record.message === "string") return record.message;
  // Raw FastAPI validation: detail is an array of { loc, msg, type } items.
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
    // Empty or non-JSON body (e.g. a proxy 502/504, or HTML error page).
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
  const { body, auth: _auth, ...rest } = init ?? {};

  const hasBody = body !== undefined && body !== null;
  const serializedBody: BodyInit | undefined = !hasBody
    ? undefined
    : isBodyInit(body)
      ? body
      : JSON.stringify(body);
  const hasJsonBody = hasBody && !isBodyInit(body);

  const headers = await buildHeaders(init, hasJsonBody);

  const res = await fetch(`${getBaseUrl()}${path}`, {
    ...rest,
    headers,
    body: serializedBody,
  });

  if (!res.ok) {
    throw await toApiError(res);
  }

  // 204 No Content / empty (or whitespace-only) body — resolve as undefined for
  // `Promise<void>` callers.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (text.trim().length === 0) {
    return undefined as T;
  }
  // Guard the parse the same way the error path does: a 2xx with a non-JSON body
  // (captive portal / proxy / maintenance HTML) would otherwise throw a raw
  // SyntaxError that escapes ApiError normalization (and gets needlessly retried).
  try {
    return JSON.parse(text) as T;
  } catch (parseError) {
    // Keep the user-facing detail clean, but preserve the original parser error
    // + raw text on `body` for observability (these would otherwise be lost).
    throw new ApiError({
      status: res.status,
      detail: `Expected a JSON response but received ${
        res.headers.get("content-type") ?? "an unknown content type"
      }.`,
      body: {
        responseText: text,
        parseError:
          parseError instanceof Error ? parseError.message : String(parseError),
      },
    });
  }
}
