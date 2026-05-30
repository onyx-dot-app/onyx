// The auth seam the integrator plugs into ClientConfig.getAuthHeaders.
//
// errorHandlingFetcher (and the streaming reader) call this once per request and
// merge the result into the outgoing headers. On mobile that means attaching the
// stored JWT as a Bearer token; web returns {} because it rides cookies instead.
//
// Signature is intentionally fixed at `() => Promise<HeadersInit>` — query/client
// imports it by reference, so it must stay shape-compatible.
import { getToken } from "./secureStore";

/**
 * Resolve the per-request auth headers: a Bearer JWT if signed in, else `{}`.
 *
 * Returning `{}` (rather than throwing) when there's no token lets unauthenticated
 * requests proceed and surface a real 401/403 from the backend, which the app's
 * auth-error handling turns into a sign-out + redirect to login.
 */
export async function getAuthHeaders(): Promise<HeadersInit> {
  const jwt = await getToken();
  if (!jwt) return {};
  return { Authorization: `Bearer ${jwt}` };
}
