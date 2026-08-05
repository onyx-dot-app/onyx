import * as React from "react";
import { Pressable, View } from "react-native";
import { router, type Href } from "expo-router";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";
import type { SidebarVariant } from "@/components/sidebar/interfaces";

interface SidebarTabColors {
  bg: string;
  label: string;
  icon: string;
}

function resolveColors(
  variant: SidebarVariant,
  selected: boolean,
  disabled: boolean,
): SidebarTabColors {
  if (disabled) {
    return { bg: "", label: "text-text-03", icon: "text-text-03" };
  }
  if (variant === "sidebar-light") {
    return {
      bg: selected ? "bg-background-tint-00" : "",
      label: "text-text-02",
      icon: "text-text-02",
    };
  }
  // sidebar-heavy
  if (selected) {
    return {
      bg: "bg-background-tint-00",
      label: "text-text-04",
      icon: "text-text-03",
    };
  }
  return { bg: "", label: "text-text-03", icon: "text-text-02" };
}

interface SidebarTabProps {
  folded?: boolean;
  selected?: boolean;
  variant?: SidebarVariant;
  nested?: boolean;
  disabled?: boolean;
  onPress?: () => void;
  href?: Href;
  icon?: IconFunctionComponent;
  // Leading-slot node (e.g. an agent avatar), used instead of `icon`.
  leading?: React.ReactNode;
  rightChildren?: React.ReactNode;
  tooltip?: string;
  children?: React.ReactNode;
}

function SidebarTab({
  folded,
  selected = false,
  variant = "sidebar-heavy",
  nested,
  disabled = false,
  onPress,
  href,
  icon,
  leading,
  rightChildren,
  children,
}: SidebarTabProps) {
  const colors = resolveColors(variant, selected, disabled);

  function handlePress() {
    // `disabled` Pressable already blocks onPress, so no guard needed here.
    onPress?.();
    if (href != null) router.navigate(href);
  }

  return (
    <Pressable
      disabled={disabled}
      onPress={handlePress}
      className={cn(
        "h-9 w-full flex-row items-center rounded-08 px-2",
        colors.bg,
        !disabled && "active:bg-background-tint-03",
        disabled && "opacity-50",
      )}
    >
      {/* Leading icon/avatar/spacer; explicit `mr-0.5` instead of `gap` (unreliable in RN/NativeWind). */}
      {nested ? (
        <View className="mr-0.5 w-5" aria-hidden />
      ) : leading ? (
        <View className="mr-0.5 items-center justify-center p-0.5">
          {leading}
        </View>
      ) : icon ? (
        <View className="mr-0.5 items-center justify-center p-0.5">
          <Icon as={icon} size={16} className={colors.icon} />
        </View>
      ) : null}

      {!folded && (
        <>
          {typeof children === "string" ? (
            <Text
              font="main-ui-body"
              numberOfLines={1}
              className={cn("flex-1", colors.label)}
            >
              {children}
            </Text>
          ) : (
            <View className="flex-1">{children}</View>
          )}

          {rightChildren && (
            <View className="ml-auto flex-row items-center">
              {rightChildren}
            </View>
          )}
        </>
      )}
    </Pressable>
  );
}

export { SidebarTab, type SidebarTabProps };
