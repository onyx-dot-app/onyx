import type { ReactNode } from "react";
import { Pressable, View, type PressableProps } from "react-native";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";
import { Text, type TextColor, type TextFont } from "@/components/opal/Text";

export type ButtonVariant = "default" | "action" | "danger" | "none";
export type ButtonProminence = "primary" | "secondary" | "tertiary";
export type ButtonSize = "lg" | "md" | "sm" | "xs";

// Static class strings only — NativeWind scans these at build time.
const containerVariants = cva(
  "flex-row items-center justify-center gap-1",
  {
    variants: {
      variant: {
        default: "",
        action: "",
        danger: "",
        none: "",
      },
      prominence: {
        primary: "",
        secondary: "border bg-transparent",
        tertiary: "bg-transparent",
      },
      size: {
        lg: "h-10 px-4 rounded-[12px]",
        md: "h-9 px-3.5 rounded-[8px]",
        sm: "h-8 px-3 rounded-[8px]",
        xs: "h-7 px-2.5 rounded-[4px]",
      },
      disabled: {
        true: "opacity-50",
        false: "",
      },
    },
    // (variant × prominence) → bg/border colors; static strings the NativeWind scanner sees verbatim.
    compoundVariants: [
      { variant: "default", prominence: "primary", className: "bg-theme-primary-05" },
      { variant: "default", prominence: "secondary", className: "border-border-02" },
      { variant: "default", prominence: "tertiary", className: "" },
      { variant: "action", prominence: "primary", className: "bg-action-link-05" },
      { variant: "action", prominence: "secondary", className: "border-action-link-05" },
      { variant: "action", prominence: "tertiary", className: "" },
      { variant: "danger", prominence: "primary", className: "bg-status-error-05" },
      { variant: "danger", prominence: "secondary", className: "border-action-danger-05" },
      { variant: "danger", prominence: "tertiary", className: "" },
      { variant: "none", prominence: "primary", className: "" },
      { variant: "none", prominence: "secondary", className: "border-border-02" },
      { variant: "none", prominence: "tertiary", className: "" },
    ],
    defaultVariants: {
      variant: "default",
      prominence: "primary",
      size: "md",
      disabled: false,
    },
  },
);

// Label color token per (variant × prominence) — resolved by Text via style, not a dynamic className.
const LABEL_COLOR: Record<ButtonVariant, Record<ButtonProminence, TextColor>> = {
  default: {
    primary: "text-inverted-05",
    secondary: "text-05",
    tertiary: "text-04",
  },
  action: {
    primary: "text-inverted-05",
    secondary: "action-text-link-05",
    tertiary: "action-text-link-05",
  },
  danger: {
    primary: "text-inverted-05",
    secondary: "action-text-danger-05",
    tertiary: "action-text-danger-05",
  },
  none: {
    primary: "text-05",
    secondary: "text-05",
    tertiary: "text-04",
  },
};

const LABEL_FONT: Record<ButtonSize, TextFont> = {
  lg: "main-ui-body",
  md: "main-ui-body",
  sm: "secondary-body",
  xs: "secondary-body",
};

type ContainerVariantProps = VariantProps<typeof containerVariants>;

interface ButtonProps extends Omit<PressableProps, "children" | "disabled" | "style"> {
  variant?: ButtonVariant;
  prominence?: ButtonProminence;
  size?: ButtonSize;
  disabled?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  className?: string;
  children?: ReactNode;
}

// Native mirror of web Opal Button.
function Button({
  variant = "default",
  prominence = "primary",
  size = "md",
  disabled = false,
  leftIcon,
  rightIcon,
  className,
  children,
  ...pressableProps
}: ButtonProps) {
  const labelColor = LABEL_COLOR[variant][prominence];
  const labelFont = LABEL_FONT[size];

  const containerProps: ContainerVariantProps = {
    variant,
    prominence,
    size,
    disabled,
  };

  return (
    <Pressable disabled={disabled} {...pressableProps}>
      <View className={cn(containerVariants(containerProps), className)}>
        {leftIcon}
        {typeof children === "string" ? (
          <Text font={labelFont} color={labelColor}>
            {children}
          </Text>
        ) : (
          children
        )}
        {rightIcon}
      </View>
    </Pressable>
  );
}

export { Button, type ButtonProps };
