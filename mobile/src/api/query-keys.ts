export const QUERY_KEYS = {
  // Keyed by serverUrl so switching instances never serves the prior backend's
  // cached identity/config.
  me: (serverUrl: string | null) => ["me", serverUrl] as const,
  authType: (serverUrl: string | null) => ["auth-type", serverUrl] as const,
};
