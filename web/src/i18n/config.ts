// Locale registry for the web UI.
//
// Must stay in sync with the backend `SupportedLanguage` enum in
// backend/onyx/db/enums.py — config.test.ts pins this list, and
// `PATCH /user/language` rejects values outside that enum.
export const SUPPORTED_LOCALES = [
  "en",
  "es",
  "pt",
  "fr",
  "de",
  "ja",
  "zh",
  "ko",
  "ar",
] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

// Cookie the server layout reads to resolve the locale without a DB round
// trip. The backend owns it: PATCH /user/language and GET /me set it from the
// stored preference (NEXT_LOCALE_COOKIE_NAME in backend/onyx/configs/
// constants.py). The client never writes it.
export const LOCALE_COOKIE_NAME = "NEXT_LOCALE";

// Endonyms (each language named in itself) so users can always find their own
// language in the picker, whatever the current UI language is.
export const LOCALE_ENDONYMS = {
  en: "English",
  es: "Español",
  pt: "Português",
  fr: "Français",
  de: "Deutsch",
  ja: "日本語",
  zh: "简体中文",
  ko: "한국어",
  ar: "العربية",
} satisfies Record<Locale, string>;

export function isSupportedLocale(
  value: string | null | undefined
): value is Locale {
  // SAFETY: the cast narrows only to satisfy the readonly-array
  // `includes` signature. Membership is still checked at runtime.
  return SUPPORTED_LOCALES.includes(value as Locale);
}

// Locales whose UI renders right-to-left. Drives <html dir> and the
// Radix DirectionProvider in the root layout. A new RTL locale is
// registered here after joining SUPPORTED_LOCALES.
export const RTL_LOCALES: readonly Locale[] = ["ar"];

export type HtmlDir = "ltr" | "rtl";

export function htmlDirForLocale(locale: Locale): HtmlDir {
  return RTL_LOCALES.includes(locale) ? "rtl" : "ltr";
}

// Arabic reads Eastern Arabic-Indic digits. The numbering system rides on the
// runtime locale tag, so any Intl call given useLocale() shapes digits without
// a numberingSystem option.
const NUMBERING_SYSTEMS: Partial<Record<Locale, string>> = { ar: "arab" };

export type RuntimeLocale = Locale | `${Locale}-u-nu-${string}`;

/** The locale handed to next-intl and Intl for a stored language. */
export function runtimeLocale(locale: Locale): RuntimeLocale {
  const system = NUMBERING_SYSTEMS[locale];
  return system ? `${locale}-u-nu-${system}` : locale;
}

/** The stored language behind a runtime tag ("ar-u-nu-arab" is "ar"). Unknown tags fall back to English. */
export function messageLocale(locale: string): Locale {
  const base = locale.split("-u-")[0] ?? locale;
  return isSupportedLocale(base) ? base : DEFAULT_LOCALE;
}
