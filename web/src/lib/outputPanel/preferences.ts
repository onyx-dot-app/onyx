/**
 * An output panel's preferences per chat or Craft session, in session
 * storage: they last through a reload of the browser tab, and logout clears
 * them. Each panel parses its own values; these only read and write them.
 */

/** The stored preferences, as `parse` reads them from the stored JSON. */
export function readPanelPreferences<T>(
  key: string,
  // oxlint-disable-next-line anti-slop/no-unknown-parameters -- The parser receives untrusted browser storage at the I/O boundary.
  parse: (stored: unknown) => T | undefined
): T | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw === null ? undefined : parse(JSON.parse(raw));
  } catch {
    return undefined;
  }
}

export function savePanelPreferences<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Panel controls remain usable when browser storage is unavailable.
  }
}

export function clearPanelPreferences(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Browser storage may be unavailable.
  }
}
