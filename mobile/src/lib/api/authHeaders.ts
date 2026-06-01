// Shared auth-header merge. Several transports (fetcher, sendMessage, files) all
// need to layer `config.getAuthHeaders()` (mobile: a bearer PAT; web: {}) on top
// of any caller-provided headers. This centralizes that merge so the
// `new Headers(await config.getAuthHeaders()).forEach(...)` dance lives in one place.

import type { ClientConfig } from "./config";

/**
 * Build a `Headers` from `init?.headers` (any HeadersInit shape) with the
 * platform auth headers merged in on top (auth wins on key collisions).
 */
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

/**
 * Record variant of {@link resolveAuthHeaders} for APIs that take a plain
 * `Record<string, string>` rather than a `Headers` (e.g. expo-file-system
 * `uploadAsync`'s `headers` option).
 */
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
