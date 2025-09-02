import { User } from "./types";
import i18n from "@/i18n/init";
import k from "../i18n/keys";

const conditionallyAddPlural = (solo: string, noun: string, cnt: number) => {
  if (cnt > 1) {
    return `${noun}`;
  }
  return solo;
};

export const timeAgo = (
  dateString: string | undefined | null
): string | null => {
  if (!dateString) {
    return null;
  }

  const date = new Date(dateString);
  const now = new Date();
  const secondsDiff = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (secondsDiff < 60) {
    return `${secondsDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_SECOND),
      i18n.t(k.TIME_SECONDS),
      secondsDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const minutesDiff = Math.floor(secondsDiff / 60);
  if (minutesDiff < 60) {
    return `${minutesDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_MINUTE),
      i18n.t(k.TIME_MINUTES),
      secondsDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const hoursDiff = Math.floor(minutesDiff / 60);
  if (hoursDiff < 24) {
    return `${hoursDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_HOUR),
      i18n.t(k.TIME_HOURS),
      hoursDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const daysDiff = Math.floor(hoursDiff / 24);
  if (daysDiff < 30) {
    return `${daysDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_DAY),
      i18n.t(k.TIME_DAYS),
      daysDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const weeksDiff = Math.floor(daysDiff / 7);
  if (weeksDiff < 4) {
    return `${weeksDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_WEEK),
      i18n.t(k.TIME_WEEKS),
      weeksDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const monthsDiff = Math.floor(daysDiff / 30);
  if (monthsDiff < 12) {
    return `${monthsDiff} ${conditionallyAddPlural(
      i18n.t(k.TIME_MONTH),
      i18n.t(k.TIME_MONTHS),
      monthsDiff
    )} ${i18n.t(k.TIME_AGO)}`;
  }

  const yearsDiff = Math.floor(monthsDiff / 12);
  return `${yearsDiff} ${conditionallyAddPlural(
    i18n.t(k.TIME_YEAR),
    i18n.t(k.TIME_YEARS),
    yearsDiff
  )} ${i18n.t(k.TIME_AGO)}`;
};

export function localizeAndPrettify(dateString: string) {
  const date = new Date(dateString);
  return date.toLocaleString();
}

export function humanReadableFormat(dateString: string): string {
  // Create a Date object from the dateString
  const date = new Date(dateString);

  // Use Intl.DateTimeFormat to format the date
  // Specify the locale as 'en-US' and options for month, day, and year
  const formatter = new Intl.DateTimeFormat("ru-RU", {
    month: "long", // full month name
    day: "numeric", // numeric day
    year: "numeric", // numeric year
  });

  // Format the date and return it
  return formatter.format(date);
}

export function humanReadableFormatWithTime(datetimeString: string): string {
  // Create a Date object from the dateString
  const date = new Date(datetimeString);

  // Use Intl.DateTimeFormat to format the date
  // Specify the locale as 'en-US' and options for month, day, and year
  const formatter = new Intl.DateTimeFormat("ru-RU", {
    month: "long", // full month name
    day: "numeric", // numeric day
    year: "numeric", // numeric year
    hour: "numeric",
    minute: "numeric",
  });
  // Format the date and return it
  return formatter.format(date);
}

export function getSecondsUntilExpiration(
  userInfo: User | null
): number | null {
  if (!userInfo) {
    return null;
  }

  const { oidc_expiry, current_token_created_at, current_token_expiry_length } =
    userInfo;

  const now = new Date();

  let secondsUntilTokenExpiration: number | null = null;
  let secondsUntilOIDCExpiration: number | null = null;

  if (current_token_created_at && current_token_expiry_length !== undefined) {
    const createdAt = new Date(current_token_created_at);
    const expiresAt = new Date(
      createdAt.getTime() + current_token_expiry_length * 1000
    );
    secondsUntilTokenExpiration = Math.floor(
      (expiresAt.getTime() - now.getTime()) / 1000
    );
  }

  if (oidc_expiry) {
    const expiresAtFromOIDC = new Date(oidc_expiry);
    secondsUntilOIDCExpiration = Math.floor(
      (expiresAtFromOIDC.getTime() - now.getTime()) / 1000
    );
  }

  if (
    secondsUntilTokenExpiration === null &&
    secondsUntilOIDCExpiration === null
  ) {
    return null;
  }

  return Math.max(
    0,
    Math.min(
      secondsUntilTokenExpiration ?? Infinity,
      secondsUntilOIDCExpiration ?? Infinity
    )
  );
}
