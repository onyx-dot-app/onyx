// Central TanStack Query key registry (mirrors web's src/lib/swr-keys.ts).
export const QUERY_KEYS = {
  // Keyed by serverUrl so switching instances never serves the previous
  // backend's authenticated identity from cache.
  me: (serverUrl: string | null) => ["me", serverUrl] as const,

  // Keyed by serverUrl so switching instances refetches the new backend's config.
  authType: (serverUrl: string | null) => ["auth-type", serverUrl] as const,
};
