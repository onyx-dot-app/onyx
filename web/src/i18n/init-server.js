import i18next from "i18next";

const russian = require("./russian");
const english = require("./english");

i18next.init({
  lng: "ru",
  fallbackLng: "ru",
  preload: ["ru", "en"],
  resources: {
    ru: { translations: russian },
    en: { translations: english },
  },
  ns: ["translations"],
  defaultNS: "translations",
  interpolation: {
    escapeValue: false,
  },
});

export default i18next;


