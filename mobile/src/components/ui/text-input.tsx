// React Native counterpart of web Opal's `InputTypeIn`
// (web/lib/opal/src/components/inputs/input-type-in/components.tsx): a controlled
// field shell with a `variant` for idle/error/disabled/readOnly. RHF-agnostic — it
// only sees value/onChangeText/onBlur, so it's reusable anywhere. `PasswordTextInput`
// adds the show/hide reveal toggle.
import { cva, type VariantProps } from "class-variance-authority";
import { cssInterop } from "nativewind";
import { useState, type ReactNode, type Ref } from "react";
import {
  Pressable,
  TextInput as RNTextInput,
  View,
  type TextInputProps as RNTextInputProps,
  type TextStyle,
} from "react-native";
import { textPresets } from "@onyx-ai/shared/native";

import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";
import type { IconFunctionComponent } from "@/icons/types";
import SvgEye from "@/icons/eye";
import SvgEyeOff from "@/icons/eye-off";

// `placeholderTextColor` is a prop, not a style, so a NativeWind class can't reach
// it. Bridge a `placeholderClassName` → resolved color → the prop, keeping the
// placeholder on the token system (dark-mode aware). Mirrors the `Icon` wrapper.
const FieldTextInput = cssInterop(RNTextInput, {
  className: { target: "style" },
  placeholderClassName: {
    target: false,
    nativeStyleToProp: { color: "placeholderTextColor" },
  },
}) as React.ComponentType<
  RNTextInputProps & {
    ref?: Ref<RNTextInput>;
    className?: string;
    placeholderClassName?: string;
  }
>;

const fieldShell = cva(
  "h-40 w-full flex-row items-center rounded-08 border px-12",
  {
    variants: {
      variant: {
        idle: "border-border-01 bg-background-tint-00",
        error: "border-status-error-05 bg-background-tint-00",
        disabled: "border-border-01 bg-background-tint-01",
        readOnly: "border-border-01 bg-background-tint-01",
      },
    },
    defaultVariants: { variant: "idle" },
  },
);

export type TextInputVariant = NonNullable<
  VariantProps<typeof fieldShell>["variant"]
>;

export interface TextInputProps extends Omit<RNTextInputProps, "editable"> {
  ref?: Ref<RNTextInput>;
  /** Drives border + background tokens (and editability). @default "idle" */
  variant?: TextInputVariant;
  /** Leading icon rendered inside the field (e.g. search). */
  leftIcon?: IconFunctionComponent;
  /** Trailing content inside the field (e.g. the password reveal button). */
  rightSlot?: ReactNode;
  className?: string;
}

function TextInput({
  variant = "idle",
  leftIcon,
  rightSlot,
  className,
  style,
  ...rest
}: TextInputProps) {
  const editable = variant !== "disabled" && variant !== "readOnly";
  const muted = variant === "disabled" || variant === "readOnly";
  return (
    <View className={cn(fieldShell({ variant }), className)}>
      {leftIcon ? (
        <Icon as={leftIcon} size={16} className="mr-8 text-text-03" />
      ) : null}
      <FieldTextInput
        editable={editable}
        accessibilityState={
          variant === "disabled" ? { disabled: true } : undefined
        }
        placeholderClassName="text-text-03"
        className={cn("flex-1", muted ? "text-text-03" : "text-text-04")}
        style={[textPresets["main-ui-body"] as TextStyle, style]}
        {...rest}
      />
      {rightSlot ? <View className="ml-8">{rightSlot}</View> : null}
    </View>
  );
}

export interface PasswordTextInputProps extends Omit<
  TextInputProps,
  "rightSlot" | "secureTextEntry" | "leftIcon"
> {
  /** When false the value stays masked with no reveal toggle. @default true */
  revealable?: boolean;
}

function PasswordTextInput({
  revealable = true,
  autoCapitalize,
  autoComplete,
  textContentType,
  ...rest
}: PasswordTextInputProps) {
  const [revealed, setRevealed] = useState(false);
  return (
    <TextInput
      {...rest}
      secureTextEntry={!revealed}
      autoCapitalize={autoCapitalize ?? "none"}
      autoComplete={autoComplete ?? "password"}
      textContentType={textContentType ?? "password"}
      rightSlot={
        revealable ? (
          <Pressable
            onPress={() => setRevealed((value) => !value)}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={revealed ? "Hide password" : "Show password"}
          >
            <Icon
              as={revealed ? SvgEyeOff : SvgEye}
              size={16}
              className="text-text-03"
            />
          </Pressable>
        ) : undefined
      }
    />
  );
}

export { TextInput, PasswordTextInput };
