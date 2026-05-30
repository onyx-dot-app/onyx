/** @type {import('tailwindcss').Config} */
module.exports = {
  // Scan the router screens AND shared source for className usage.
  content: ["./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  // Opal dark mode is class-driven (`.dark`); NativeWind toggles it per scheme.
  darkMode: "class",
  presets: [
    require("nativewind/preset"),
    // Generated from Opal CSS — see mobile/scripts/generate-theme.ts.
    require("./src/theme/generated/nativewind-preset.js"),
  ],
};
