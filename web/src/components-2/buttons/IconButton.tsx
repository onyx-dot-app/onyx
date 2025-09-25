"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";

const buttonClasses = (active: boolean | undefined) =>
  ({
    primary: {
      main: [
        active ? "bg-theme-primary-06" : "bg-theme-primary-05",
        "hover:bg-theme-primary-04",
      ],
      disabled: ["bg-background-neutral-04"],
    },
    secondary: {
      main: [
        active ? "bg-background-tint-00" : "bg-background-tint-02",
        "hover:bg-background-tint-02",
        "border",
      ],
      disabled: ["bg-background-neutral-03"],
    },
    tertiary: {
      main: [
        active ? "bg-background-tint-00" : "bg-transparent",
        "hover:bg-background-tint-02",
      ],
      disabled: ["bg-background-neutral-02"],
    },
    internal: {
      main: [
        active ? "bg-background-tint-00" : "bg-transparent",
        "hover:bg-background-tint-00",
      ],
      disabled: ["bg-transparent"],
    },
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    primary: {
      main: ["stroke-text-inverted-05"],
      disabled: ["stroke-text-inverted-05"],
    },
    secondary: {
      main: [active ? "stroke-text-05" : "stroke-text-03"],
      disabled: ["stroke-text-01"],
    },
    tertiary: {
      main: [
        active ? "!stroke-text-05" : "stroke-text-03",
        "group-hover/IconButton:stroke-text-04",
      ],
      disabled: ["stroke-text-01"],
    },
    internal: {
      main: [
        active ? "!stroke-text-05" : "stroke-text-02",
        "group-hover/IconButton:stroke-text-04",
      ],
      disabled: ["stroke-text-01"],
    },
  }) as const;

export interface IconButtonProps
  extends React.HTMLAttributes<HTMLButtonElement> {
  // Button states:
  active?: boolean;
  disabled?: boolean;

  // Button variant:
  primary?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  internal?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  icon: React.FunctionComponent<SvgProps>;
}

export function IconButton({
  active,
  disabled,

  primary,
  secondary,
  tertiary,
  internal,

  onClick,
  icon: Icon,
  className,

  ...props
}: IconButtonProps) {
  const variant = primary
    ? "primary"
    : secondary
      ? "secondary"
      : tertiary
        ? "tertiary"
        : internal
          ? "internal"
          : "primary";
  const state = disabled ? "disabled" : "main";

  return (
    <button
      className={cn(
        "flex items-center justify-center group/IconButton",
        internal ? "p-spacing-inline" : "p-spacing-interline",
        disabled && "cursor-not-allowed",
        internal ? "rounded-08" : "rounded-12",
        buttonClasses(active)[variant][state],
        className
      )}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      {...props}
    >
      <Icon
        className={cn("h-[1rem] w-[1rem]", iconClasses(active)[variant][state])}
      />
    </button>
  );
}
