import i18next from "i18next";

const russian = require("./russian");

i18next.init({
  lng: "ru",
  debug: true,
  resources: {
    ru: { translation: russian },
  },
});

// Add this line to your app entrypoint. Usually it is src/index.js
// import './i18n/init';
