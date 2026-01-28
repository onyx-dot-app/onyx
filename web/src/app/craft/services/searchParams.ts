import { ReadonlyURLSearchParams } from "next/navigation";

// search params for build pages
export const CRAFT_SEARCH_PARAM_NAMES = {
  SESSION_ID: "sessionId",
};

export function getSessionIdFromSearchParams(
  searchParams: ReadonlyURLSearchParams | null
): string | null {
  return searchParams?.get(CRAFT_SEARCH_PARAM_NAMES.SESSION_ID) ?? null;
}
