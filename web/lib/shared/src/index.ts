/**
 * @onyx-ai/shared — platform-agnostic code shared between Onyx web and mobile.
 *
 * Design tokens are NOT re-exported here: they are generated build artifacts,
 * consumed via the dedicated subpaths "@onyx-ai/shared/tokens.css" (web/Opal CSS
 * variables), "@onyx-ai/shared/nativewind-theme" (mobile Tailwind theme fragment),
 * and "@onyx-ai/shared/native" (mobile light/dark vars() maps).
 */
export * from "./contracts";
export * from "./types";
export * from "./utils";
