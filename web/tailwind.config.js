var path = require("path");
var fs = require("fs");
var { createRequire } = require("module");

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
  // Use createRequire to avoid bundler static analysis without using eval
  const dynamicRequire = createRequire(__filename);
  customThemes = dynamicRequire(customThemePath);
}

function deepMerge(target, source) {
  const result = { ...target };
  for (const key of Object.keys(source)) {
    if (
      source[key] &&
      typeof source[key] === "object" &&
      !Array.isArray(source[key])
    ) {
      result[key] = deepMerge(result[key] || {}, source[key]);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

/** @type {import('tailwindcss').Config} */
module.exports = customThemes
  ? deepMerge(baseThemes, customThemes)
  : baseThemes;
