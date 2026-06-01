import { useEffect, useState } from "react";
import { Animated, Easing } from "react-native";

import { SvgLoader } from "@/components/icons/SvgLoader";
import type { ColorToken } from "@/theme/generated/colors";

// ---------------------------------------------------------------------------
// Spinner — native mirror of web's `SimpleLoader` (an Opal loader glyph spun
// with `animate-spin`). RN has no CSS animation, so we rotate the ported
// `SvgLoader` with the built-in `Animated` API (useNativeDriver, linear loop).
// Used in attachment tiles while a file uploads / processes.
// ---------------------------------------------------------------------------

interface SpinnerProps {
  /** Square edge length in px. Default: 16. */
  size?: number;
  /** Color token for the arc. Default: `"text-03"` (muted, web parity). */
  color?: ColorToken;
}

function Spinner({ size = 16, color = "text-03" }: SpinnerProps) {
  // 0→1 driven once per rotation; interpolated to 0→360deg below. A lazily-
  // initialised state value (not a ref) so it's created once and is safe to read
  // during render (the React Compiler forbids reading refs in render).
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
