"use client";

import React, { useMemo } from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { SvgProps } from "@/icons";

const variantClasses = (transient?: boolean) =>
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
          "bg-background-tint-01",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
          "border",
        ],
        disabled: ["bg-background-neutral-03", "border"],
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
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
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
          "bg-background-tint-01",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
          "border",
        ],
        disabled: ["bg-background-neutral-02", "border"],
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
        enabled: [],
        disabled: [],
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
          "bg-background-tint-01",
          "hover:bg-background-tint-02",
          transient && "bg-background-tint-02",
          "active:bg-background-tint-00",
          "border",
        ],
        disabled: ["bg-background-neutral-02", "border"],
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
        enabled: [],
        disabled: [],
      },
    },
  }) as const;

const textClasses = (transient?: boolean) =>
  ({
    main: {
      primary: {
        enabled: ["text-text-inverted-05"],
        disabled: ["text-text-inverted-04"],
      },
      secondary: {
        enabled: [
          "text-text-03",
          "group-hover/Button:text-text-04",
          transient && "text-text-04",
          "group-active/Button:text-text-05",
        ],
        disabled: ["text-text-01"],
      },
      tertiary: {
        enabled: [
          "text-text-03",
          "group-hover/Button:text-text-04",
          transient && "text-text-04",
          "group-active/Button:text-text-05",
        ],
        disabled: ["text-text-01"],
      },
      internal: {
        enabled: [
          "text-text-03",
          "group-hover/Button:text-text-04",
          transient && "text-text-04",
          "group-active/Button:text-text-05",
        ],
        disabled: ["text-text-01"],
      },
    },
    action: {
      primary: {
        enabled: ["text-text-light-05"],
        disabled: ["text-text-01"],
      },
      secondary: {
        enabled: ["text-action-text-link-05"],
        disabled: ["text-action-link-03"],
      },
      tertiary: {
        enabled: ["text-action-text-link-05"],
        disabled: ["text-action-link-03"],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    danger: {
      primary: {
        enabled: ["text-text-light-05"],
        disabled: ["text-text-01"],
      },
      secondary: {
        enabled: ["text-action-text-danger-05"],
        disabled: ["text-action-danger-03"],
      },
      tertiary: {
        enabled: ["text-action-text-danger-05"],
        disabled: ["text-action-danger-03"],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
  }) as const;

const iconClasses = (transient?: boolean) =>
  ({
    main: {
      primary: {
        enabled: ["stroke-text-inverted-05"],
        disabled: ["stroke-text-inverted-04"],
      },
      secondary: {
        enabled: [
          "stroke-text-03",
          "group-hover/Button:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/Button:stroke-text-05",
        ],
        disabled: ["stroke-text-01"],
      },
      tertiary: {
        enabled: [
          "stroke-text-03",
          "group-hover/Button:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/Button:stroke-text-05",
        ],
        disabled: ["stroke-text-01"],
      },
      internal: {
        enabled: [
          "stroke-text-03",
          "group-hover/Button:stroke-text-04",
          transient && "stroke-text-04",
          "group-active/Button:stroke-text-05",
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
        enabled: ["stroke-action-text-link-05"],
        disabled: ["stroke-action-link-03"],
      },
      tertiary: {
        enabled: ["stroke-action-text-link-05"],
        disabled: ["stroke-action-link-03"],
      },
      internal: {
        enabled: [],
        disabled: [],
      },
    },
    danger: {
      primary: {
        enabled: ["stroke-text-light-05"],
        disabled: ["stroke-text-01"],
      },
      secondary: {
        enabled: ["stroke-action-text-danger-05"],
        disabled: ["stroke-action-danger-03"],
      },
      tertiary: {
        enabled: ["stroke-action-text-danger-05"],
        disabled: ["stroke-action-danger-03"],
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
  main?: boolean;
  action?: boolean;
  danger?: boolean;

  // Button subvariants:
  primary?: boolean;
  secondary?: boolean;
  tertiary?: boolean;
  internal?: boolean;

  // Button states:
  disabled?: boolean;
  transient?: boolean;

  // Icons:
  leftIcon?: React.FunctionComponent<SvgProps>;
  rightIcon?: React.FunctionComponent<SvgProps>;

  href?: string;
}

export default function Button({
  main,
  action,
  danger,

  primary,
  secondary,
  tertiary,
  internal,

  disabled,
  transient,

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
    () => variantClasses(transient)[variant][subvariant][abled],
    [transient, variant, subvariant, abled]
  );
  const iconClass = useMemo(
    () => iconClasses(transient)[variant][subvariant][abled],
    [transient, variant, subvariant, abled]
  );

  const spacer = <div className="w-[0.1rem]" />;

  const content = (
    <button
      className={cn(
        "p-2 h-fit rounded-12 group/Button w-fit flex flex-row items-center justify-center gap-1",
        buttonClass,
        className
      )}
      disabled={disabled}
      {...props}
    >
      {LeftIcon ? (
        <div className="w-[1rem] h-[1rem] flex flex-col items-center justify-center">
          <LeftIcon className={cn("w-[1rem] h-[1rem]", iconClass)} />
        </div>
      ) : (
        spacer
      )}
      {typeof children === "string" ? (
        <Text
          className={cn(
            "whitespace-nowrap",
            textClasses(transient)[variant][subvariant][abled]
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
              iconClasses(transient)[variant][subvariant][abled]
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
