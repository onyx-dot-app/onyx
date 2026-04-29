// Default chat background images

import { ThemePreference } from "@/lib/types";

export const CHAT_BACKGROUND_NONE = "none";

export interface ChatBackgroundOption {
  id: string;
  src: string;
  thumbnail: string;
  label: string;
  theme?: ThemePreference;
}

// Curated collection of scenic backgrounds that work well as chat backgrounds
export const CHAT_BACKGROUND_OPTIONS: ChatBackgroundOption[] = [
  {
    id: "none",
    src: CHAT_BACKGROUND_NONE,
    thumbnail: CHAT_BACKGROUND_NONE,
    label: "None",
  },
  {
    id: "clouds",
    src: "/chat-backgrounds/clouds.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/clouds.jpg",
    label: "Clouds",
    theme: ThemePreference.LIGHT,
  },
  {
    id: "hills",
    src: "/chat-backgrounds/hills.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/hills.jpg",
    label: "Hills",
    theme: ThemePreference.LIGHT,
  },
  {
    id: "plant",
    src: "/chat-backgrounds/plant.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/plant.jpg",
    label: "Plants",
    theme: ThemePreference.DARK,
  },
  {
    id: "mountains",
    src: "/chat-backgrounds/mountains.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/mountains.jpg",
    label: "Mountains",
    theme: ThemePreference.DARK,
  },
  {
    id: "night",
    src: "/chat-backgrounds/night.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/night.jpg",
    label: "Night",
    theme: ThemePreference.DARK,
  },
];

export const getBackgroundById = (
  id: string | null
): ChatBackgroundOption | undefined => {
  if (!id || id === CHAT_BACKGROUND_NONE) {
    return CHAT_BACKGROUND_OPTIONS[0];
  }
  return CHAT_BACKGROUND_OPTIONS.find((bg) => bg.id === id);
};
