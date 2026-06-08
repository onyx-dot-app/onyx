// Approximates web's .shimmer-text CSS animation with a Reanimated opacity pulse
// (a moving gradient mask would need @react-native-masked-view, deferred).

import { useEffect } from "react";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withSequence,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { Text, type TextFont, type TextColor } from "@/components/opal";

interface ShimmerTextProps {
  children: string;
  font?: TextFont;
  color?: TextColor;
}

export function ShimmerText({
  children,
  font = "main-ui-action",
  color = "text-03",
}: ShimmerTextProps) {
  const opacity = useSharedValue(0.55);
  useEffect(() => {
    opacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(0.55, { duration: 700, easing: Easing.inOut(Easing.ease) })
      ),
      -1,
      false
    );
  }, [opacity]);

  const style = useAnimatedStyle(() => ({ opacity: opacity.value }));

  return (
    <Animated.View style={style}>
      <Text font={font} color={color}>
        {children}
      </Text>
    </Animated.View>
  );
}

export default ShimmerText;
