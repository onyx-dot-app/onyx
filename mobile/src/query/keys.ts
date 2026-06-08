// The API path registry doubles as the query key registry: a URL string (or
// `[builder(id)]` for per-id endpoints) IS the query key.
import { API_PATHS } from "@/lib/api";

export const queryKeys = API_PATHS;
