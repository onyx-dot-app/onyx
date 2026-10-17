import { cs } from "./cs";
import { en } from "./en";

export type { Translations } from "./en";

export const translations = { en, cs };
export type Locale = keyof typeof translations;

export function resolveLocale(
  languages: readonly string[] = navigator.languages,
  fallbackLanguage: string = navigator.language
): Locale {
  for (const language of languages.length ? languages : [fallbackLanguage]) {
    const baseLanguage = language.toLowerCase().split("-")[0];
    if (baseLanguage === "en" || baseLanguage === "cs") {
      return baseLanguage;
    }
  }
  return "en";
}