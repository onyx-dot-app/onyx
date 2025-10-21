"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";

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
    danger: {
      main: [
        active ? "bg-action-danger-06" : "bg-action-danger-05",
        "hover:bg-action-danger-04",
      ],
      disabled: ["bg-action-danger-02"],
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
      main: [
        active ? "stroke-text-05" : "stroke-text-03",
        "group-hover/IconButton:stroke-text-04",
      ],
      disabled: ["stroke-text-01"],
    },
    tertiary: {
      main: [
        active ? "!stroke-text-05" : "stroke-text-03",
        "group-hover/IconButton:stroke-text-04",
      ],
      disabled: ["stroke-text-01"],
    },
    danger: {
      main: ["stroke-text-light-05"],
      disabled: ["stroke-text-light-05"],
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
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  // Button states:
  active?: boolean;
  disabled?: boolean;

  // Button variant:
  primary?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  internal?: boolean;
  danger?: boolean;

  // Button properties:
  onHover?: (isHovering: boolean) => void;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  icon: React.FunctionComponent<SvgProps>;
  tooltip?: string;
}

export default function IconButton({
  active,
  disabled,

  primary,
  secondary,
  tertiary,
  internal,
  danger,

  onHover,
  onClick,
  icon: Icon,
  className,
  tooltip,

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
          : danger
            ? "danger"
            : "primary";
  const state = disabled ? "disabled" : "main";

  const buttonElement = (
    <button
      className={cn(
        "flex items-center justify-center h-fit w-fit group/IconButton",
        internal ? "p-spacing-inline" : "p-spacing-interline",
        disabled && "cursor-not-allowed",
        internal ? "rounded-08" : "rounded-12",
        buttonClasses(active)[variant][state],
        className
      )}
      onClick={disabled ? undefined : onClick}
      onMouseEnter={(e) => {
        props.onMouseEnter?.(e);
        if (!disabled) onHover?.(true);
      }}
      onMouseLeave={(e) => {
        props.onMouseLeave?.(e);
        if (!disabled) onHover?.(false);
      }}
      disabled={disabled}
      {...props}
    >
      <Icon
        className={cn("h-[1rem] w-[1rem]", iconClasses(active)[variant][state])}
      />
    </button>
  );

  if (!tooltip) return buttonElement;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{buttonElement}</TooltipTrigger>
        <TooltipContent side="top">
          <Text inverted>{tooltip}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
