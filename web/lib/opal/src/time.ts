function conditionallyAddPlural(noun: string, cnt: number): string {
  if (cnt > 1) {
    return `${noun}s`;
  }
  return noun;
}

/**
 * Returns a human-readable relative time string for a past date, or `null`
 * if the input is absent. Granularity increases with distance: seconds →
 * minutes → hours → days → weeks → months → years.
 *
 * @example
 * timeAgo(new Date(Date.now() - 3_000).toISOString())                    // "3 seconds ago"
 * timeAgo(new Date(Date.now() - 42 * 60_000).toISOString())              // "42 minutes ago"
 * timeAgo(new Date(Date.now() - 5 * 3_600_000).toISOString())            // "5 hours ago"
 * timeAgo(new Date(Date.now() - 12 * 86_400_000).toISOString())          // "12 days ago"
 * timeAgo(new Date(Date.now() - 14 * 86_400_000).toISOString())          // "2 weeks ago"
 * timeAgo(new Date(Date.now() - 240 * 86_400_000).toISOString())         // "8 months ago"
 * timeAgo(new Date(Date.now() - 3 * 365 * 86_400_000).toISOString())     // "3 years ago"
 * timeAgo(null)                                                           // null
 */
export function timeAgo(dateString: string | undefined | null): string | null {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  const now = new Date();
  const secondsDiff = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (secondsDiff < 60) {
    return `${secondsDiff} ${conditionallyAddPlural("second", secondsDiff)} ago`;
  }

  const minutesDiff = Math.floor(secondsDiff / 60);
  if (minutesDiff < 60) {
    return `${minutesDiff} ${conditionallyAddPlural("minute", minutesDiff)} ago`;
  }

  const hoursDiff = Math.floor(minutesDiff / 60);
  if (hoursDiff < 24) {
    return `${hoursDiff} ${conditionallyAddPlural("hour", hoursDiff)} ago`;
  }

  const daysDiff = Math.floor(hoursDiff / 24);
  if (daysDiff < 30) {
    return `${daysDiff} ${conditionallyAddPlural("day", daysDiff)} ago`;
  }

  const weeksDiff = Math.floor(daysDiff / 7);
  if (weeksDiff < 4) {
    return `${weeksDiff} ${conditionallyAddPlural("week", weeksDiff)} ago`;
  }

  const monthsDiff = Math.floor(daysDiff / 30);
  if (monthsDiff < 12) {
    return `${monthsDiff} ${conditionallyAddPlural("month", monthsDiff)} ago`;
  }

  const yearsDiff = Math.floor(monthsDiff / 12);
  return `${yearsDiff} ${conditionallyAddPlural("year", yearsDiff)} ago`;
}

/**
 * Formats a date string using the browser's locale and timezone, producing a
 * short, human-friendly date-and-time string.
 *
 * @example
 * localizeAndPrettify("2025-01-15T10:30:00Z") // "1/15/2025, 10:30:00 AM"
 */
export function localizeAndPrettify(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString();
}

/**
 * Formats a date string as a long-form date: full month name, numeric day,
 * and four-digit year, in US English.
 *
 * @example
 * humanReadableFormat("2025-01-15T10:30:00Z") // "January 15, 2025"
 */
export function humanReadableFormat(dateString: string): string {
  const date = new Date(dateString);
  const formatter = new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
  return formatter.format(date);
}

/**
 * Formats a date as a short-form date: abbreviated month name, numeric day,
 * and four-digit year, in US English. Returns an empty string for a null input.
 *
 * @example
 * humanReadableFormatShort("2025-01-15T10:30:00Z") // "Jan 15, 2025"
 * humanReadableFormatShort(null)                   // ""
 */
export function humanReadableFormatShort(date: string | Date | null): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  const formatter = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return formatter.format(d);
}

/**
 * Formats a datetime string as a long-form date with clock time: full month
 * name, numeric day, four-digit year, and 12-hour time, in US English.
 *
 * @example
 * humanReadableFormatWithTime("2025-01-15T10:30:00Z") // "January 15, 2025 at 10:30 AM"
 */
export function humanReadableFormatWithTime(datetimeString: string): string {
  const date = new Date(datetimeString);
  const formatter = new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "numeric",
  });
  return formatter.format(date);
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
 * Returns the number of seconds until the nearest of two optional expiry
 * boundaries. When both are provided, returns the smaller value. Returns
 * `null` if neither boundary is available. Never returns a negative number
 * — clamps to `0` once the deadline has already passed.
 *
 * `expiryA` is an absolute expiry `Date`. `expiryB` is expressed as a
 * creation time plus a duration in seconds, and is resolved to an absolute
 * date internally.
 *
 * @example
 * getSecondsUntilExpiration(undefined, undefined, undefined) // null
 * getSecondsUntilExpiration(new Date(Date.now() + 300_000), undefined, undefined) // ~300
 */
export function getSecondsUntilExpiration(
  expiryA: Date | undefined,
  expiryBCreatedAt: Date | undefined,
  expiryBDurationSeconds: number | undefined
): number | null {
  const now = new Date();

  let secondsUntilExpiryA: number | null = null;
  let secondsUntilExpiryB: number | null = null;

  if (expiryBCreatedAt && expiryBDurationSeconds !== undefined) {
    const expiresAt = new Date(
      expiryBCreatedAt.getTime() + expiryBDurationSeconds * 1000
    );
    secondsUntilExpiryB = Math.floor(
      (expiresAt.getTime() - now.getTime()) / 1000
    );
  }

  if (expiryA) {
    secondsUntilExpiryA = Math.floor(
      (expiryA.getTime() - now.getTime()) / 1000
    );
  }

  if (secondsUntilExpiryA === null && secondsUntilExpiryB === null) {
    return null;
  }

  return Math.max(
    0,
    Math.min(secondsUntilExpiryA ?? Infinity, secondsUntilExpiryB ?? Infinity)
  );
}
