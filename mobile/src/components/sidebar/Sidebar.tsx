import * as React from "react";
import { Pressable, ScrollView, View } from "react-native";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useDerivedValue,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Portal } from "@rn-primitives/portal";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgSidebar from "@/icons/sidebar";
import { useSidebar } from "@/components/sidebar/SidebarProvider";
import {
  SIDEBAR_ANIM_MS,
  SIDEBAR_WIDTH_EXPANDED,
} from "@/components/sidebar/interfaces";

// ---------------------------------------------------------------------------
// SidebarLayouts — the RN sidebar shell (Root/Header/Body/Footer/Section). A
// full-height overlay that slides in from the left with a tinted backdrop:
//   • portalled above all screens via @rn-primitives/portal,
//   • reanimated translateX slide + backdrop opacity off the `folded` state,
//   • gesture-handler Pan for swipe-to-close (gated to horizontal so it doesn't
//     steal the Body ScrollView's vertical scroll),
//   • colors + typography from the shared design tokens.
// ---------------------------------------------------------------------------

interface SidebarRootProps {
  /** Kept for web API parity; the mobile overlay behaves the same regardless. */
  foldable?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({ children }: SidebarRootProps) {
  const { folded, setFolded } = useSidebar();
  const insets = useSafeAreaInsets();

  // `progress` is derived (read-only) from the React `folded` state: 1 = open,
  // 0 = closed (off-screen). Driving it via useDerivedValue keeps the open/close
  // animation purely state-driven — no manual shared-value mutation in an effect.
  const progress = useDerivedValue(
    () => withTiming(folded ? 0 : 1, { duration: SIDEBAR_ANIM_MS }),
    [folded],
  );

  // `drag` is a live swipe offset, mutated ONLY inside the Pan worklet and read by
  // the animated styles — it layers on top of `progress` so a finger drag tracks 1:1.
  const drag = useSharedValue(0);

  const columnStyle = useAnimatedStyle(() => {
    const base = (progress.value - 1) * SIDEBAR_WIDTH_EXPANDED;
    return { transform: [{ translateX: Math.min(0, base + drag.value) }] };
  });

  const backdropStyle = useAnimatedStyle(() => {
    const dragFade = 1 + drag.value / SIDEBAR_WIDTH_EXPANDED;
    return { opacity: progress.value * Math.max(0, Math.min(1, dragFade)) };
  });

  const close = React.useCallback(() => setFolded(true), [setFolded]);

  // Swipe left on the column to close. `activeOffsetX` gates activation to
  // horizontal movement, letting vertical scroll fall through to the Body. Built
  // inline (not via a hook) so `drag` isn't treated as a frozen hook argument —
  // useSharedValue refs are stable, so re-creating the gesture object is cheap and
  // the Root only re-renders when `folded` flips.
  const pan = Gesture.Pan()
    .activeOffsetX([-15, 15])
    .onUpdate((e) => {
      drag.value = Math.min(0, e.translationX); // leftward only
    })
    .onEnd((e) => {
      const shouldClose =
        e.translationX < -SIDEBAR_WIDTH_EXPANDED / 3 || e.velocityX < -500;
      drag.value = withTiming(0, { duration: SIDEBAR_ANIM_MS });
      if (shouldClose) runOnJS(setFolded)(true);
    });

  return (
    <Portal name="sidebar">
      <View
        pointerEvents={folded ? "none" : "auto"}
        className="absolute inset-0 z-50"
      >
        {/* Tinted backdrop (web `bg-mask-03`; the ~1px backdrop-blur is dropped — not
            a mobile token). Tap to close. */}
        <Animated.View style={backdropStyle} className="absolute inset-0">
          <Pressable className="flex-1 bg-mask-03" onPress={close} />
        </Animated.View>

        <GestureDetector gesture={pan}>
          <Animated.View
            style={[
              columnStyle,
              {
                width: SIDEBAR_WIDTH_EXPANDED,
                paddingTop: insets.top,
                paddingBottom: insets.bottom,
              },
            ]}
            className="absolute bottom-0 left-0 top-0 bg-background-tint-02 pb-2"
          >
            <View className="min-h-0 flex-1 flex-col">{children}</View>
          </Animated.View>
        </GestureDetector>
      </View>
    </Portal>
  );
}

// ---------------------------------------------------------------------------
// Header — topbar (logo + close button) with optional pinned content below
// ---------------------------------------------------------------------------

interface SidebarHeaderProps {
  logo?: (folded: boolean | undefined) => React.ReactNode;
  /** Kept for web API parity (no hover on touch). */
  showLogoWhenFolded?: boolean;
  children?: React.ReactNode;
}

function SidebarHeader({ logo, children }: SidebarHeaderProps) {
  const { folded, setFolded } = useSidebar();
  const logoEl = logo != null ? logo(folded) : null;

  if (logoEl == null && children == null) return null;

  return (
    <View className="gap-4 pb-2">
      {logoEl != null && (
        <View className="flex-row items-start justify-between px-2 pt-3">
          {logoEl}
          <Pressable
            onPress={() => setFolded(true)}
            hitSlop={8}
            className="rounded-08 p-1 active:bg-background-tint-03"
          >
            <Icon as={SvgSidebar} size={20} className="text-text-03" />
          </Pressable>
        </View>
      )}
      {children != null && <View className="px-2">{children}</View>}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Body — scrollable content area
// ---------------------------------------------------------------------------

interface SidebarBodyProps {
  /** Accepted for web API parity; scroll-offset persistence is out of scope for the shell. */
  scrollKey?: string;
  children?: React.ReactNode;
}

function SidebarBody({ children }: SidebarBodyProps) {
  return (
    <ScrollView className="min-h-0 flex-1" showsVerticalScrollIndicator={false}>
      <View className="gap-2 px-2 pb-8">{children}</View>
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Footer — pinned content below the scroll area
// ---------------------------------------------------------------------------

interface SidebarFooterProps {
  children?: React.ReactNode;
}

function SidebarFooter({ children }: SidebarFooterProps) {
  return <View className="px-2 pt-4">{children}</View>;
}

// ---------------------------------------------------------------------------
// Section — titled group within the scrollable body
// ---------------------------------------------------------------------------

interface SidebarSectionProps {
  title?: string;
  /** Optional action (e.g. a "+" button); always visible on touch (no hover). */
  action?: React.ReactNode;
  /** Dims the section header to indicate it is unavailable. */
  disabled?: boolean;
  children?: React.ReactNode;
}

function SidebarSection({
  title,
  action,
  disabled,
  children,
}: SidebarSectionProps) {
  return (
    <View className="flex-col">
      {title ? (
        <View
          className={cn(
            "flex-row items-center justify-between pb-1 pl-2 pt-2",
            disabled && "opacity-50",
          )}
        >
          <View className="p-0.5">
            <Text font="secondary-body" className="text-text-02">
              {title}
            </Text>
          </View>
          {action != null && <View>{action}</View>}
        </View>
      ) : (
        <View className="h-2" />
      )}
      <View className="gap-1">{children}</View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Exports — mirror the web `SidebarLayouts` namespace
// ---------------------------------------------------------------------------

export const SidebarLayouts = {
  Root: SidebarRoot,
  Header: SidebarHeader,
  Body: SidebarBody,
  Footer: SidebarFooter,
  Section: SidebarSection,
};

export type {
  SidebarRootProps,
  SidebarHeaderProps,
  SidebarBodyProps,
  SidebarFooterProps,
  SidebarSectionProps,
};
