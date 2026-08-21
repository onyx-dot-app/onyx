import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { DEFAULT_AGENT_ID } from "@/lib/constants";

/**
 * Where `/app` should send a request that names the Assistant outright, or
 * `null` when the query is already fine.
 *
 * Bare `/app` is the only way into the Assistant. Naming it by id leaves the
 * sidebar with nothing selected: `useAppFocus` reads the id as an agent focus,
 * and no tab renders agent 0. Only that one param is dropped; the rest of the
 * query survives.
 */
export function defaultAgentRedirectTarget(
  searchParams: Record<string, string>
): "/app" | `/app?${string}` | null {
  if (searchParams[SEARCH_PARAM_NAMES.AGENT_ID] !== String(DEFAULT_AGENT_ID)) {
    return null;
  }

  const rest = new URLSearchParams(searchParams);
  rest.delete(SEARCH_PARAM_NAMES.AGENT_ID);
  const query = rest.toString();

  return query ? `/app?${query}` : "/app";
}
