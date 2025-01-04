export interface Shortcut {
  name: string;
  url: string;
  favicon?: string;
}

// Start of Selection

// Start of Selection
export enum LightBackgroundColors {
  Red = "#dc2626", // Tailwind Red 600
  Blue = "#2563eb", // Tailwind Blue 600
  Green = "#16a34a", // Tailwind Green 600
  Yellow = "#ca8a04", // Tailwind Yellow 600
  Purple = "#9333ea", // Tailwind Purple 600
  Orange = "#ea580c", // Tailwind Orange 600
  Pink = "#db2777", // Tailwind Pink 600
}

export enum DarkBackgroundColors {
  Red = "#991b1b", // Tailwind Red 800
  Blue = "#1e40af", // Tailwind Blue 800
  Green = "#166534", // Tailwind Green 800
  Yellow = "#854d0e", // Tailwind Yellow 800
  Purple = "#5b21b6", // Tailwind Purple 800
  Orange = "#9a3412", // Tailwind Orange 800
  Pink = "#9d174d", // Tailwind Pink 800
}

export enum StoredBackgroundColors {
  RED = "Red",
  BLUE = "Blue",
  GREEN = "Green",
  YELLOW = "Yellow",
  PURPLE = "Purple",
  ORANGE = "Orange",
  PINK = "Pink",
}

export type BackgroundColors = LightBackgroundColors | DarkBackgroundColors;

export interface Shortcut {
  name: string;
  url: string;
  favicon?: string;
}

export const darkImages = [
  "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d?q=80&w=2666&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
  "https://images.unsplash.com/photo-1520330461350-508fab483d6a?q=80&w=2723&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
];

export const lightImages = [
  "https://images.unsplash.com/photo-1473830439578-14e9a9e61d55?q=80&w=2670&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
  "https://images.unsplash.com/photo-1500964757637-c85e8a162699?q=80&w=2703&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
  "https://images.unsplash.com/photo-1475924156734-496f6cac6ec1?q=80&w=2670&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D",
];

// Local storage keys
export const SHORTCUTS_KEY = "shortCuts";
export const NEW_TAB_PAGE_VIEW_KEY = "newTabPageView";
export const USE_ONYX_AS_NEW_TAB_KEY = "useOnyxAsNewTab";

// Default values
export const DEFAULT_LIGHT_BACKGROUND_IMAGE = "onyxBackgroundLight";
export const DEFAULT_DARK_BACKGROUND_IMAGE = "onyxBackgroundDark";
export const DEFAULT_NEW_TAB_PAGE_VIEW = "chat";
