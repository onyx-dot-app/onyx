import { Pressable, View } from "react-native";
import * as CheckboxPrimitive from "@rn-primitives/checkbox";

import { cn } from "@/lib/cn";
import { Text } from "@/components/opal/Text";
import { useToken } from "@/theme/ThemeProvider";

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
  className?: string;
}

// Tick drawn with two borders of a rotated View — avoids pulling in an icon/svg dependency.
function CheckGlyph({ color }: { color: string }) {
  return (
    <View
      style={{
        width: 6,
        height: 10,
        borderRightWidth: 2,
        borderBottomWidth: 2,
        borderColor: color,
        transform: [{ rotate: "45deg" }],
        marginTop: -2,
      }}
    />
  );
}

// Native mirror of web Opal Checkbox.
function Checkbox({
  checked,
  onCheckedChange,
  disabled = false,
  label,
  className,
}: CheckboxProps) {
  const glyphColor = useToken("text-inverted-05");

  return (
    <Pressable
      disabled={disabled}
      onPress={() => onCheckedChange(!checked)}
      accessibilityRole="checkbox"
      accessibilityState={{ checked, disabled }}
      className={cn("flex-row items-center gap-2", disabled && "opacity-50", className)}
    >
      <CheckboxPrimitive.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cn(
          "h-5 w-5 items-center justify-center rounded-[4px] border",
          checked
            ? "border-theme-primary-05 bg-theme-primary-05"
            : "border-border-03 bg-transparent",
        )}
      >
        <CheckboxPrimitive.Indicator>
          <CheckGlyph color={glyphColor} />
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      {label ? (
        <Text font="main-ui-body" color="text-05">
          {label}
        </Text>
      ) : null}
    </Pressable>
  );
}

export { Checkbox, type CheckboxProps };
