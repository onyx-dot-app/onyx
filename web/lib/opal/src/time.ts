/** Date and duration helpers. The date formatters take the active UI locale (BCP 47). */

// Rows in long tables format many dates per render, so formatters are reused per locale.
const relativeTimeFormatters = new Map<string, Intl.RelativeTimeFormat>();

function relativeTimeFormatter(locale: string): Intl.RelativeTimeFormat {
  let formatter = relativeTimeFormatters.get(locale);
  if (!formatter) {
    formatter = new Intl.RelativeTimeFormat(locale, { numeric: "always" });
    relativeTimeFormatters.set(locale, formatter);
  }
  return formatter;
}

/**
 * Formats how long ago a date was, e.g. "12 days ago", or null without a date.
 */
export function timeAgo(
  dateString: string | undefined | null,
  locale: string
): string | null {
  if (!dateString) {
    return null;
  }

  const time = new Date(dateString).getTime();
  if (Number.isNaN(time)) {
    return null;
  }

  const formatter = relativeTimeFormatter(locale);
  // Clamped so clock skew on a stored timestamp never reads as "in 5 seconds".
  const secondsDiff = Math.max(0, Math.floor((Date.now() - time) / 1000));

  if (secondsDiff < 60) {
    return formatter.format(-secondsDiff, "second");
  }

  const minutesDiff = Math.floor(secondsDiff / 60);
  if (minutesDiff < 60) {
    return formatter.format(-minutesDiff, "minute");
  }

  const hoursDiff = Math.floor(minutesDiff / 60);
  if (hoursDiff < 24) {
    return formatter.format(-hoursDiff, "hour");
  }

  const daysDiff = Math.floor(hoursDiff / 24);
  if (daysDiff < 30) {
    return formatter.format(-daysDiff, "day");
  }

  const monthsDiff = Math.floor(daysDiff / 30);
  if (monthsDiff < 12) {
    return formatter.format(-monthsDiff, "month");
  }

  return formatter.format(-Math.floor(monthsDiff / 12), "year");
}

/**
 * Formats a date string as a short date-and-time in the local timezone.
 *
 * @example
 * localizeAndPrettify("2025-01-15T10:30:00Z", "en") // "1/15/2025, 10:30:00 AM"
 */
export function localizeAndPrettify(
  dateString: string,
  locale: string
): string {
  return new Date(dateString).toLocaleString(locale);
}

/**
 * Formats a date string as a long-form date: full month name, numeric day,
 * and four-digit year.
 *
 * @example
 * humanReadableFormat("2025-01-15T10:30:00Z", "en") // "January 15, 2025"
 */
export function humanReadableFormat(
  dateString: string,
  locale: string
): string {
  return new Intl.DateTimeFormat(locale, {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(dateString));
}

/**
 * Formats a date as a short-form date: abbreviated month name, numeric day,
 * and four-digit year. Returns an empty string for a null input.
 *
 * @example
 * humanReadableFormatShort("2025-01-15T10:30:00Z", "en") // "Jan 15, 2025"
 * humanReadableFormatShort(null, "en")                   // ""
 */
export function humanReadableFormatShort(
  date: string | Date | null,
  locale: string
): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(d);
}

/**
 * Formats a datetime string as a long-form date with clock time: full month
 * name, numeric day, four-digit year, and the locale's clock format.
 *
 * @example
 * humanReadableFormatWithTime("2025-01-15T10:30:00Z", "en") // "January 15, 2025 at 10:30 AM"
 */
export function humanReadableFormatWithTime(
  datetimeString: string,
  locale: string
): string {
  return new Intl.DateTimeFormat(locale, {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "numeric",
  }).format(new Date(datetimeString));
}

export type TimeFilter = "day" | "week" | "month" | "year";

/**
 * Returns a `Date` representing the start of the given time filter window
 * relative to now, or `null` for an unrecognised filter value.
 *
 * @example
 * getTimeFilterDate("day")   // Date 24 hours ago
 * getTimeFilterDate("week")  // Date 7 days ago
 * getTimeFilterDate("month") // Date 30 days ago
 * getTimeFilterDate("year")  // Date 365 days ago
 */
export function getTimeFilterDate(filter: TimeFilter): Date | null {
  const now = new Date();
  switch (filter) {
    case "day":
      return new Date(now.getTime() - 24 * 60 * 60 * 1000);
    case "week":
      return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    case "month":
      return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    case "year":
      return new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
    default:
      return null;
  }
}

/**
 * Formats a duration given in seconds as a compact string, rounding up to
 * the nearest whole second.
 *
 * @example
 * formatDurationSeconds(45)   // "45s"
 * formatDurationSeconds(90)   // "1m 30s"
 * formatDurationSeconds(120)  // "2m"
 */
export function formatDurationSeconds(seconds: number): string {
  const totalSeconds = Math.ceil(seconds);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

/**
 * Formats a duration given in milliseconds as a compact, human-readable
 * string, automatically choosing the most appropriate unit. Non-finite
 * inputs (e.g. `Infinity`, `NaN`) render as `"—"`.
 *
 * @example
 * formatDurationMs(0.5)      // "<1 ms"
 * formatDurationMs(42)       // "42 ms"
 * formatDurationMs(1500)     // "1.50 s"
 * formatDurationMs(75000)    // "1m 15s"
 * formatDurationMs(3600000)  // "1h"
 * formatDurationMs(5400000)  // "1h 30m"
 * formatDurationMs(Infinity) // "—"
 */
export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;

  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;

  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remSeconds = totalSeconds % 60;
  if (minutes < 60) {
    return remSeconds > 0 ? `${minutes}m ${remSeconds}s` : `${minutes}m`;
  }

  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes > 0 ? `${hours}h ${remMinutes}m` : `${hours}h`;
}

/**
 * Returns the number of seconds remaining until the given expiry `Date`.
 * Clamps to `0` if the deadline has already passed.
 *
 * @example
 * getSecondsUntilExpiration(new Date(Date.now() + 240_000)) // ~240
 * getSecondsUntilExpiration(new Date(Date.now() - 1_000))   // 0
 */
export function getSecondsUntilExpiration(expiry: Date): number {
  return Math.max(0, Math.floor((expiry.getTime() - Date.now()) / 1000));
}
