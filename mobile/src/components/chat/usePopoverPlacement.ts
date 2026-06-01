import { Dimensions } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

// Shared safe-area-aware placement for the composer's anchored popovers
// (AttachMenu, ModelSelectorTrigger, ActionsPopover). Each of these opens near
// the bottom edge of the screen, so they pad the rn-primitives collision insets
// by the safe-area + 8px and clamp their measured width below the screen edge.
//
// Kept as a chat-local helper rather than a `PopoverContent` default so the
// non-chat popover callers (which intentionally pass no insets/width) keep their
// current behavior.

export interface PopoverPlacement {
  /** rn-primitives collision insets (safe-area padded). */
  insets: { top: number; bottom: number; left: number; right: number };
  /** Width clamped so the card never overflows a narrow screen. */
  contentWidth: number;
}

interface PopoverPlacementOptions {
  /** Maximum content width before clamping. */
  maxWidth: number;
  /** Horizontal margin kept clear on each side when clamping the width. */
  widthMargin: number;
  /**
   * Extra bottom inset, e.g. the live keyboard height for a popover whose search
   * box would otherwise sit under the keyboard. Defaults to 0.
   */
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
