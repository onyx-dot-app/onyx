// Pure, Next-independent i18n config so it can be unit-tested in the node
// jest project. Keep `next/headers` and other server-only imports OUT of here.

export const SUPPORTED_LOCALES = ["zh", "en"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "zh";

// Standard cookie name next-intl / Next conventions use for the active locale.
export const LOCALE_COOKIE = "NEXT_LOCALE";

export function isSupportedLocale(
  value: string | undefined | null
): value is SupportedLocale {
  return value === "zh" || value === "en";
}

export function resolveLocale(value: string | undefined | null): SupportedLocale {
  return isSupportedLocale(value) ? value : DEFAULT_LOCALE;
}
