/**
 * Appearance preferences: the options the Appearance settings offer, and the
 * attributes on <html> that apply the ones the first paint needs (fonts and
 * motion). CSS in src/app/globals.css maps each font value to the
 * --font-interface / --font-content variables that the typography presets
 * resolve through, and Opal's motion variants read `data-motion`, so a change
 * never re-renders React trees.
 *
 * The values match the backend `InterfaceFont`, `ResponseFont`,
 * `MotionPreference` and `PopupDismissal` enums, and the defaults match the
 * `user_preferences` column defaults.
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

/** `system` follows the OS reduced-motion setting; `reduced` always reduces. */
export const MOTIONS = ["system", "reduced"] as const;
export type Motion = (typeof MOTIONS)[number];

/** Whether toasts close by themselves or stay until the user closes them. */
export const POPUP_DISMISSALS = ["auto_dismiss", "stay_on_screen"] as const;
export type PopupDismissal = (typeof POPUP_DISMISSALS)[number];

/** The preferences the appearance cookie carries for the first paint. */
export interface AppearancePreferences {
  interface_font: InterfaceFont;
  response_font: ResponseFont;
  motion: Motion;
}

export const DEFAULT_APPEARANCE_PREFERENCES: AppearancePreferences = {
  interface_font: "default",
  response_font: "match",
  motion: "system",
};

/**
 * Everything PATCH /user/appearance saves. Popup dismissal and dynamic
 * conversations apply once /me loads, so the cookie does not carry them.
 */
export interface AppearanceSettings extends AppearancePreferences {
  popup_dismissal: PopupDismissal;
  /** Unload chat messages far off screen; screen readers cannot reach them. */
  dynamic_conversations: boolean;
}

export const DEFAULT_APPEARANCE_SETTINGS: AppearanceSettings = {
  ...DEFAULT_APPEARANCE_PREFERENCES,
  popup_dismissal: "auto_dismiss",
  dynamic_conversations: true,
};

/**
 * Set by the backend when the user saves an appearance preference and on
 * GET /me, so the server layout renders the saved fonts and motion on first
 * paint.
 * Name must match APPEARANCE_COOKIE_NAME in backend/onyx/configs/constants.py.
 */
export const APPEARANCE_COOKIE_NAME = "onyx_appearance";

/**
 * Reads the appearance cookie, a form-encoded query string
 * (`interface_font=...&response_font=...&motion=...`). A missing or unknown
 * value falls back to its default, and unknown fields are ignored.
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
    motion:
      MOTIONS.find((motion) => motion === fields.get("motion")) ??
      DEFAULT_APPEARANCE_PREFERENCES.motion,
  };
}

export interface AppearanceAttributes {
  "data-interface-font": InterfaceFont;
  "data-response-font": ResponseFont;
  /** Read by Opal's `motion-reduce:` variants and `prefersReducedMotion()`. */
  "data-motion": Motion;
}

/** The <html> attributes for server rendering and for `applyAppearance`. */
export function appearanceAttributes({
  interface_font,
  response_font,
  motion,
}: AppearancePreferences): AppearanceAttributes {
  return {
    "data-interface-font": interface_font,
    "data-response-font": response_font,
    "data-motion": motion,
  };
}

/** Switches the fonts and motion of a rendered document. */
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
