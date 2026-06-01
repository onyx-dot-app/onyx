import { useEffect, useState } from "react";
import { Animated, Easing } from "react-native";

import { SvgLoader } from "@/components/icons/SvgLoader";
import type { ColorToken } from "@/theme/generated/colors";

// Native mirror of web SimpleLoader. RN has no CSS animation, so rotate SvgLoader
// with the Animated API (useNativeDriver, linear loop).

interface SpinnerProps {
  size?: number;
  color?: ColorToken;
}

function Spinner({ size = 16, color = "text-03" }: SpinnerProps) {
  // Lazily-initialised state (not a ref) so it's created once and safe to read in render —
  // the React Compiler forbids reading refs during render.
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(progress, {
        toValue: 1,
        duration: 800,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [progress]);

  const rotate = progress.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  return (
    <Animated.View
      accessibilityRole="progressbar"
      style={{ width: size, height: size, transform: [{ rotate }] }}
    >
      <SvgLoader size={size} color={color} />
    </Animated.View>
  );
}

export { Spinner, type SpinnerProps };
