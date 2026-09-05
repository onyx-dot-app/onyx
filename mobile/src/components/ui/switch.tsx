/*
 * Hand-built rather than RN's Switch, which can't match the token look. Animated is react-native's,
 * not reanimated's: importing reanimated here drags the worklets runtime into every jest suite that
 * renders a menu row.
 */
import { useEffect, useState } from "react";
import { Animated, Pressable } from "react-native";

import { cn } from "@/lib/utils";

const TRACK_WIDTH = 32;
const TRACK_HEIGHT = 18;
const THUMB_SIZE = 14;
const TRACK_PADDING = 2;
// Inner track width minus the thumb: 32 − 2·2 − 14 = 14.
const THUMB_TRAVEL = TRACK_WIDTH - TRACK_PADDING * 2 - THUMB_SIZE;
const DURATION_MS = 150;

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
  // Lazy useState, not a ref: created once, and refs can't be read during render.
  const [offset] = useState(
    () => new Animated.Value(checked ? THUMB_TRAVEL : 0),
  );

  useEffect(() => {
    Animated.timing(offset, {
      toValue: checked ? THUMB_TRAVEL : 0,
      duration: DURATION_MS,
      useNativeDriver: true,
    }).start();
  }, [checked, offset]);

  const trackColor = disabled
    ? checked
      ? "bg-action-selection-03"
      : "bg-background-neutral-04"
    : checked
      ? "bg-action-selection-05"
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
        style={[
          { width: THUMB_SIZE, height: THUMB_SIZE },
          { transform: [{ translateX: offset }] },
        ]}
      />
    </Pressable>
  );
}

export { Switch, type SwitchProps };
