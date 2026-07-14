import { useEffect, useMemo } from "react";
import { Animated, Easing } from "react-native";

import { Icon } from "@/components/ui/icon";
import SvgLoader from "@/icons/loader";

interface SpinnerProps {
  size?: number;
  // Onyx text-color class for the arc, e.g. "text-status-error-05".
  className?: string;
}

// RN Animated native transform (not ActivityIndicator) so spinners match the icon set;
// Animated (not reanimated) keeps it jest-safe.
export function Spinner({
  size = 16,
  className = "text-text-03",
}: SpinnerProps) {
  const rotation = useMemo(() => new Animated.Value(0), []);

  useEffect(() => {
    const animation = Animated.loop(
      Animated.timing(rotation, {
        toValue: 1,
        duration: 800,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    animation.start();
    return () => animation.stop();
  }, [rotation]);

  const rotate = rotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  return (
    <Animated.View style={{ transform: [{ rotate }] }}>
      <Icon as={SvgLoader} size={size} className={className} />
    </Animated.View>
  );
}
