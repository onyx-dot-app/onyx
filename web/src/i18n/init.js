import i18next from "i18next";

const english = require("./english");
const chinese = require("./chinese");
const russian = require("./russian");

i18next.init({
  lng: localStorage.getItem("lng") || "ru",
  debug: true,
  resources: {
    en: { translation: english },
    "zh-Hans": { translation: chinese },
    ru: { translation: russian },
  },
});

// Add this line to your app entrypoint. Usually it is src/index.js
// import './i18n/init';
