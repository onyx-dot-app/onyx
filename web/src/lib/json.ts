// Types for data decoded from JSON, such as a `JSON.parse` result or a stream
// packet. Narrow with the predicates and readers below instead of casting.

export type JsonPrimitive = string | number | boolean | null;

export type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;

export interface JsonObject {
  [key: string]: JsonValue;
}

export function isJsonObject(
  value: JsonValue | undefined
): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isJsonArray(
  value: JsonValue | undefined
): value is JsonValue[] {
  return Array.isArray(value);
}

// The backend sends some fields in both snake_case and camelCase, so each
// reader takes several keys. Like `a ?? b`, a reader uses the first key whose
// value is not null or undefined. It returns null when that value has a
// different type.
function firstSetValue(
  source: JsonObject,
  keys: string[]
): JsonValue | undefined {
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null) return value;
  }
  return undefined;
}

export function readString(
  source: JsonObject,
  ...keys: string[]
): string | null {
  const value = firstSetValue(source, keys);
  return typeof value === "string" ? value : null;
}

export function readNumber(
  source: JsonObject,
  ...keys: string[]
): number | null {
  const value = firstSetValue(source, keys);
  return typeof value === "number" ? value : null;
}

export function readObject(
  source: JsonObject,
  ...keys: string[]
): JsonObject | null {
  const value = firstSetValue(source, keys);
  return isJsonObject(value) ? value : null;
}

export function readArray(
  source: JsonObject,
  ...keys: string[]
): JsonValue[] | null {
  const value = firstSetValue(source, keys);
  return isJsonArray(value) ? value : null;
}
