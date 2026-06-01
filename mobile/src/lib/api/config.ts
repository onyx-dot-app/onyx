// ClientConfig — the platform seam that keeps this package transport-neutral.
// The ONLY platform differences are the fetch implementation and how auth is carried:
//   - web:    fetchImpl = browser `fetch`, getAuthHeaders = () => ({})  (cookies ride automatically)
//   - mobile: fetchImpl = `expo/fetch`,   getAuthHeaders = () => ({ Authorization: `Bearer <jwt>` })
// Concrete providers are constructed per platform.

export interface ClientConfig {
  /** Absolute API base, e.g. "https://cloud.onyx.app" or "http://localhost:8080". */
  baseUrl: string;
  /** Platform fetch: browser `fetch` on web, `expo/fetch` on mobile. */
  fetchImpl: typeof fetch;
  /** Resolves auth headers per request. Web returns {}; mobile returns a bearer JWT. */
  getAuthHeaders: () => Promise<HeadersInit>;
}
