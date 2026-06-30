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
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import SvgSidebar from "@/icons/sidebar";
import { useSidebar } from "@/components/sidebar/SidebarProvider";
import {
  SIDEBAR_ANIM_MS,
  SIDEBAR_WIDTH_EXPANDED,
} from "@/components/sidebar/interfaces";

interface SidebarRootProps {
  foldable?: boolean;
  children: React.ReactNode;
}

function SidebarRoot({ children }: SidebarRootProps) {
  const { folded, setFolded } = useSidebar();
  const insets = useSafeAreaInsets();

  // Derived from `folded` so the slide stays state-driven (no effect mutation): 1 = open, 0 = closed.
  const progress = useDerivedValue(
    () => withTiming(folded ? 0 : 1, { duration: SIDEBAR_ANIM_MS }),
    [folded],
  );

  // Live swipe offset, mutated only in the Pan worklet; layers on `progress` for 1:1 finger tracking.
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

  // Swipe-left-to-close; `activeOffsetX` gates to horizontal so vertical scroll falls through to Body.
  const pan = Gesture.Pan()
    .activeOffsetX([-15, 15])
    .onUpdate((e) => {
      drag.value = Math.min(0, e.translationX);
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
        {/* Tap-to-close backdrop. Web's ~1px backdrop-blur is dropped — no mobile token. */}
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

interface SidebarHeaderProps {
  logo?: (folded: boolean | undefined) => React.ReactNode;
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
          <Button
            prominence="internal"
            icon={SvgSidebar}
            accessibilityLabel="Collapse sidebar"
            onPress={() => setFolded(true)}
          />
        </View>
      )}
      {children != null && <View className="px-2">{children}</View>}
    </View>
  );
}

interface SidebarBodyProps {
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

interface SidebarFooterProps {
  children?: React.ReactNode;
}

function SidebarFooter({ children }: SidebarFooterProps) {
  return <View className="px-2 pt-4">{children}</View>;
}

interface SidebarSectionProps {
  title?: string;
  action?: React.ReactNode;
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
