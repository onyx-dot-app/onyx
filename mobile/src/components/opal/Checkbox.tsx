import { Pressable, View } from "react-native";
import * as CheckboxPrimitive from "@rn-primitives/checkbox";

import { cn } from "@/lib/cn";
import { Text } from "@/components/opal/Text";
import { useToken } from "@/theme/ThemeProvider";

// ---------------------------------------------------------------------------
// Checkbox — a themed checkbox built on @rn-primitives/checkbox.
//
//   <Checkbox checked={v} onCheckedChange={setV} label="Remember me" />
//
// Checked  → `theme-primary-05` fill + a check glyph (inverted-text color).
// Unchecked → transparent box with a `border-03` border.
// Disabled  → dimmed + non-interactive.
// ---------------------------------------------------------------------------

interface CheckboxProps {
  /** Whether the box is checked. Controlled. */
  checked: boolean;
  /** Called with the next checked state on press. */
  onCheckedChange: (checked: boolean) => void;
  /** Disable interaction + dim. Default: false. */
  disabled?: boolean;
  /** Optional label rendered next to the box via the Opal `Text` component. */
  label?: string;
  /** Extra classes merged onto the outer row. */
  className?: string;
}

/**
 * A small tick drawn with two borders of a rotated View — avoids pulling in an
 * icon/svg dependency. Color comes from the `text-inverted-05` token (resolved
 * through `style`, never a dynamic className) so it reads on the filled box in
 * both light and dark schemes.
 */
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

/**
 * Native mirror of the Opal `Checkbox`. The box background/border is a fixed
 * two-state set, so it uses STATIC NativeWind classes toggled on `checked`; the
 * check glyph color is a doc-03 token applied via `style`.
 */
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
