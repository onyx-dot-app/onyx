// Button — React Native port of web's Opal Button
// (web/lib/opal/src/components/buttons/button/components.tsx), built on the
// `Interactive.Stateless` variant × prominence color matrix. `variant` /
// `prominence` / `disabled` come from the shared @onyx-ai/shared InteractiveContract
// so the API can't drift from web; the color matrix + sizing live in button.styles.
//
// Web "hover" → RN "pressed" (Pressable's pressed state). All classes resolve to
// the same Onyx token as web. Spacing uses explicit margins, not `gap-*`, which is
// unreliable in RN/NativeWind (see SidebarTab).
//
// `children` is a plain string — web's `RichStr`/markdown is intentionally
// unsupported here, pending the mobile Text reconciliation noted in text.tsx.
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
  /** Size preset — controls height, padding, rounding, label + icon size. @default "lg" */
  size?: ButtonSize;
  /** `"fit"` shrink-wraps to content; `"full"` stretches to parent. @default "fit" */
  width?: ButtonWidth;
  /**
   * Forces the pressed visual without a touch (e.g. an open-popover trigger).
   * Touch has no hover, so there is no `"hover"`. @default "rest"
   */
  interaction?: ButtonInteraction;
  /** Trailing icon. */
  rightIcon?: IconFunctionComponent;
  onPress?: () => void;
  /** Optional route to navigate to on press (expo-router). */
  href?: Href;
  /** Accepted for web API parity; a no-op on touch. */
  tooltip?: string;
  /** Layout/positioning overrides applied to the outer pressable. */
  className?: string;
  /**
   * Screen-reader name. Required for icon-only buttons (which have no text to
   * derive a name from); labeled buttons name themselves from their text.
   */
  accessibilityLabel?: string;
};

// Mirrors web's discriminated `ButtonContentProps`: a button must have a label
// OR a leading icon (an icon-only button omits children) — never neither.
type ButtonProps = ButtonBaseProps &
  (
    | { icon?: IconFunctionComponent; children: string }
    | { icon: IconFunctionComponent; children?: string }
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
    // A disabled Pressable already blocks onPress, so no guard is needed here.
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
      // RN flex children stretch on the cross axis by default, so `fit` needs an
      // explicit `self-start` to shrink-wrap like web's `w-fit` (RN has no
      // `fit-content`); `full` stretches. Caller `className` (layout only) wins last.
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
              // `mx-4` reproduces web's `gap-1` (4px) on each side of the label —
              // the gap to a leading/trailing icon, or the symmetric inset web
              // gets from its empty spacer divs when an icon is absent. `shrink`
              // lets the label clip (not push the trailing icon out) in a
              // constrained width; `ellipsizeMode="clip"` matches web's hard clip
              // (no ellipsis) instead of RN's default tail "…".
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
                  // With a label, its `mx-4` already spaces the trailing icon;
                  // for an icon-only pair, add the 4px gap here.
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
