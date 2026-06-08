// Shared auth-header merge: layers config.getAuthHeaders() (mobile: bearer PAT;
// web: {}) on top of any caller-provided headers, in one place.

import type { ClientConfig } from "./config";

// Auth headers win on key collisions.
export async function resolveAuthHeaders(
  config: ClientConfig,
  init?: HeadersInit
): Promise<Headers> {
  const headers = new Headers(init);
  new Headers(await config.getAuthHeaders()).forEach((value, key) => {
    headers.set(key, value);
  });
  return headers;
}

// Record variant for APIs that take a plain Record rather than Headers (e.g.
// expo-file-system uploadAsync's `headers` option).
export async function resolveAuthHeadersRecord(
  config: ClientConfig,
  init?: HeadersInit
): Promise<Record<string, string>> {
  const record: Record<string, string> = {};
  (await resolveAuthHeaders(config, init)).forEach((value, key) => {
    record[key] = value;
  });
  return record;
}
