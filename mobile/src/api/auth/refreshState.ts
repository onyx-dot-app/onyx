// Split out of `sessionManager` so `api/client` can await an in-flight refresh without importing it back — a cycle.
import { getToken } from "@/api/auth/tokenStore";

let inFlightRefresh: Promise<string | null> | null = null;

export function getInFlightRefresh(): Promise<string | null> | null {
  return inFlightRefresh;
}

export function setInFlightRefresh(
  refresh: Promise<string | null> | null,
): void {
  inFlightRefresh = refresh;
}

/*
 * The token is opaque (not a JWT), so there's no expiry to check: "valid" only means not about to be replaced.
 * A failed refresh falls back to the stored token — one flaky refresh must not fail every concurrent request.
 */
export async function getValidToken(): Promise<string | null> {
  const pending = inFlightRefresh;
  if (pending) {
    try {
      return await pending;
    } catch {
      return getToken();
    }
  }
  return getToken();
}
