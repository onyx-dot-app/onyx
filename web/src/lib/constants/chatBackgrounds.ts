// Default chat background images

export const CHAT_BACKGROUND_NONE = "none";

export interface ChatBackgroundOption {
  id: string;
  url: string;
  thumbnail: string;
  label: string;
}

// Curated collection of scenic backgrounds that work well as chat backgrounds
export const CHAT_BACKGROUND_OPTIONS: ChatBackgroundOption[] = [
  {
    id: "none",
    url: CHAT_BACKGROUND_NONE,
    thumbnail: CHAT_BACKGROUND_NONE,
    label: "None",
  },
  {
    id: "clouds",
    url: "/chat-backgrounds/clouds.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/clouds.jpg",
    label: "Clouds",
  },
  {
    id: "hills",
    url: "/chat-backgrounds/hills.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/hills.jpg",
    label: "Hills",
  },
  {
    id: "plant",
    url: "/chat-backgrounds/plant.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/plant.jpg",
    label: "Plants",
  },
  {
    id: "mountains",
    url: "/chat-backgrounds/mountains.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/mountains.jpg",
    label: "Mountains",
  },
  {
    id: "night",
    url: "/chat-backgrounds/night.jpg",
    thumbnail: "/chat-backgrounds/thumbnails/night.jpg",
    label: "Night",
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
