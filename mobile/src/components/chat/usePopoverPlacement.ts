import { Dimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

// Safe-area-aware placement for the composer's anchored popovers, which open
// near the bottom edge: pads the rn-primitives collision insets and clamps width.
export interface PopoverPlacement {
  insets: { top: number; bottom: number; left: number; right: number };
  contentWidth: number;
}

interface PopoverPlacementOptions {
  maxWidth: number;
  widthMargin: number;
  // Extra bottom inset, e.g. live keyboard height for a popover with a search box.
  extraBottom?: number;
}

export function usePopoverPlacement({
  maxWidth,
  widthMargin,
  extraBottom = 0,
}: PopoverPlacementOptions): PopoverPlacement {
  const insets = useSafeAreaInsets();
  const screenWidth = Dimensions.get("window").width;

  return {
    insets: {
      top: insets.top + 8,
      bottom: insets.bottom + 8 + extraBottom,
      left: 12,
      right: 12,
    },
    contentWidth: Math.min(maxWidth, screenWidth - widthMargin),
  };
}
