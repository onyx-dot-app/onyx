// Default chat background images
// Using high-quality Unsplash images optimized for different themes

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
    url: "https://images.unsplash.com/photo-1610888814579-ff6913173733",
    thumbnail: "https://images.unsplash.com/photo-1610888814579-ff6913173733",
    label: "Clouds",
  },
  {
    id: "hills",
    url: "https://images.unsplash.com/photo-1532019333101-b0f43c16a912",
    thumbnail: "https://images.unsplash.com/photo-1532019333101-b0f43c16a912",
    label: "Hills",
  },
  {
    id: "rainbow",
    url: "https://images.unsplash.com/photo-1500964757637-c85e8a162699",
    thumbnail: "https://images.unsplash.com/photo-1500964757637-c85e8a162699",
    label: "Rainbow",
  },
  {
    id: "gradient-mesh",
    url: "https://images.unsplash.com/photo-1557682250-33bd709cbe85",
    thumbnail: "https://images.unsplash.com/photo-1557682250-33bd709cbe85",
    label: "Gradient",
  },
  {
    id: "plant",
    url: "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d",
    thumbnail: "https://images.unsplash.com/photo-1692520883599-d543cfe6d43d",
    label: "Plants",
  },
  {
    id: "mountains",
    url: "https://images.unsplash.com/photo-1496361751588-bdd9a3fcdd6f",
    thumbnail: "https://images.unsplash.com/photo-1496361751588-bdd9a3fcdd6f",
    label: "Mountains",
  },
  {
    id: "night",
    url: "https://images.unsplash.com/photo-1520330461350-508fab483d6a",
    thumbnail: "https://images.unsplash.com/photo-1520330461350-508fab483d6a",
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
