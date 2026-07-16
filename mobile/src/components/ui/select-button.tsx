// Pill primitive, RN port of Opal SelectButton
// (web/lib/opal/src/components/buttons/select-button/). Shared by the deep-research toggle and the
// forced-tool chips. Web's `foldable` collapses the label to icon-only via a CSS :hover animation;
// touch has no hover, so mobile folds by simply not rendering the label — which is exactly what the
// deep-research use needs (icon-only when off, label when on: `foldable={!on}`).
import { Pressable, View } from "react-native";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";
import {
  resolveSelectState,
  SELECT_COLORS,
  type SelectState,
  type SelectVariant,
} from "@/components/ui/select-button.styles";

interface SelectButtonProps {
  icon?: IconFunctionComponent;
  children?: string;
  state?: SelectState;
  variant?: SelectVariant;
  // When true, the label is hidden (icon-only). Pass `foldable={!on}` for the deep-research pattern.
  foldable?: boolean;
  disabled?: boolean;
  onPress?: () => void;
  // Required when folded / icon-only so a screen reader has something to announce.
  accessibilityLabel?: string;
}

function SelectButton({
  icon,
  children,
  state = "empty",
  variant = "select-light",
  foldable = false,
  disabled = false,
  onPress,
  accessibilityLabel,
}: SelectButtonProps) {
  const showLabel = children != null && !foldable;

  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? children}
      accessibilityState={{ disabled, selected: state === "selected" }}
      className="self-start"
    >
      {({ pressed }) => {
        const colors =
          SELECT_COLORS[variant][state][resolveSelectState(disabled, pressed)];
        return (
          <View
            className={cn(
              "h-28 flex-row items-center justify-center overflow-hidden rounded-08 px-8",
              colors.bg,
            )}
          >
            {icon ? (
              <View className="items-center justify-center p-2">
                <Icon as={icon} size={16} className={colors.icon} />
              </View>
            ) : null}

            {showLabel ? (
              <Text
                font="main-ui-body"
                numberOfLines={1}
                ellipsizeMode="clip"
                className={cn("mx-4 shrink", colors.fg)}
              >
                {children}
              </Text>
            ) : null}
          </View>
        );
      }}
    </Pressable>
  );
}

export { SelectButton, type SelectButtonProps };
