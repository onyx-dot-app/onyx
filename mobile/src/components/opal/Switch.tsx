import { useEffect } from "react";
import { Pressable } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  interpolateColor,
} from "react-native-reanimated";

import { useToken } from "@/theme/ThemeProvider";

export interface SwitchProps {
  value: boolean;
  onValueChange: (next: boolean) => void;
  disabled?: boolean;
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

  // Drive track color + thumb translation from a shared value updated in useEffect —
  // robust Reanimated pattern vs. calling withTiming inline in the worklet each render.
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
