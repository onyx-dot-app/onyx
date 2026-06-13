import * as React from "react";
import { Pressable, View } from "react-native";
import { router, type Href } from "expo-router";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";
import type { SidebarVariant } from "@/components/sidebar/interfaces";

// ---------------------------------------------------------------------------
// SidebarTab — React Native port of web's Opal SidebarTab
// (web/lib/opal/src/components/buttons/sidebar-tab/components.tsx), built on the
// `Interactive.Stateful` sidebar-heavy / sidebar-light color matrix
// (web/lib/opal/src/core/interactive/stateful/styles.css:543-662).
//
// Web "hover" → RN "pressed" (NativeWind's `active:` modifier on Pressable).
// All classes resolve to the same Onyx token hex as web.
// ---------------------------------------------------------------------------

interface SidebarTabColors {
  /** Selected background; empty/filled is transparent (omitted). */
  bg: string;
  /** Label foreground color class. */
  label: string;
  /** Icon foreground. */
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
    // All states use text-02 foreground; selected adds the tint-00 background.
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
  /** Collapses the label, showing only the icon (inert on phone — sidebar is open/closed). */
  folded?: boolean;
  /** Marks this tab as the currently active item. */
  selected?: boolean;
  /** Color variant. @default "sidebar-heavy" */
  variant?: SidebarVariant;
  /** Renders an empty spacer in place of the icon, for nested items. */
  nested?: boolean;
  /** Disables the tab — muted colors, suppressed press. */
  disabled?: boolean;
  onPress?: () => void;
  /** Optional route to navigate to on press (expo-router). */
  href?: Href;
  icon?: IconFunctionComponent;
  /** Content rendered on the right (e.g. a count or action). */
  rightChildren?: React.ReactNode;
  /** Accepted for web API parity; a no-op on touch. */
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
      {/* Leading slot — mirrors web's ContentSm (web/lib/opal/.../content/ContentSm.tsx
          + styles.css): a 16px icon inside a `p-0.5` container (the padding "around"
          the icon), then a 2px gap (web's `gap: 0.125rem`) before the label, or a
          matching spacer for nested items so labels align. Explicit margin instead of
          `gap`, which doesn't render reliably in RN/NativeWind. */}
      {nested ? (
        <View className="mr-0.5 w-5" aria-hidden />
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
