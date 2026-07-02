import { cva, type VariantProps } from "class-variance-authority";
import { cssInterop } from "nativewind";
import { useCallback, useRef, useState, type ReactNode, type Ref } from "react";
import {
  Pressable,
  TextInput as RNTextInput,
  View,
  type TextInputProps as RNTextInputProps,
  type TextStyle,
} from "react-native";
import { textPresets } from "@onyx-ai/shared/native";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { cn } from "@/lib/utils";
import type { IconFunctionComponent } from "@/icons/types";
import SvgEye from "@/icons/eye";
import SvgEyeClosed from "@/icons/eye-closed";
import SvgX from "@/icons/x";

// `placeholderTextColor` is a prop, not a style — bridge a class to it via cssInterop.
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
        idle: "border-border-01 bg-background-neutral-00",
        internal: "border-transparent bg-transparent",
        error: "border-status-error-05 bg-background-neutral-00",
        disabled: "border-transparent bg-background-neutral-03",
        readOnly: "border-border-01 bg-transparent",
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
  variant?: TextInputVariant;
  leftIcon?: IconFunctionComponent;
  prefixText?: string;
  rightSlot?: ReactNode;
  clearButton?: boolean;
  className?: string;
}

function TextInput({
  ref,
  variant = "idle",
  leftIcon,
  prefixText,
  rightSlot,
  clearButton = false,
  className,
  style,
  value,
  onChangeText,
  onFocus,
  onBlur,
  ...rest
}: TextInputProps) {
  const editable = variant !== "disabled" && variant !== "readOnly";
  const [focused, setFocused] = useState(false);

  const innerRef = useRef<RNTextInput | null>(null);
  const setRef = useCallback(
    (node: RNTextInput | null) => {
      innerRef.current = node;
      if (typeof ref === "function") ref(node);
      else if (ref) ref.current = node;
    },
    [ref],
  );
  const focusInput = useCallback(() => {
    if (editable) innerRef.current?.focus();
  }, [editable]);

  const focusBorder = focused && variant === "idle" ? "border-border-05" : "";
  // Always mounted (stable input width), inert when empty.
  const hasValue = !!value;
  const showClear = clearButton && !rightSlot && editable;

  return (
    <Pressable
      accessible={false}
      onPress={focusInput}
      className={cn(fieldShell({ variant }), focusBorder, className)}
    >
      {leftIcon ? (
        <Icon as={leftIcon} size={16} className="mr-8 text-text-02" />
      ) : null}
      {prefixText ? (
        <Text font="main-ui-body" color="text-02">
          {prefixText}
        </Text>
      ) : null}
      <FieldTextInput
        ref={setRef}
        editable={editable}
        accessibilityState={
          variant === "disabled" ? { disabled: true } : undefined
        }
        placeholderClassName="text-text-02"
        className={cn(
          "flex-1",
          variant === "disabled" ? "text-text-02" : "text-text-04",
        )}
        style={[textPresets["main-ui-body"] as TextStyle, style]}
        value={value}
        onChangeText={onChangeText}
        onFocus={(e) => {
          setFocused(true);
          onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          onBlur?.(e);
        }}
        {...rest}
      />
      {showClear ? (
        <Pressable
          disabled={!hasValue}
          onPress={() => onChangeText?.("")}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Clear"
          pointerEvents={hasValue ? "auto" : "none"}
          className={cn("ml-8", !hasValue && "opacity-0")}
        >
          <Icon as={SvgX} size={16} className="text-text-03" />
        </Pressable>
      ) : null}
      {rightSlot ? <View className="ml-8">{rightSlot}</View> : null}
    </Pressable>
  );
}

// Backend secrets arrive as all-bullet placeholders; they can't be revealed.
const BACKEND_PLACEHOLDER = /^•+$/;

export interface PasswordTextInputProps extends Omit<
  TextInputProps,
  "rightSlot" | "secureTextEntry" | "leftIcon" | "clearButton"
> {
  revealable?: boolean;
}

function PasswordTextInput({
  revealable = true,
  value,
  autoCapitalize,
  autoComplete,
  textContentType,
  onFocus,
  onBlur,
  ...rest
}: PasswordTextInputProps) {
  // `revealed` deliberately persists across blur (matches web).
  const [revealed, setRevealed] = useState(false);
  const [focused, setFocused] = useState(false);

  const realValue = String(value ?? "");
  const nonRevealable =
    !revealable ||
    (realValue.length > 0 && BACKEND_PLACEHOLDER.test(realValue));
  const hidden = !revealed || nonRevealable;
  const showToggle = realValue.length > 0 || focused;
  const label = nonRevealable
    ? "Value cannot be revealed"
    : revealed
      ? "Hide password"
      : "Show password";

  return (
    <TextInput
      {...rest}
      value={value}
      secureTextEntry={hidden}
      autoCapitalize={autoCapitalize ?? "none"}
      // "new-password" so managers don't autofill a saved login into a secret field.
      autoComplete={autoComplete ?? "new-password"}
      textContentType={textContentType ?? "password"}
      onFocus={(e) => {
        setFocused(true);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      rightSlot={
        showToggle ? (
          <Pressable
            disabled={nonRevealable}
            onPress={() => setRevealed((v) => !v)}
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={label}
          >
            <Icon
              as={revealed && !nonRevealable ? SvgEye : SvgEyeClosed}
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
