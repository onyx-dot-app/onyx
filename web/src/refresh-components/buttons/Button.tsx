"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Link from "next/link";
import type { Route } from "next";
import type { IconProps } from "@opal/types";
import Text from "@/refresh-components/texts/Text";

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
  transient?: boolean;

  // Button sizes:
  size?: "lg" | "md";

  // Icons:
  leftIcon?: React.FunctionComponent<IconProps>;
  rightIcon?: React.FunctionComponent<IconProps>;

  href?: string;
  target?: string;
}

const BUTTON_SIZE_CLASS_MAP = {
  lg: {
    button: "p-2 rounded-12 gap-1.5",
    content: {
      left: "pr-1",
      right: "pl-1",
      none: "",
    },
  },
  md: {
    button: "p-1 rounded-08 gap-0",
    content: {
      left: "pr-1 py-0.5",
      right: "pl-1 py-0.5",
      none: "py-0.5",
    },
  },
} as const;

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      main,
      action,
      danger,

      primary,
      secondary,
      tertiary,
      internal,

      disabled,
      transient,
      size = "lg",

      leftIcon: LeftIcon,
      rightIcon: RightIcon,

      href,
      target,
      children,
      className,
      ...props
    },
    ref
  ) => {
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

    const buttonClass = `button-${variant}-${subvariant}`;
    const textClass = `button-${variant}-${subvariant}-text`;
    const iconClass = `button-${variant}-${subvariant}-icon`;
    const iconPlacement = LeftIcon ? "left" : RightIcon ? "right" : "none";
    const sizeClasses = BUTTON_SIZE_CLASS_MAP[size];
    const textSizeProps =
      size === "md"
        ? { secondaryAction: true as const }
        : { mainUiBody: true as const };

    const content = (
      <button
        ref={ref}
        className={cn(
          "h-fit w-fit flex flex-row items-center justify-center",
          sizeClasses.button,
          buttonClass,
          className
        )}
        disabled={disabled}
        data-state={transient ? "transient" : undefined}
        type="button"
        {...props}
      >
        {LeftIcon && (
          <div className="w-[1rem] h-[1rem] flex flex-col items-center justify-center">
            <LeftIcon className={cn("w-[1rem] h-[1rem]", iconClass)} />
          </div>
        )}
        <div className={cn("leading-none", sizeClasses.content[iconPlacement])}>
          {typeof children === "string" ? (
            <Text
              {...textSizeProps}
              className={cn("whitespace-nowrap", textClass)}
            >
              {children}
            </Text>
          ) : (
            children
          )}
        </div>
        {RightIcon && (
          <div className="w-[1rem] h-[1rem]">
            <RightIcon className={cn("w-[1rem] h-[1rem]", iconClass)} />
          </div>
        )}
      </button>
    );

    if (!href) return content;
    return (
      <Link
        href={href as Route}
        target={target}
        rel={target === "_blank" ? "noopener noreferrer" : undefined}
      >
        {content}
      </Link>
    );
  }
);
Button.displayName = "Button";

export default Button;
