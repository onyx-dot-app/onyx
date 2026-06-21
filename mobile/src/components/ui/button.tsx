// React Native port of web's Opal Button
// (web/lib/opal/src/components/buttons/button/components.tsx); the color matrix
// and sizing live in button.styles. Web "hover" maps to RN "pressed". Spacing
// uses margins, not `gap-*` (unreliable in RN/NativeWind — see SidebarTab).
// `children` is plain string; web's RichStr/markdown is intentionally unsupported.
import { Pressable, View } from "react-native";
import { router, type Href } from "expo-router";
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

type ButtonBaseProps = InteractiveContract & {
  /** Size preset. @default "lg" */
  size?: ButtonSize;
  /** `"fit"` shrink-wraps to content; `"full"` stretches to parent. @default "fit" */
  width?: ButtonWidth;
  /**
   * Forces the pressed visual without a touch (e.g. an open popover trigger).
   * @default "rest"
   */
  interaction?: ButtonInteraction;
  rightIcon?: IconFunctionComponent;
  onPress?: () => void;
  /** Navigates here on press (expo-router). */
  href?: Href;
  /** Accepted for web API parity; a no-op on touch. */
  tooltip?: string;
  /** Layout overrides, applied to the outer pressable. */
  className?: string;
  /** Screen-reader name — required for icon-only buttons (they have no text). */
  accessibilityLabel?: string;
};

// Mirrors web's discriminated `ButtonContentProps`: a label or a leading icon,
// never neither. Icon-only (no children) must supply `accessibilityLabel` —
// with no text, a screen reader would otherwise announce just "button".
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
    // disabled Pressable already blocks onPress — no guard needed
    onPress?.();
    if (href != null) router.navigate(href);
  }

  return (
    <Pressable
      disabled={disabled}
      onPress={handlePress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled }}
      // RN stretches flex children on the cross axis, so `fit` needs `self-start`
      // to shrink-wrap like web's `w-fit` (RN has no `fit-content`).
      className={cn(width === "full" ? "w-full" : "self-start", className)}
    >
      {({ pressed }) => {
        const state = resolveButtonState(disabled, interaction, pressed);
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
            {icon ? (
              <View className={cn("items-center justify-center", spec.iconPad)}>
                <Icon as={icon} size={spec.iconSize} className={colors.fg} />
              </View>
            ) : null}

            {hasLabel ? (
              // `mx-4` reproduces web's `gap-1` around the label (RN `gap-*` is
              // unreliable). `shrink` + `ellipsizeMode="clip"` clip a long label
              // (matching web) instead of pushing the trailing icon out.
              <Text
                font={spec.font}
                numberOfLines={1}
                ellipsizeMode="clip"
                className={cn("mx-4 shrink", colors.fg)}
              >
                {children}
              </Text>
            ) : null}

            {rightIcon ? (
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
