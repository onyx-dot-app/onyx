// shadows.ts — RN shadow helpers for elevated surfaces (citation detail card).
//
// Web's `shadow-01` utility (applied to SourceTagDetailsCard) is a TWO-layer
// box-shadow built from the `shadow-02` COLOR token (#0000001a light):
//   0px 2px 12px 0px var(--shadow-02), 0px 0px 4px 1px var(--shadow-02)
// RN can't stack two box-shadows portably, so we approximate the dominant
// `0 2px 12px` layer with a single iOS shadow + Android elevation. Documented
// approximation (amendment M9).

import { Platform, type ViewStyle } from "react-native";
import { useToken } from "@/theme/ThemeProvider";

export function useCardShadow(): ViewStyle {
  const shadowColor = useToken("shadow-02");
  return Platform.select<ViewStyle>({
    ios: {
      shadowColor,
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 1, // the token already carries alpha (#0000001a)
      shadowRadius: 8,
    },
    android: {
      elevation: 6,
    },
    default: {},
  })!;
}

// Alias kept for the citation detail card call sites.
export const useCitationShadow = useCardShadow;
