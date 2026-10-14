import type en from "@/i18n/messages/en.json";
import type { RuntimeLocale } from "@/i18n/config";

// Makes message keys type-safe: `useTranslations`/`getTranslations` calls
// autocomplete against the English catalog, and a key that is missing from
// en.json is a compile error caught by `bun run types:check`.
// The locale is the runtime tag: the message locale, plus a numbering system for Arabic.
declare module "next-intl" {
  interface AppConfig {
    Locale: RuntimeLocale;
    Messages: typeof en;
  }
}
