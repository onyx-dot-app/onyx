import { isJsonObject, type JsonValue } from "@/lib/json";

const MAX_FIELDS = 8;
const MAX_FIELD_LENGTH = 120;

export type ToolField = [key: string, value: string];

/** A flat object of short strings, numbers and booleans as key/value rows,
 * or null for any other payload. */
export function flatFields(payload: JsonValue | undefined): ToolField[] | null {
  if (!isJsonObject(payload)) return null;
  const entries = Object.entries(payload);
  if (entries.length === 0 || entries.length > MAX_FIELDS) return null;
  const fields: ToolField[] = [];
  for (const [key, value] of entries) {
    if (typeof value === "number" || typeof value === "boolean") {
      fields.push([key, String(value)]);
    } else if (
      typeof value === "string" &&
      value.length <= MAX_FIELD_LENGTH &&
      !value.includes("\n")
    ) {
      fields.push([key, value]);
    } else {
      return null;
    }
  }
  return fields;
}

/** Whether a payload shows nothing: no value, blank text, `{}` or `[]`. */
export function isEmptyPayload(payload: JsonValue | undefined): boolean {
  if (payload === null || payload === undefined) return true;
  if (typeof payload === "string") return payload.trim() === "";
  if (Array.isArray(payload)) return payload.length === 0;
  if (typeof payload === "object") return Object.keys(payload).length === 0;
  return false;
}

/**
 * Whether a response only repeats the request: each of its fields has the same
 * key and value as a request field. Keys count, so `{count: 3}` after
 * `{limit: 3}` is a real answer.
 */
export function isEcho(
  response: ToolField[] | null,
  request: ToolField[] | null
): boolean {
  if (!response || !request) return false;
  const sent = new Set(request.map(([key, value]) => `${key}\u0000${value}`));
  return response.every(([key, value]) => sent.has(`${key}\u0000${value}`));
}
