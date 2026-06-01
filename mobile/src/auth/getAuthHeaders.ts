// The auth seam plugged into ClientConfig.getAuthHeaders. Mobile attaches the stored
// JWT as a Bearer token; web returns {} because it rides cookies instead.
import { getToken } from "./secureStore";

// Return `{}` (rather than throw) when signed out so the request proceeds and surfaces
// a real 401/403, which the app's auth-error handling turns into sign-out + redirect.
export async function getAuthHeaders(): Promise<HeadersInit> {
  const jwt = await getToken();
  if (!jwt) return {};
  return { Authorization: `Bearer ${jwt}` };
}
