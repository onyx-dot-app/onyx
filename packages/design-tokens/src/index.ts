// @onyx-ai/design-tokens — Opal design tokens bridged to React Native.
//
// Contents are owned by: docs/plans/2026-05-30-mobile-app/03-design-system-bridge.md
// A Style Dictionary pipeline ingests the Opal token sources and emits:
//   - flattened TS theme objects (lightTheme / darkTheme) for runtime use, and
//   - a NativeWind / Tailwind-v3 colors preset (exposed later as a subpath export
//     "./nativewind-preset", consumed by mobile/tailwind.config.js — see doc 05).
//
// Token sources (web): web/lib/opal/src/styles/colors.css (:root + .dark),
//   web/lib/opal/src/styles/typography.css, web/lib/opal/src/root.css,
//   web/src/app/css/*, and web/tailwind.config.js (breakpoints/calendar/code).
//
// Reminder: NativeWind v4 = Tailwind v3 semantics, so the web Tailwind-4 config is NOT
// reusable — bridge token VALUES only (flatten alias indirection).
//
// Source-only internal package: consumers import TS directly via the workspace symlink.

export {};
