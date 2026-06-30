import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import enCommon from "../../public/locales/en/common.json";
import esCommon from "../../public/locales/es/common.json";
import ptCommon from "../../public/locales/pt/common.json";
import frCommon from "../../public/locales/fr/common.json";
import deCommon from "../../public/locales/de/common.json";

/**
 * Initialize the shared i18next instance.
 *
 * Intentionally an explicit factory rather than an import-time side effect:
 * importing this module (e.g. for the default `i18n` export used by non-React
 * helpers) must NOT trigger initialization, cookie/localStorage reads, etc.
 * Call this once at app startup (see `AppProvider`).
 *
 * Idempotent — the underlying `init()` only runs the first time.
 */
export function initI18n() {
  if (!i18n.isInitialized) {
    i18n
      .use(LanguageDetector)
      .use(initReactI18next)
      .init({
        resources: {
          en: { common: enCommon },
          es: { common: esCommon },
          pt: { common: ptCommon },
          fr: { common: frCommon },
          de: { common: deCommon },
        },
        fallbackLng: "en",
        ns: ["common"],
        defaultNS: "common",
        interpolation: {
          escapeValue: false, // React already safes from XSS
        },
        detection: {
          order: ["cookie", "localStorage", "navigator", "htmlTag"],
          caches: ["cookie", "localStorage"],
          lookupCookie: "i18next",
          lookupLocalStorage: "i18nextLng",
        },
      });
  }

  return i18n;
}

export default i18n;
