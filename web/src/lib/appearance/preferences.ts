/**
 * Appearance preferences that select fonts: the options the Appearance
 * settings offer, and the attributes on <html> that apply them. CSS in
 * src/app/globals.css maps each attribute value to the --font-interface /
 * --font-content variables that the typography presets resolve through, so
 * switching fonts never re-renders React trees.
 *
 * The values match the backend `InterfaceFont` / `ResponseFont` enums, and the
 * defaults match the `user_preferences` column defaults.
 */

export const INTERFACE_FONTS = [
  "default",
  "system",
  "opendyslexic",
  "atkinson",
] as const;
export type InterfaceFont = (typeof INTERFACE_FONTS)[number];

/** `match` follows the interface font; `default` keeps the default font. */
export const RESPONSE_FONTS = ["match", "default"] as const;
export type ResponseFont = (typeof RESPONSE_FONTS)[number];

export interface AppearancePreferences {
  interface_font: InterfaceFont;
  response_font: ResponseFont;
}

export const DEFAULT_APPEARANCE_PREFERENCES: AppearancePreferences = {
  interface_font: "default",
  response_font: "match",
};

/**
 * Set by the backend when the user saves an appearance preference and on
 * GET /me, so the server layout renders the saved fonts on first paint.
 * Name must match APPEARANCE_COOKIE_NAME in backend/onyx/configs/constants.py.
 */
export const APPEARANCE_COOKIE_NAME = "onyx_appearance";

/**
 * Reads the appearance cookie, a form-encoded query string
 * (`interface_font=...&response_font=...`). A missing or unknown value falls
 * back to its default, and unknown fields are ignored.
 */
export function parseAppearanceCookie(
  cookie: string | undefined
): AppearancePreferences {
  const fields = new URLSearchParams(cookie);
  return {
    interface_font:
      INTERFACE_FONTS.find((font) => font === fields.get("interface_font")) ??
      DEFAULT_APPEARANCE_PREFERENCES.interface_font,
    response_font:
      RESPONSE_FONTS.find((font) => font === fields.get("response_font")) ??
      DEFAULT_APPEARANCE_PREFERENCES.response_font,
  };
}

export interface AppearanceAttributes {
  "data-interface-font": InterfaceFont;
  "data-response-font": ResponseFont;
}

/** The <html> attributes for server rendering and for `applyAppearance`. */
export function appearanceAttributes({
  interface_font,
  response_font,
}: AppearancePreferences): AppearanceAttributes {
  return {
    "data-interface-font": interface_font,
    "data-response-font": response_font,
  };
}

/** Switches the fonts of a rendered document. */
export function applyAppearance(
  preferences: AppearancePreferences,
  root: HTMLElement = document.documentElement
): void {
  for (const [name, value] of Object.entries(
    appearanceAttributes(preferences)
  )) {
    root.setAttribute(name, value);
  }
}
