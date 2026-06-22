import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import enCommon from "../../public/locales/en/common.json";
import esCommon from "../../public/locales/es/common.json";

// Initialize i18n only if it hasn't been initialized yet
if (!i18n.isInitialized) {
  i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources: {
        en: {
          common: enCommon,
        },
        es: {
          common: esCommon,
        },
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

export default i18n;
