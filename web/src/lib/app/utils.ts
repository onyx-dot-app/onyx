import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import { DEFAULT_AGENT_ID } from "@/lib/constants";

/**
 * Where `/app` should send a request that names the Assistant outright, or
 * `null` when the query is already fine.
 *
 * Bare `/app` is the only way into the Assistant. Naming it by id leaves the
 * sidebar with nothing selected: `useAppPosition` reads the id as an agent focus,
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

/** The web server's version, from its ONYX_VERSION env var. Server-side only. */
export function getWebVersion(): string {
  return process.env.ONYX_VERSION || "dev";
}

/** Where the About page's version links. */
export const CHANGELOG_URL = "https://docs.onyx.app/changelog";

/** The GitHub page of a commit of the Onyx repo. */
export function commitUrl(commit: string): string {
  return `https://github.com/onyx-dot-app/onyx/commit/${commit}`;
}
