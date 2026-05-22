export const CRAFT_PATH = "/craft/v1";
export const CRAFT_CONFIGURE_PATH = `${CRAFT_PATH}/configure`;
export const CRAFT_TASKS_PATH = `${CRAFT_PATH}/tasks`;
export const CRAFT_SKILLS_PATH = `${CRAFT_PATH}/skills`;
export const CRAFT_APPS_PATH = `${CRAFT_PATH}/apps`;
export const CRAFT_APPS_ADMIN_PATH = `${CRAFT_PATH}/apps/admin`;
export const CRAFT_APPS_OAUTH_CALLBACK_PATH = `${CRAFT_PATH}/apps/oauth/callback`;
export const CRAFT_OAUTH_COOKIE_NAME = "build_mode_oauth";
export const ONYX_CRAFT_CALENDAR_URL = "https://cal.com/team/onyx/onyx-craft";

// Backend BFF root for Craft/build endpoints (routes through the frontend
// per CLAUDE.md). Shared by the craft service modules.
export const BUILD_API_BASE = "/api/build";
