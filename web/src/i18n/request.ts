import { getRequestConfig } from "next-intl/server";
import { cookies, headers } from "next/headers";
import { locales, defaultLocale, LOCALE_COOKIE_NAME } from "./config";

function parseAcceptLanguage(acceptLanguage: string | null): string | null {
  if (!acceptLanguage) return null;
  const preferred = acceptLanguage.split(",").map((lang) => {
    const parts = lang.trim().split(";q=");
    const code = parts[0] ?? "";
    const priority = parts[1] ? parseFloat(parts[1]) : 1;
    return { code: code.trim(), priority };
  });
  preferred.sort((a, b) => b.priority - a.priority);
  for (const { code } of preferred) {
    if (!code) continue;
    const lower = code.toLowerCase();
    if (lower.startsWith("zh")) return "zh";
    if (lower.startsWith("en")) return "en";
  }
  return null;
}

export default getRequestConfig(async () => {
  let locale = defaultLocale;

  try {
    const cookieStore = await cookies();
    const cookieLocale = cookieStore.get(LOCALE_COOKIE_NAME)?.value;
    if (cookieLocale && locales.includes(cookieLocale as typeof locales[number])) {
      locale = cookieLocale as typeof locales[number];
    } else {
      const headerStore = await headers();
      const acceptLanguage = headerStore.get("accept-language");
      const detected = parseAcceptLanguage(acceptLanguage);
      if (detected && locales.includes(detected as typeof locales[number])) {
        locale = detected as typeof locales[number];
      }
    }
  } catch {
    // cookies() may throw in static rendering or outside request context
  }

  return {
    locale,
    messages: (await import(`@/messages/${locale}.json`)).default,
  };
});
