"use client";

import React, { useMemo } from "react";
import type { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

const buttonClasses = (transient: boolean | undefined) =>
  ({
    main: {
      primary: {
        enabled: [
          "bg-theme-primary-05",
          "hover:bg-theme-primary-04",
          transient && "bg-theme-primary-04",
          "active:bg-theme-primary-06",
        ],
        disabled: ["bg-background-neutral-04"],
      },
      secondary: {
        enabled: [
          "bg-background-tint-02",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-background-neutral-03"],
      },
      tertiary: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-transparent"],
      },
      internal: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-00",
          transient && "bg-background-tint-00",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-transparent"],
      },
    },
    action: {
      primary: {
        enabled: [
          "bg-action-link-05",
          "hover:bg-action-link-04",
          transient && "bg-action-link-04",
          "active:bg-action-link-06",
        ],
        disabled: ["bg-action-link-02"],
      },
      secondary: {
        enabled: [
          "bg-background-tint-02",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-background-neutral-02"],
      },
      tertiary: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-background-neutral-02"],
      },
      internal: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-00",
          transient && "bg-background-tint-00",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-transparent"],
      },
    },
    danger: {
      primary: {
        enabled: [
          "bg-action-danger-05",
          "hover:bg-action-danger-04",
          transient && "bg-action-danger-04",
          "active:bg-action-danger-06",
        ],
        disabled: ["bg-action-danger-02"],
      },
      secondary: {
        enabled: [
          "bg-background-tint-02",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-background-neutral-02"],
      },
      tertiary: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-background-neutral-02"],
      },
      internal: {
        enabled: [
          "bg-transparent",
          "hover:bg-background-tint-00",
          transient && "bg-background-tint-00",
          "active:bg-background-tint-00",
        ],
        disabled: ["bg-transparent"],
      },
    },
  }) as const;

const iconClasses = (transient: boolean | undefined) =>
  ({
    main: {
      primary: {
        enabled: ["stroke-text-inverted-05"],
        disabled: ["stroke-text-inverted-05"],
      },
      secondary: {
        enabled: [
          "stroke-text-03",
          "group-hover/IconButton:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/IconButton:stroke-text-05",
        ],
        disabled: ["stroke-text-01"],
      },
      tertiary: {
        enabled: [
          "stroke-text-03",
          "group-hover/IconButton:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/IconButton:stroke-text-05",
        ],
        disabled: ["stroke-text-01"],
      },
      internal: {
        enabled: [
          "stroke-text-02",
          "group-hover/IconButton:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/IconButton:stroke-text-05",
        ],
        disabled: ["stroke-text-01"],
      },
    },
    action: {
      primary: {
        enabled: ["stroke-text-light-05"],
        disabled: ["stroke-text-01"],
      },
      secondary: {
        enabled: [
          "stroke-action-link-05",
          "group-hover/IconButton:stroke-action-link-05",
          transient && "stroke-action-link-05",
          "group-active/IconButton:stroke-action-link-06",
        ],
        disabled: ["stroke-action-link-02"],
      },
      tertiary: {
        enabled: [
          "stroke-action-link-05",
          "group-hover/IconButton:stroke-action-link-05",
          transient && "stroke-action-link-05",
          "group-active/IconButton:stroke-action-link-06",
        ],
        disabled: ["stroke-action-link-02"],
      },
      internal: {
        enabled: [
          "stroke-action-link-05",
          "group-hover/IconButton:stroke-action-link-05",
          transient && "stroke-action-link-05",
          "group-active/IconButton:stroke-action-link-06",
        ],
        disabled: ["stroke-action-link-02"],
      },
    },
    danger: {
      primary: {
        enabled: ["stroke-text-light-05"],
        disabled: ["stroke-text-01"],
      },
      secondary: {
        enabled: [
          "stroke-action-danger-05",
          "group-hover/IconButton:stroke-action-danger-05",
          transient && "stroke-action-danger-05",
          "group-active/IconButton:stroke-action-danger-06",
        ],
        disabled: ["stroke-action-danger-02"],
      },
      tertiary: {
        enabled: [
          "stroke-action-danger-05",
          "group-hover/IconButton:stroke-action-danger-05",
          transient && "stroke-action-danger-05",
          "group-active/IconButton:stroke-action-danger-06",
        ],
        disabled: ["stroke-action-danger-02"],
      },
      internal: {
        enabled: [
          "stroke-action-danger-05",
          "group-hover/IconButton:stroke-action-danger-05",
          transient && "stroke-action-danger-05",
          "group-active/IconButton:stroke-action-danger-06",
        ],
        disabled: ["stroke-action-danger-02"],
      },
    },
  }) as const;

export interface IconButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  // Top level button variants
  main?: boolean;
  action?: boolean;
  danger?: boolean;

  // Button sub-variants
  primary?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  internal?: boolean;

  // Button size
  large?: boolean;

  // Button states
  transient?: boolean;
  disabled?: boolean;

  // Button properties
  onHover?: (isHovering: boolean) => void;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  icon: React.FunctionComponent<IconProps>;
  tooltip?: string;
}

export default function IconButton({
  main,
  action,
  danger,

  primary,
  secondary,
  tertiary,
  internal,

  transient,
  disabled,

  onHover,
  onClick,
  icon: Icon,
  className,
  tooltip,

  ...props
}: IconButtonProps) {
  const variant = main
    ? "main"
    : action
      ? "action"
      : danger
        ? "danger"
        : "main";
  const subvariant = primary
    ? "primary"
    : secondary
      ? "secondary"
      : tertiary
        ? "tertiary"
        : internal
          ? "internal"
          : "primary";
  const abled = disabled ? "disabled" : "enabled";

  const buttonClass = useMemo(
    () => buttonClasses(transient)[variant][subvariant][abled],
    [transient, variant, subvariant, abled]
  );
  const iconClass = useMemo(
    () => iconClasses(transient)[variant][subvariant][abled],
    [transient, variant, subvariant, abled]
  );

  const buttonElement = (
    <button
      type="button"
      className={cn(
        "flex items-center justify-center h-fit w-fit group/IconButton",
        internal ? "p-1" : "p-2",
        disabled && "cursor-not-allowed",
        internal ? "rounded-08" : "rounded-12",
        buttonClass,
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
      <Icon className={cn("h-[1rem] w-[1rem]", iconClass)} />
    </button>
  );

  if (!tooltip) return buttonElement;

  return (
    <SimpleTooltip side="top" tooltip={tooltip}>
      {buttonElement}
    </SimpleTooltip>
  );
}
