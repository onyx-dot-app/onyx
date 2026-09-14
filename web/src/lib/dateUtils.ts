"use client";

import { humanReadableFormatShort } from "@opal/time";

export function getXDaysAgo(daysAgo: number) {
  const today = new Date();
  const daysAgoDate = new Date(today);
  daysAgoDate.setDate(today.getDate() - daysAgo);
  return daysAgoDate;
}

export function convertDateToEndOfDay(date?: Date | null) {
  if (!date) {
    return date;
  }

  const dateCopy = new Date(date);
  dateCopy.setHours(23, 59, 59, 999);
  return dateCopy;
}

export function convertDateToStartOfDay(date?: Date | null) {
  if (!date) {
    return date;
  }

  const dateCopy = new Date(date);
  dateCopy.setHours(0, 0, 0, 0);
  return dateCopy;
}

export function getXYearsAgo(yearsAgo: number) {
  const today = new Date();
  const yearsAgoDate = new Date(today);
  yearsAgoDate.setFullYear(yearsAgoDate.getFullYear() - yearsAgo);
  return yearsAgoDate;
}

export function formatDateForApiParam(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function normalizeDate(date: Date): Date {
  const normalizedDate = new Date(date);
  normalizedDate.setHours(0, 0, 0, 0);
  return normalizedDate;
}

function isAfterDate(date: Date, maxDate: Date): boolean {
  return normalizeDate(date).getTime() > normalizeDate(maxDate).getTime();
}

export function isDateInFuture(date: Date): boolean {
  return isAfterDate(date, new Date());
}

// Options for formatting the date
const dateOptions: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
};

// Options for formatting the time
const timeOptions: Intl.DateTimeFormatOptions = {
  hour: "numeric",
  minute: "2-digit",
  hour12: true, // Use 12-hour format with AM/PM
};

export const timestampToReadableDate = (timestamp: string) => {
  const date = new Date(timestamp);
  return (
    date.toLocaleDateString(undefined, dateOptions) +
    ", " +
    date.toLocaleTimeString(undefined, timeOptions)
  );
};

/** Short date like "Jan 27, 2026", or an em dash when there is no date. */
export const formatDateShort = (
  dateStr: string | null | undefined,
  locale: string
): string => (dateStr ? humanReadableFormatShort(dateStr, locale) : "—");

// Parses at local midnight so the day never shifts the way `formatDateShort` can for callers west of UTC.
export const formatCalendarDay = (
  dateStr: string,
  locale: string,
  { withYear = false }: { withYear?: boolean } = {}
): string =>
  new Date(`${dateStr}T00:00:00`).toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
    ...(withYear && { year: "numeric" }),
  });

/**
 * Format an ISO timestamp as "YYYY/MM/DD HH:MM:SS" (24-hour, local time).
 * Intended for log displays where full precision is needed.
 */
export function formatDateTimeLog(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatMmDdYyyy(d: string): string {
  const date = new Date(d);
  return `${date.getMonth() + 1}/${date.getDate()}/${date.getFullYear()}`;
}

/**
 * Format a duration in seconds as MM:SS (e.g. 65 → "01:05").
 */
export function formatElapsedTime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}`;
}

export const getFormattedDateTime = (date: Date | null, locale: string) => {
  if (!date) return null;

  const now = new Date();
  const isToday = now.toDateString() === date.toDateString();

  if (isToday) {
    // If it's today, return the time in format like "3:45 PM"
    return date.toLocaleTimeString(locale, {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } else {
    // Otherwise return the date in format like "Jan 15, 2023"
    return date.toLocaleDateString(locale, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
};
