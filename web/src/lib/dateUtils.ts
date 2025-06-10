import { useEffect } from "react";
import { useState } from "react";

export const useNightTime = () => {
  const [isNight, setIsNight] = useState(false);

  useEffect(() => {
    const checkNightTime = () => {
      const currentHour = new Date().getHours();
      setIsNight(currentHour >= 18 || currentHour < 6);
    };

    checkNightTime();
    const interval = setInterval(checkNightTime, 60000); // Check every minute

    return () => clearInterval(interval);
  }, []);

  return { isNight };
};

export function getXDaysAgo(daysAgo: number) {
  const today = new Date();
  const daysAgoDate = new Date(today);
  daysAgoDate.setDate(today.getDate() - daysAgo);
  return daysAgoDate;
}

export function getXYearsAgo(yearsAgo: number) {
  const today = new Date();
  const yearsAgoDate = new Date(today);
  yearsAgoDate.setFullYear(yearsAgoDate.getFullYear() - yearsAgo);
  return yearsAgoDate;
}

export const timestampToDateString = (timestamp: string) => {
  const date = new Date(timestamp);
  const year = date.getFullYear();
  const month = date.getMonth() + 1; // getMonth() is zero-based
  const day = date.getDate();

  const formattedDate = `${year}-${month.toString().padStart(2, "0")}-${day
    .toString()
    .padStart(2, "0")}`;
  return formattedDate;
};

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

export const buildDateString = (date: Date | null) => {
  return date
    ? `${Math.round(
        (new Date().getTime() - date.getTime()) / (1000 * 60 * 60 * 24)
      )} days ago`
    : "Select a time range";
};

export const getFormattedDateRangeString = (
  from: Date | null,
  to: Date | null
) => {
  if (!from || !to) return null;

  const options: Intl.DateTimeFormatOptions = {
    month: "short",
    day: "numeric",
    year: "numeric",
  };
  const fromString = from.toLocaleDateString("en-US", options);
  const toString = to.toLocaleDateString("en-US", options);

  return `${fromString} - ${toString}`;
};

export const getDateRangeString = (from: Date | null, to: Date | null) => {
  if (!from || !to) return null;

  const now = new Date();
  const fromDiffMs = now.getTime() - from.getTime();
  const toDiffMs = now.getTime() - to.getTime();

  const fromDiffDays = Math.floor(fromDiffMs / (1000 * 60 * 60 * 24));
  const toDiffDays = Math.floor(toDiffMs / (1000 * 60 * 60 * 24));

  const fromString = getTimeAgoString(from);
  const toString = getTimeAgoString(to);

  if (fromString === toString) return fromString;

  if (toDiffDays === 0) {
    return `${fromString} - Today`;
  }

  return `${fromString} - ${toString}`;
};

export const getTimeAgoString = (date: Date | null) => {
  if (!date) return null;

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const diffWeeks = Math.floor(diffDays / 7);
  const diffMonths = Math.floor(diffDays / 30);

  if (now.toDateString() === date.toDateString()) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${diffWeeks}w ago`;
  return `${diffMonths}mo ago`;
};

export const getFormattedDateTime = (date: Date | null) => {
  if (!date) return null;

  const now = new Date();
  const isToday = now.toDateString() === date.toDateString();

  if (isToday) {
    // If it's today, return the time in format like "3:45 PM"
    return date.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } else {
    // Otherwise return the date in format like "Jan 15, 2023"
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
};
