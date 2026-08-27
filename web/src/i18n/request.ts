import { getRequestConfig } from "next-intl/server";
import { cookies } from "next/headers";

import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE_NAME,
  isSupportedLocale,
} from "@/i18n/config";
import englishMessages from "@/i18n/messages/en.json";

type MessageTree = { [key: string]: string | MessageTree };

// Overlay a target-locale catalog on top of the English one. Keys the target
// catalog does not have yet (the lag window before the translation pipeline
// runs) render in English instead of as raw key paths.
function withEnglishFallback(base: MessageTree, overlay: MessageTree) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(overlay)) {
    const baseValue = merged[key];
    merged[key] =
      typeof value === "object" &&
      value !== null &&
      typeof baseValue === "object" &&
      baseValue !== null
        ? withEnglishFallback(baseValue, value)
        : value;
  }
  return merged;
}

// SAFETY: catalog files are JSON objects whose values are strings or nested
// objects of the same shape; the i18n catalog test enforces this.
const english = englishMessages as MessageTree;

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
  const locale = isSupportedLocale(cookieLocale)
    ? cookieLocale
    : DEFAULT_LOCALE;

  if (locale === DEFAULT_LOCALE) {
    return { locale, messages: english };
  }

  // SAFETY: same catalog shape as en.json, enforced by the i18n catalog test.
  const overlay = (await import(`@/i18n/messages/${locale}.json`))
    .default as MessageTree;
  return { locale, messages: withEnglishFallback(english, overlay) };
});
