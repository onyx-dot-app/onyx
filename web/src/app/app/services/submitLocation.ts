/** Formats a path and query so that equal locations give equal keys. */
export function locationKey(
  pathname: string,
  search: string | URLSearchParams
): string {
  const query = new URLSearchParams(search).toString();
  return query ? `${pathname}?${query}` : pathname;
}

/**
 * True when the page still shows a location that a send started from. A send
 * that fails after the user moves to a different page must not change that page.
 */
export function isStillOnLocation(
  startKeys: readonly string[],
  current: { pathname: string; search: string }
): boolean {
  return startKeys.includes(locationKey(current.pathname, current.search));
}
