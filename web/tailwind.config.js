var merge = require("lodash/merge");
var path = require("path");
var fs = require("fs");

// Use relative paths for imports
const baseThemes = require("./tailwind-themes/tailwind.config.js");

let customThemes = null;

// Determine which theme to load: custom theme if specified, otherwise default
const themeName = process.env.NEXT_PUBLIC_THEME || "default";
const customThemePath = path.join(
  __dirname,
  "tailwind-themes/custom",
  themeName,
  "tailwind.config.js"
);

if (fs.existsSync(customThemePath)) {
  customThemes = require(customThemePath);
}

/** @type {import('tailwindcss').Config} */
module.exports = customThemes ? merge(baseThemes, customThemes) : baseThemes;
