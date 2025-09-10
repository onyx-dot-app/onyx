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
    escapeValue: false, // not needed for react!!
  },
});

// Add this line to your app entrypoint. Usually it is src/index.js
// import './i18n/init';

export default i18next;
