/**
 * The results a check list shows: a check that does not apply to the access
 * type or config is stored as skipped, but has no row.
 */
export function applicableResults<T extends { applicable: boolean }>(
  results: T[]
): T[] {
  return results.filter((result) => result.applicable);
}
