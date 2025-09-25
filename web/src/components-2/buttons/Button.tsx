"use client";

import React from "react";
import Text from "@/components-2/Text";
import { cn } from "@/lib/utils";

const variantClasses = (active: boolean | undefined) =>
  ({
    primary: {
      main: [],
      secondary: [
        active ? "bg-background-tint-00" : "bg-background-tint-01",
        "hover:bg-background-tint-02",
        "border",
      ],
      tertiary: [],
      disabled: [],
    },
    action: {
      main: [],
      secondary: [],
      tertiary: [],
      disabled: [],
    },
    danger: {
      main: [
        active ? "bg-action-danger-06" : "bg-action-danger-05",
        "hover:bg-action-danger-04",
      ],
      secondary: [],
      tertiary: [],
      disabled: [],
    },
  }) as const;

const textClasses = (active: boolean | undefined) =>
  ({
    primary: {
      main: ["text-text-inverted-05"],
      secondary: [
        active ? "text-text-05" : "text-text-03",
        "group-hover:text-text-04",
      ],
      tertiary: [],
      disabled: ["text-text-01"],
    },
    action: {
      main: ["text-text-inverted-05"],
      secondary: [],
      tertiary: [],
      disabled: [],
    },
    danger: {
      main: ["text-text-inverted-05"],
      secondary: [],
      tertiary: [],
      disabled: [],
    },
  }) as const;

interface ButtonProps extends React.HTMLAttributes<HTMLButtonElement> {
  // Button variants:
  primary?: boolean;
  action?: boolean;
  danger?: boolean;

  // Button subvariants:
  main?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  disabled?: boolean;

  // Button states:
  active?: boolean;
}

export default function Button({
  primary,
  action,
  danger,

  main,
  secondary,
  tertiary,
  disabled,

  active,

  children,
  className,
  ...props
}: ButtonProps) {
  const variant = primary
    ? "primary"
    : action
      ? "action"
      : danger
        ? "danger"
        : "primary";

  const subvariant = main
    ? "main"
    : secondary
      ? "secondary"
      : tertiary
        ? "tertiary"
        : disabled
          ? "disabled"
          : "main";

  return (
    <button
      className={cn(
        "p-spacing-interline rounded-08 group",
        variantClasses(active)[variant][subvariant]
        // className,
      )}
      {...props}
    >
      {typeof children === "string" ? (
        <Text className={cn(textClasses(active)[variant][subvariant])}>
          {children}
        </Text>
      ) : (
        children
      )}
    </button>
  );
}
