// Opacity pulse, not web's gradient sweep: that relies on `background-clip: text`, which RN has no
// equivalent for. RN `Animated`, not reanimated, so the timeline stays renderable under jest.
import { useEffect, useMemo } from "react";
import { Animated, Easing } from "react-native";

import { Text } from "@/components/ui/text";

const PULSE_DURATION_MS = 900;
const PULSE_MIN_OPACITY = 0.5;

export function ShimmerText({ children }: { children: string }) {
  const opacity = useMemo(() => new Animated.Value(PULSE_MIN_OPACITY), []);

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: PULSE_DURATION_MS,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: PULSE_MIN_OPACITY,
          duration: PULSE_DURATION_MS,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [opacity]);

  return (
    <Animated.View style={{ opacity }}>
      <Text font="main-ui-action" color="text-03">
        {children}
      </Text>
    </Animated.View>
  );
}

export default ShimmerText;
