// Locale registry for the web UI.
//
// Must stay in sync with the backend `SupportedLanguage` enum in
// backend/onyx/db/enums.py — config.test.ts pins this list, and
// `PATCH /user/language` rejects values outside that enum.
export const SUPPORTED_LOCALES = ["en", "es", "pt", "fr", "de"] as const;

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
} satisfies Record<Locale, string>;

export function isSupportedLocale(
  value: string | null | undefined
): value is Locale {
  // SAFETY: the cast only widens the argument for the readonly-array
  // `includes` signature; membership is still checked at runtime.
  return SUPPORTED_LOCALES.includes(value as Locale);
}
