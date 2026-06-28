// Spacing uses margins, not `gap-*` (unreliable in RN/NativeWind).
import { ActivityIndicator, Pressable, View } from "react-native";
import { router, type Href } from "expo-router";
import { cssInterop } from "nativewind";
import type { InteractiveContract } from "@onyx-ai/shared/contracts";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";
import {
  BUTTON_COLORS,
  BUTTON_SIZES,
  resolveButtonState,
  type ButtonInteraction,
  type ButtonSize,
  type ButtonWidth,
} from "@/components/ui/button.styles";

// ActivityIndicator ignores `style.color`; bridge the text-color class onto its `color` prop.
const Spinner = cssInterop(ActivityIndicator, {
  className: { target: false, nativeStyleToProp: { color: "color" } },
}) as React.ComponentType<{ className?: string; size?: "small" | "large" }>;

type ButtonBaseProps = InteractiveContract & {
  size?: ButtonSize;
  width?: ButtonWidth;
  interaction?: ButtonInteraction;
  loading?: boolean;
  rightIcon?: IconFunctionComponent;
  onPress?: () => void;
  href?: Href;
  tooltip?: string;
  className?: string;
  // Required for icon-only buttons — without text a screen reader announces just "button".
  accessibilityLabel?: string;
};

// A label or a leading icon, never neither; icon-only must supply `accessibilityLabel`.
type ButtonProps = ButtonBaseProps &
  (
    | { icon?: IconFunctionComponent; children: string }
    | {
        icon: IconFunctionComponent;
        children?: string;
        accessibilityLabel: string;
      }
  );

function Button({
  variant = "default",
  prominence = "primary",
  size = "lg",
  width = "fit",
  interaction = "rest",
  disabled = false,
  loading = false,
  accessibilityLabel,
  icon,
  rightIcon,
  children,
  onPress,
  href,
  className,
}: ButtonProps) {
  const spec = BUTTON_SIZES[size];
  const hasLabel = children != null;

  function handlePress() {
    // disabled/loading Pressable already blocks onPress — no guard needed
    onPress?.();
    if (href != null) router.navigate(href);
  }

  return (
    <Pressable
      disabled={disabled || loading}
      onPress={handlePress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: disabled || loading, busy: loading }}
      // RN stretches flex children cross-axis; `self-start` shrink-wraps `fit` (no `fit-content`).
      className={cn(width === "full" ? "w-full" : "self-start", className)}
    >
      {({ pressed }) => {
        const state = resolveButtonState(
          disabled || loading,
          interaction,
          pressed,
        );
        const colors = BUTTON_COLORS[variant][prominence][state];
        return (
          <View
            className={cn(
              "flex-row items-center justify-center overflow-hidden",
              spec.height,
              spec.minWidth,
              spec.padding,
              spec.rounding,
              width === "full" && "w-full",
              colors.bg,
              colors.border,
            )}
          >
            {loading ? (
              <View className={cn("items-center justify-center", spec.iconPad)}>
                <Spinner size="small" className={colors.fg} />
              </View>
            ) : icon ? (
              <View className={cn("items-center justify-center", spec.iconPad)}>
                <Icon as={icon} size={spec.iconSize} className={colors.fg} />
              </View>
            ) : null}

            {hasLabel ? (
              // `mx-4` substitutes for `gap-*`; `shrink`+clip trims a long label
              // instead of pushing the trailing icon out.
              <Text
                font={spec.font}
                numberOfLines={1}
                ellipsizeMode="clip"
                className={cn("mx-4 shrink", colors.fg)}
              >
                {children}
              </Text>
            ) : null}

            {!loading && rightIcon ? (
              <View
                className={cn(
                  "items-center justify-center",
                  spec.iconPad,
                  // a label's `mx-4` already spaces this; only an icon-only pair needs it
                  !hasLabel && icon != null && "ml-4",
                )}
              >
                <Icon
                  as={rightIcon}
                  size={spec.iconSize}
                  className={colors.fg}
                />
              </View>
            ) : null}
          </View>
        );
      }}
    </Pressable>
  );
}

export { Button, type ButtonProps };
