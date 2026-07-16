// Toggle primitive, RN port of Opal Switch (web/lib/opal/src/components/inputs/switch/). Track
// 32×18, thumb 14×14, reanimated thumb translate. RN's native Switch can't match the token look, so
// this is hand-built from a Pressable track + an Animated thumb.
import { useEffect } from "react";
import { Pressable } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

import { cn } from "@/lib/utils";

const TRACK_WIDTH = 32;
const TRACK_HEIGHT = 18;
const THUMB_SIZE = 14;
const TRACK_PADDING = 2;
// Inner track width minus the thumb: 32 − 2·2 − 14 = 14.
const THUMB_TRAVEL = TRACK_WIDTH - TRACK_PADDING * 2 - THUMB_SIZE;

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  accessibilityLabel?: string;
}

function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  accessibilityLabel,
}: SwitchProps) {
  const offset = useSharedValue(checked ? THUMB_TRAVEL : 0);

  useEffect(() => {
    offset.value = withTiming(checked ? THUMB_TRAVEL : 0, { duration: 150 });
  }, [checked, offset]);

  const thumbStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: offset.value }],
  }));

  const trackColor = disabled
    ? checked
      ? "bg-action-link-03"
      : "bg-background-neutral-04"
    : checked
      ? "bg-action-link-05"
      : "bg-background-tint-03";
  const thumbColor = disabled
    ? "bg-background-neutral-03"
    : "bg-background-neutral-light-00";

  return (
    <Pressable
      disabled={disabled}
      onPress={() => onCheckedChange(!checked)}
      accessibilityRole="switch"
      accessibilityState={{ checked, disabled }}
      accessibilityLabel={accessibilityLabel}
      className={cn("justify-center rounded-full", trackColor)}
      style={{
        width: TRACK_WIDTH,
        height: TRACK_HEIGHT,
        paddingHorizontal: TRACK_PADDING,
      }}
    >
      <Animated.View
        className={cn("rounded-full", thumbColor)}
        style={[{ width: THUMB_SIZE, height: THUMB_SIZE }, thumbStyle]}
      />
    </Pressable>
  );
}

export { Switch, type SwitchProps };
