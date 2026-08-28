import type en from "@/i18n/messages/en.json";
import type { Locale } from "@/i18n/config";

// Makes message keys type-safe: `useTranslations`/`getTranslations` calls
// autocomplete against the English catalog, and a key that is missing from
// en.json is a compile error caught by `bun run types:check`.
declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof en;
  }
}
