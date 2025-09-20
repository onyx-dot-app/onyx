"use client";

import React from "react";
import Text from "@/components-2/Text";

const variantClasses = {
  secondary: "bg-background-tint-01 hover:bg-background-tint-02",
  danger: "bg-action-danger-05 hover:bg-action-danger-04",
} as const;

interface ButtonProps extends React.HTMLAttributes<HTMLButtonElement> {
  secondary?: boolean;
  danger?: boolean;
}

export default function Button({
  children,
  className,
  secondary,
  danger,
  ...props
}: ButtonProps) {
  const variant = danger ? "danger" : secondary ? "secondary" : "secondary";

  return (
    <button
      className={`p-spacing-interline rounded-08 border ${variantClasses[variant]} ${className}`}
      {...props}
    >
      {typeof children === "string" ? <Text>{children}</Text> : children}
    </button>
  );
}
