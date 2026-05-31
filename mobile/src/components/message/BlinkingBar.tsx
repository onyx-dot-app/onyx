// BlinkingBar.tsx — the streaming caret / empty-state placeholder.
//
// Ports web BlinkingBar (animate-pulse bg-theme-primary-05 w-2 h-4). Used as the
// MessageText trailing caret AND as the empty-state placeholder in search/fetch
// renderers while results are still streaming. Reanimated opacity loop.

import { useEffect } from "react";
import { View, type ViewStyle } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withSequence,
  Easing,
} from "react-native-reanimated";

import { useToken } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";

interface BlinkingBarProps {
  /** Adds a small top margin to baseline-align with text (web `addMargin`). */
  addMargin?: boolean;
  style?: ViewStyle;
}

export function BlinkingBar({ addMargin = false, style }: BlinkingBarProps) {
  const color = useToken("theme-primary-05");
  const opacity = useSharedValue(1);

  useEffect(() => {
    // Mirrors Tailwind's animate-pulse cadence (~1s ease-in-out, alternating).
    opacity.value = withRepeat(
      withSequence(
        withTiming(0.35, { duration: 500, easing: Easing.inOut(Easing.ease) }),
        withTiming(1, { duration: 500, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      false
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View
      style={[
        {
          width: 8,
          height: 16,
          borderRadius: radii["02"],
          backgroundColor: color,
          marginTop: addMargin ? 2 : 0,
        },
        animatedStyle,
        style,
      ]}
    />
  );
}

/** Static (non-animated) variant for environments where animation is undesirable. */
export function StaticBar({ addMargin = false }: BlinkingBarProps) {
  const color = useToken("theme-primary-05");
  return (
    <View
      style={{
        width: 8,
        height: 16,
        borderRadius: radii["02"],
        backgroundColor: color,
        marginTop: addMargin ? 2 : 0,
      }}
    />
  );
}
