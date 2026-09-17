import type { SearchParamName } from "@/app/app/services/searchParams";
import type { Route } from "next";

type QueryValue = string | number | boolean | undefined;

/**
 * Build a route with a query string. The pathname is checked against the routes
 * that `typedRoutes` generates, and the query keys against `SEARCH_PARAM_NAMES`.
 * Undefined values are dropped. Values are URL-encoded.
 */
export function routeWithQuery<P extends string>(
  pathname: Route<P>,
  query: Partial<Record<SearchParamName, QueryValue>>
): `${P}?${string}` {
  const searchParams = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined) searchParams.set(name, String(value));
  }
  return `${pathname as P}?${searchParams.toString()}`;
}
