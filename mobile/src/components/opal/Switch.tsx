import { useEffect } from "react";
import { Pressable } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  interpolateColor,
} from "react-native-reanimated";

import { useToken } from "@/theme/ThemeProvider";

// ---------------------------------------------------------------------------
// Switch — a themed animated toggle (web-parity).
//
//   <Switch value={v} onValueChange={setV} />
//
// Dynamic/track colours are resolved through `useToken()` and applied via
// `style` (never a dynamic className), and animated with Reanimated's
// `interpolateColor` driven by a shared value (matching the codebase
// convention in `BlinkingBar.tsx`).
// ---------------------------------------------------------------------------

export interface SwitchProps {
  /** Whether the switch is on. Controlled. */
  value: boolean;
  /** Called with the next value on press. */
  onValueChange: (next: boolean) => void;
  /** Disable interaction + show the disabled track colour. Default: false. */
  disabled?: boolean;
  /** Accessibility label for screen readers. */
  accessibilityLabel?: string;
}

const TRACK_W = 32;
const TRACK_H = 18;
const THUMB = 14;
const PAD = 1;
const ON_X = TRACK_W - THUMB - PAD; // 32 - 14 - 1 = 17
const DURATION = 150;

export function Switch({
  value,
  onValueChange,
  disabled = false,
  accessibilityLabel,
}: SwitchProps) {
  const offTrack = useToken("background-tint-03");
  const onTrack = useToken("action-link-05");
  const disabledTrack = useToken("background-neutral-04");

  // Drives both the track colour interpolation and the thumb translation. A
  // shared value updated from a useEffect is the robust Reanimated pattern
  // (vs. calling withTiming inline in the worklet on every render).
  const progress = useSharedValue(value ? 1 : 0);

  useEffect(() => {
    progress.value = withTiming(value ? 1 : 0, { duration: DURATION });
  }, [value, progress]);

  const trackStyle = useAnimatedStyle(() => ({
    backgroundColor: disabled
      ? disabledTrack
      : interpolateColor(progress.value, [0, 1], [offTrack, onTrack]),
  }));

  const thumbStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: PAD + progress.value * (ON_X - PAD) }],
  }));

  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: value, disabled }}
      accessibilityLabel={accessibilityLabel}
      disabled={disabled}
      hitSlop={8}
      onPress={() => onValueChange(!value)}
    >
      <Animated.View
        style={[
          {
            width: TRACK_W,
            height: TRACK_H,
            borderRadius: TRACK_H / 2,
            justifyContent: "center",
          },
          trackStyle,
        ]}
      >
        <Animated.View
          style={[
            {
              width: THUMB,
              height: THUMB,
              borderRadius: THUMB / 2,
              backgroundColor: "#ffffff",
            },
            thumbStyle,
          ]}
        />
      </Animated.View>
    </Pressable>
  );
}
