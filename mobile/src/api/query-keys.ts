// Central TanStack Query key registry (mirrors web's src/lib/swr-keys.ts).
//
// All useQuery / invalidateQueries / setQueryData calls reference these instead
// of inline arrays, so keys stay greppable and consistent. Keys are arrays (the
// TanStack requirement); use `as const` so the literal types are preserved.
// For dynamic keys (per-id endpoints), use a builder function.
export const QUERY_KEYS = {
  // ── User ──────────────────────────────────────────────────────────────────
  // Keyed by serverUrl so switching instances never serves the previous
  // backend's authenticated identity from cache.
  me: (serverUrl: string | null) => ["me", serverUrl] as const,

  // ── Auth ──────────────────────────────────────────────────────────────────
  // Keyed by serverUrl so switching instances refetches the new backend's
  // config (and so a null/unset URL has its own cache entry).
  authType: (serverUrl: string | null) => ["auth-type", serverUrl] as const,

  // Examples for when more endpoints land:
  // settings: ["settings"] as const,
  // persona: (id: string) => ["persona", id] as const,
};
