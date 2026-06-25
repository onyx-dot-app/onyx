// Probes a *candidate* URL via raw `fetch`; `apiFetch` is bound to the committed
// server URL and can't reach an unconfirmed instance.
import { getApiPrefix } from "@/api/config";
import type { AuthTypeMetadata } from "@/api/types";

export const ONYX_CLOUD_URL = "https://cloud.onyx.app";

const PROBE_TIMEOUT_MS = 10_000;

// Default to https only when no scheme given (keep explicit http:// for localhost).
export function normalizeServerUrl(input: string): string {
  const trimmed = input.trim();
  if (trimmed.length === 0) {
    throw new Error("Enter your Onyx instance URL.");
  }
  const withScheme = /^https?:\/\//i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    throw new Error("That doesn't look like a valid URL.");
  }
  if (!url.hostname) {
    throw new Error("That doesn't look like a valid URL.");
  }
  return `${url.origin}${url.pathname}`.replace(/\/+$/, "");
}

// Reject non-Onyx responses (captive portal, HTML error page) so we don't commit a dead URL.
function isAuthTypeMetadata(value: unknown): value is AuthTypeMetadata {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Record<string, unknown>).auth_type === "string"
  );
}

export async function probeAuthType(
  baseUrl: string,
): Promise<AuthTypeMetadata> {
  // fetch has no timeout option; abort after PROBE_TIMEOUT_MS so a dead host can't hang.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${baseUrl}${getApiPrefix()}/auth/type`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
  } catch {
    throw new Error("Couldn't reach an Onyx instance at that address.");
  } finally {
    clearTimeout(timeout);
  }

  if (!res.ok) {
    throw new Error("Couldn't reach an Onyx instance at that address.");
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }
  if (!isAuthTypeMetadata(body)) {
    throw new Error("That address doesn't look like an Onyx instance.");
  }
  return body;
}
