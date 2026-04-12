"use client";

import { useTranslations as useNextIntlTranslations } from "next-intl";
import { useUser } from "@/providers/UserProvider";
import type { Locale } from "./config";
import { defaultLocale } from "./config";

export function useLocale(): Locale {
  const { user } = useUser();
  const pref = user?.preferences?.language_preference;
  if (pref === "en" || pref === "zh") return pref;
  return defaultLocale;
}

export { useNextIntlTranslations as useTranslations };
