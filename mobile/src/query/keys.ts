// The SWR endpoint registry doubles as the query key registry: a URL string (or
// `[builder(id)]` for per-id endpoints) IS the query key.
import { SWR_KEYS } from "@/lib/api";

export const queryKeys = SWR_KEYS;
