import type { CaptureResult } from "posthog-js";

// Query parameters that carry a credential: the sign-in, verification and
// password-reset links put a single-use token in `token`.
const CREDENTIAL_PARAMS = ["token"];

// Event properties that hold a URL of this app.
const URL_PROPERTIES = [
  "$current_url",
  "$referrer",
  "$initial_current_url",
  "$initial_referrer",
  "$session_entry_url",
  "$session_entry_referrer",
];

const RELATIVE_BASE = "http://relative.invalid";

/** `url` with credential query values replaced, absolute or relative. */
export function redactUrl(url: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url, RELATIVE_BASE);
  } catch {
    return url;
  }
  const credentials = CREDENTIAL_PARAMS.filter((name) =>
    parsed.searchParams.has(name)
  );
  if (credentials.length === 0) return url;
  for (const name of credentials) parsed.searchParams.set(name, "redacted");
  if (parsed.origin === RELATIVE_BASE && !url.startsWith(RELATIVE_BASE)) {
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  }
  return parsed.toString();
}

/**
 * PostHog `before_send` hook: every event carries the page URL, so a
 * credential in the query would reach analytics with any event, not only
 * page views.
 */
export function redactEventUrls(
  event: CaptureResult | null
): CaptureResult | null {
  if (event === null) return null;
  for (const bag of [event.properties, event.$set, event.$set_once]) {
    if (!bag) continue;
    for (const key of URL_PROPERTIES) {
      const value: unknown = bag[key];
      if (typeof value === "string") bag[key] = redactUrl(value);
    }
  }
  return event;
}
