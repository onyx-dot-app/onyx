export const THEMES = {
  LIGHT: "light",
  DARK: "dark",
};

export const DEFAULT_ONYX_DOMAIN = "http://localhost:3000";

export const SIDEBAR_PATH = "/chat/nrf/side-panel";

export const ACTIONS = {
  GET_SELECTED_TEXT: "getSelectedText",
  GET_CURRENT_ONYX_DOMAIN: "getCurrentOnyxDomain",
  UPDATE_PAGE_URL: "updatePageUrl",
  SEND_TO_ONYX: "sendToOnyx",
  OPEN_SIDEBAR: "openSidebar",
  TOGGLE_NEW_TAB_OVERRIDE: "toggleNewTabOverride",
  OPEN_SIDEBAR_WITH_INPUT: "openSidebarWithInput",
  OPEN_ONYX_WITH_INPUT: "openOnyxWithInput",
  CLOSE_SIDEBAR: "closeSidebar",
};

export const STORAGE_KEYS = {
  ONYX_DOMAIN: "onyxExtensionDomain",
  USE_ONYX_AS_DEFAULT_NEW_TAB: "onyxExtensionDefaultNewTab",
  THEME: "onyxExtensionTheme",
  BACKGROUND_IMAGE: "onyxExtensionBackgroundImage",
  DARK_BG_URL: "onyxExtensionDarkBgUrl",
  LIGHT_BG_URL: "onyxExtensionLightBgUrl",
  ONBOARDING_COMPLETE: "onyxExtensionOnboardingComplete",
};

export const EXTENSION_MESSAGE = {
  PREFERENCES_UPDATED: "PREFERENCES_UPDATED",
  ONYX_APP_LOADED: "ONYX_APP_LOADED",
  SET_DEFAULT_NEW_TAB: "SET_DEFAULT_NEW_TAB",
  LOAD_NEW_CHAT_PAGE: "LOAD_NEW_CHAT_PAGE",
  LOAD_NEW_PAGE: "LOAD_NEW_PAGE",
  AUTH_REQUIRED: "AUTH_REQUIRED",
};

export const WEB_MESSAGE = {
  PAGE_CHANGE: "PAGE_CHANGE",
};
