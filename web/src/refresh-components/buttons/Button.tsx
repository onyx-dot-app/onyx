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

  // Icons:
  leftIcon?: React.FunctionComponent<IconProps>;
  rightIcon?: React.FunctionComponent<IconProps>;

  href?: string;
}

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

      leftIcon: LeftIcon,
      rightIcon: RightIcon,

      href,
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

    const content = (
      <button
        ref={ref}
        className={cn(
          "p-2 h-fit rounded-12 w-fit flex flex-row items-center justify-center gap-1.5",
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
        <div
          className={cn(
            "leading-none",
            LeftIcon && "pr-1",
            RightIcon && "pl-1"
          )}
        >
          {typeof children === "string" ? (
            <Text className={cn("whitespace-nowrap", textClass)} as="span">
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
    return <Link href={href as Route}>{content}</Link>;
  }
);
Button.displayName = "Button";

export default Button;
