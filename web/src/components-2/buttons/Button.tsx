"use client";

import React from "react";
import Text from "@/components-2/Text";

const variantClasses = {
  primary: "bg-theme-primary-05 hover:bg-theme-primary-04",
  secondary: "bg-background-tint-01 hover:bg-background-tint-02",
  danger: "bg-action-danger-05 hover:bg-action-danger-04",
} as const;

interface ButtonProps extends React.HTMLAttributes<HTMLButtonElement> {
  primary?: boolean;
  secondary?: boolean;
  danger?: boolean;
}

export default function Button({
  children,
  className,
  primary,
  secondary,
  danger,
  ...props
}: ButtonProps) {
  const variant = primary
    ? "primary"
    : secondary
      ? "secondary"
      : danger
        ? "danger"
        : "primary";

  return (
    <button
      className={`p-spacing-interline rounded-08 border ${variantClasses[variant]} ${className}`}
      {...props}
    >
      {typeof children === "string" ? (
        <Text inverted={variant === "primary"}>{children}</Text>
      ) : (
        children
      )}
    </button>
  );
}
