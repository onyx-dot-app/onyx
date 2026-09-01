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
export const RTL_LOCALES: readonly Locale[] = [];

export type HtmlDir = "ltr" | "rtl";

export function htmlDirForLocale(locale: string): HtmlDir {
  // SAFETY: cast narrows only for the readonly-array `includes` signature.
  return RTL_LOCALES.includes(locale as Locale) ? "rtl" : "ltr";
}
