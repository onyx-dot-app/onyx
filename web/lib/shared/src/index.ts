/**
 * @onyx-ai/shared — platform-agnostic code shared between Onyx web and mobile.
 *
 * Design tokens are NOT re-exported here: they are generated build artifacts,
 * consumed via the dedicated subpaths "@onyx-ai/shared/tokens" (mobile JS
 * object) and "@onyx-ai/shared/tokens.css" (web CSS variables).
 */
export * from "./contracts";
export * from "./types";
export * from "./utils";
