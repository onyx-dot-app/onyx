import Cookies from "js-cookie";

export const CRAFT_PATH = "/craft/v1";
export const CRAFT_CONFIGURE_PATH = `${CRAFT_PATH}/configure`;
export const CRAFT_OAUTH_COOKIE_NAME = "build_mode_oauth";
export const OAUTH_STATE_KEY = "build_oauth_state";
export const CRAFT_DEMO_DATA_COOKIE_NAME = "build_demo_data_enabled";
export const ONYX_CRAFT_CALENDAR_URL = "https://cal.com/team/onyx/onyx-craft";

/**
 * Read demo data enabled setting from cookie.
 * This is the single source of truth for the demo data setting.
 * Defaults to true if cookie doesn't exist or is invalid.
 */
export function getDemoDataEnabled(): boolean {
  if (typeof window === "undefined") return true; // SSR fallback
  const cookieValue = Cookies.get(CRAFT_DEMO_DATA_COOKIE_NAME);
  if (cookieValue === "false") return false;
  return true; // Default to true
}

/**
 * Write demo data enabled setting to cookie.
 */
export function setDemoDataCookie(enabled: boolean): void {
  Cookies.set(CRAFT_DEMO_DATA_COOKIE_NAME, String(enabled), {
    path: "/",
    expires: 365, // 1 year
  });
}
