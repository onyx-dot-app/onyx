"use client";

import { useTranslation as useReactI18nextTranslation } from "react-i18next";
import { useLanguage } from "@/contexts/LanguageContext";

export function useTranslation(): {
  t: (key: string, options?: any) => string;
  language: string;
  i18n: any;
} {
  const { language } = useLanguage();
  const { t, i18n } = useReactI18nextTranslation();

  return {
    t: t as (key: string, options?: any) => string,
    language,
    i18n,
  };
}
