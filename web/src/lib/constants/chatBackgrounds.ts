// Default chat background images
// Using high-quality Unsplash images optimized for different themes

export const CHAT_BACKGROUND_NONE = "none";

export interface ChatBackgroundOption {
  id: string;
  url: string;
  thumbnail: string;
  label: string;
}

// Unsplash URL parameters:
// - Full images: w=1920, q=80, auto=format (webp when supported)
// - Thumbnails: w=200, h=150, fit=crop, q=70, auto=format

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
    url: "https://images.unsplash.com/photo-1610888814579-ff6913173733?w=1920&q=80&auto=format",
    thumbnail:
      "https://images.unsplash.com/photo-1610888814579-ff6913173733?w=200&h=150&fit=crop&q=70&auto=format",
    label: "Clouds",
  },
  {
    id: "hills",
    url: "https://images.unsplash.com/photo-1532019333101-b0f43c16a912?w=1920&q=80&auto=format",
    thumbnail:
      "https://images.unsplash.com/photo-1532019333101-b0f43c16a912?w=200&h=150&fit=crop&q=70&auto=format",
    label: "Hills",
  },
  {
    id: "plant",
    url: "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d?w=1920&q=80&auto=format",
    thumbnail:
      "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d?w=200&h=150&fit=crop&q=70&auto=format",
    label: "Plants",
  },
  {
    id: "mountains",
    url: "https://images.unsplash.com/photo-1496361751588-bdd9a3fcdd6f?w=1920&q=80&auto=format",
    thumbnail:
      "https://images.unsplash.com/photo-1496361751588-bdd9a3fcdd6f?w=200&h=150&fit=crop&q=70&auto=format",
    label: "Mountains",
  },
  {
    id: "night",
    url: "https://images.unsplash.com/photo-1520330461350-508fab483d6a?w=1920&q=80&auto=format",
    thumbnail:
      "https://images.unsplash.com/photo-1520330461350-508fab483d6a?w=200&h=150&fit=crop&q=70&auto=format",
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
