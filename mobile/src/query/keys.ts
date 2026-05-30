// Query key registry. The SWR endpoint registry doubles as our TanStack Query key
// registry: a URL string (e.g. SWR_KEYS.me) — or `[builder(id)]` for per-id endpoints —
// IS the query key. Re-exported as `queryKeys` so query hooks read from a single source.
import { SWR_KEYS } from "@/lib/api";

export const queryKeys = SWR_KEYS;
