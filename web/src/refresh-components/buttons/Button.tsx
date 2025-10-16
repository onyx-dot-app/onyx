"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { SvgProps } from "@/icons";

const variantClasses = (active?: boolean) =>
  ({
    defaulted: {
      primary: {
        enabled: [
          active ? "bg-theme-primary-06" : "bg-theme-primary-05",
          "hover:bg-theme-primary-04",
        ],
        disabled: ["bg-background-neutral-04"],
      },
      secondary: {
        enabled: [
          active ? "bg-background-tint-00" : "bg-background-tint-01",
          "hover:bg-background-tint-02",
          "border",
        ],
        disabled: ["bg-background-tint-00", "border"],
      },
      tertiary: {
        enabled: [
          active && "bg-background-tint-00",
          "hover:bg-background-tint-02",
        ],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    action: {
      primary: {
        enabled: [
          active ? "bg-action-link-06" : "bg-action-link-05",
          "hover:bg-action-link-04",
        ],
        disabled: ["bg-action-link-02"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    danger: {
      primary: {
        enabled: [
          active ? "bg-action-danger-06" : "bg-action-danger-05",
          "hover:bg-action-danger-04",
        ],
        disabled: ["bg-action-danger-02"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
  }) as const;

const textClasses = (active?: boolean) =>
  ({
    defaulted: {
      primary: {
        enabled: ["text-text-inverted-05"],
        disabled: ["text-text-inverted-04"],
      },
      secondary: {
        enabled: [
          active ? "text-text-05" : "text-text-03",
          "group-hover/Button:text-text-04",
        ],
        disabled: ["text-text-01"],
      },
      tertiary: {
        enabled: [
          active ? "text-text-05" : "text-text-03",
          "group-hover/Button:text-text-04",
        ],
        disabled: ["text-text-01"],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    action: {
      primary: {
        enabled: ["text-text-light-05"],
        disabled: ["text-text-light-05"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    danger: {
      primary: {
        enabled: ["text-text-light-05"],
        disabled: ["text-text-light-05"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
  }) as const;

const iconClasses = (active?: boolean) =>
  ({
    defaulted: {
      primary: {
        enabled: ["stroke-text-inverted-05"],
        disabled: ["stroke-text-inverted-04"],
      },
      secondary: {
        enabled: [
          active ? "stroke-text-05" : "stroke-text-03",
          "group-hover/Button:stroke-text-04",
        ],
        disabled: ["stroke-text-01"],
      },
      tertiary: {
        enabled: [
          active ? "stroke-text-05" : "stroke-text-03",
          "group-hover/Button:stroke-text-04",
        ],
        disabled: ["stroke-text-01"],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    action: {
      primary: {
        enabled: ["stroke-text-light-05"],
        disabled: ["stroke-text-light-05"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    danger: {
      primary: {
        enabled: ["stroke-text-light-05"],
        disabled: ["stroke-text-light-05"],
      },
      secondary: {
        enabled: [],
        disabled: [],
      },
      tertiary: {
        enabled: [],
        disabled: [],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
  }) as const;

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  // Button variants:
  defaulted?: boolean;
  action?: boolean;
  danger?: boolean;

  // Button subvariants:
  primary?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  internal?: boolean;

  // Button states:
  disabled?: boolean;
  active?: boolean;

  // Icons:
  leftIcon?: React.FunctionComponent<SvgProps>;
  rightIcon?: React.FunctionComponent<SvgProps>;

  href?: string;
}

export default function Button({
  defaulted,
  action,
  danger,

  primary,
  secondary,
  tertiary,
  internal,

  disabled,
  active,

  leftIcon: LeftIcon,
  rightIcon: RightIcon,

  href,
  children,
  className,
  ...props
}: ButtonProps) {
  if (LeftIcon && RightIcon)
    throw new Error(
      "The left and right icons cannot be both specified at the same time"
    );

  const variant = defaulted
    ? "defaulted"
    : action
      ? "action"
      : danger
        ? "danger"
        : "defaulted";

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

  const spacer = <div className="w-[0.1rem]" />;

  const content = (
    <button
      className={cn(
        "p-spacing-interline h-fit rounded-12 group/Button w-fit flex flex-row items-center justify-center gap-spacing-inline",
        variantClasses(active)[variant][subvariant][abled],
        className
      )}
      disabled={disabled}
      {...props}
    >
      {LeftIcon ? (
        <div className="w-[1rem] h-[1rem] flex flex-col items-center justify-center">
          <LeftIcon
            className={cn(
              "w-[1rem] h-[1rem]",
              iconClasses(active)[variant][subvariant][abled]
            )}
          />
        </div>
      ) : (
        spacer
      )}
      {typeof children === "string" ? (
        <Text
          className={cn(
            "whitespace-nowrap",
            textClasses(active)[variant][subvariant][abled]
          )}
        >
          {children}
        </Text>
      ) : (
        children
      )}
      {RightIcon ? (
        <div className="w-[1rem] h-[1rem]">
          <RightIcon
            className={cn(
              "w-[1rem] h-[1rem]",
              iconClasses(active)[variant][subvariant][abled]
            )}
          />
        </div>
      ) : (
        spacer
      )}
    </button>
  );

  if (!href) return content;

  return <Link href={href}>{content}</Link>;
}
