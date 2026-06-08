// The platform seam that keeps this package transport-neutral. The only platform
// differences are the fetch impl and how auth is carried:
//   - web:    browser `fetch`, getAuthHeaders = () => ({})  (cookies ride automatically)
//   - mobile: `expo/fetch`,    getAuthHeaders = () => ({ Authorization: `Bearer <jwt>` })

export interface ClientConfig {
  baseUrl: string;
  fetchImpl: typeof fetch;
  getAuthHeaders: () => Promise<HeadersInit>;
}
