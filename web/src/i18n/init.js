import i18next from "i18next";

const russian = require("./russian");

i18next.init({
  lng: "ru",
  debug: true,
  fallbackLng: "ru",
  preload: ["ru"],
  resources: {
    ru: { translation: russian },
  },
}),
  (err, t) => {
    if (err) return console.log("something went wrong loading", err);
    t("SIGN_UP_FOR_ONYX"); // -> same as i18next.t
  };

// Add this line to your app entrypoint. Usually it is src/index.js
// import './i18n/init';
