// Design tokens come from @onyx-ai/shared (the same source of truth as web/Opal).
// `nativewind-theme` is a Tailwind `theme.extend` fragment: semantic colors map to
// `var(--name)` (resolved at runtime by the vars() provider in src/app/_layout.tsx,
// so they flip with the system light/dark scheme), and radius/spacing are px numbers.
const sharedTheme = require("@onyx-ai/shared/nativewind-theme");
// `.font-*` → RN-text-style map (RN counterpart of web/Opal's `@utility font-*`
// blocks), registered below so mobile can use `font-heading-h1` etc. like web.
const typographyUtilities = require("@onyx-ai/shared/nativewind-typography");
const plugin = require("tailwindcss/plugin");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: { extend: sharedTheme },
  plugins: [
    plugin(({ addUtilities }) => {
      addUtilities(typographyUtilities);
    }),
  ],
};
