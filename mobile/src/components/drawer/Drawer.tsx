import { type ReactNode } from "react";
import { Dimensions, Pressable, StyleSheet, View } from "react-native";
import Animated, {
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
} from "react-native-reanimated";
import { Gesture, GestureDetector } from "react-native-gesture-handler";

import { useDrawer } from "./DrawerProvider";

const SCREEN_WIDTH = Dimensions.get("window").width;
export const DRAWER_WIDTH = Math.min(SCREEN_WIDTH * 0.86, 320);

const EDGE_OPEN_ZONE = 28; // px from the left edge where a swipe starts opening
const OPEN_THRESHOLD = 0.5; // settle open past this fraction
const FLING_VELOCITY = 600; // px/s fling to force open/close regardless of position

// ChatGPT-style slide-over drawer. Layers (bottom → top):
//   1. children            — the route navigator (chat, etc.)
//   2. backdrop            — animated dim (visual only)
//   3. tap-catcher         — full-screen Pressable, only while open, closes on tap
//   4. sidebar             — translates in from the left
//
// Open/close via the header toggle (useDrawer) or a horizontal pan. The pan only
// engages when already open or when starting from the left edge, and yields to
// vertical scrolls so list/content scrolling is unaffected.
export function Drawer({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  const { progress, isOpen, open, close } = useDrawer();

  const startProgress = useSharedValue(0);
  const active = useSharedValue(false);

  const pan = Gesture.Pan()
    .activeOffsetX([-15, 15]) // only claim horizontal drags…
    .failOffsetY([-14, 14]) // …and bail on vertical ones (let scroll through)
    .onBegin((e) => {
      active.value = progress.value > 0.5 || e.x <= EDGE_OPEN_ZONE;
      startProgress.value = progress.value;
    })
    .onUpdate((e) => {
      if (!active.value) return;
      const next = startProgress.value + e.translationX / DRAWER_WIDTH;
      progress.value = Math.min(Math.max(next, 0), 1);
    })
    .onEnd((e) => {
      if (!active.value) return;
      if (e.velocityX > FLING_VELOCITY) runOnJS(open)();
      else if (e.velocityX < -FLING_VELOCITY) runOnJS(close)();
      else if (progress.value > OPEN_THRESHOLD) runOnJS(open)();
      else runOnJS(close)();
    });

  const sidebarStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          progress.value,
          [0, 1],
          [-DRAWER_WIDTH, 0],
          Extrapolation.CLAMP,
        ),
      },
    ],
  }));

  const backdropStyle = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [0, 0.5], Extrapolation.CLAMP),
  }));

  return (
    <GestureDetector gesture={pan}>
      <View style={styles.root}>
        <View style={styles.content}>{children}</View>

        <Animated.View
          pointerEvents="none"
          style={[styles.fill, styles.backdrop, backdropStyle]}
        />

        {isOpen ? (
          <Pressable
            style={styles.fill}
            onPress={close}
            accessibilityRole="button"
            accessibilityLabel="Close menu"
          />
        ) : null}

        <Animated.View style={[styles.sidebar, sidebarStyle]}>
          {sidebar}
        </Animated.View>
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { flex: 1 },
  fill: { ...StyleSheet.absoluteFillObject },
  backdrop: { backgroundColor: "#000" },
  sidebar: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    width: DRAWER_WIDTH,
  },
});
