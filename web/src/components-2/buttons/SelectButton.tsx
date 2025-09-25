"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Truncated from "@/components-2/Truncated";
import SvgChevronDownSmall from "@/icons/chevron-down-small";

const textClasses = {
  primary: {
    main: ["text-text-04", "stroke-text-04"],
    disabled: ["text-text-02", "stroke-text-02"],
  },
} as const;

export interface SelectButtonProps {
  // Button states:
  folded?: boolean;
  active?: boolean;
  disabled?: boolean;

  // Button variants
  primary?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  className?: string;
  icon: React.FunctionComponent<SvgProps>;
  children?: React.ReactNode;
}

export function SelectButton({
  folded,
  active,
  disabled,

  primary,

  onClick,
  className,
  icon: Icon,
  children,
}: SelectButtonProps) {
  const variant = primary ? "primary" : "primary";
  const state = disabled ? "disabled" : "main";

  return (
    <button
      className={cn(
        "flex flex-row justify-center items-center p-spacing-interline gap-spacing-inline hover:bg-background-tint-02 rounded-08 h-[2rem] max-w-[10rem] w-full overflow-hidden",
        folded ? "w-min" : "w-full",
        active ? "bg-background-tint-00" : "bg-transparent",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
      onClick={disabled ? undefined : onClick}
    >
      <div className="w-[1rem] h-[1rem] flex flex-col justify-center items-center">
        <Icon className={cn("w-full h-full", textClasses[variant][state])} />
      </div>
      {!folded && (
        <div className="flex flex-row justify-center items-center">
          {typeof children === "string" ? (
            <Truncated
              side="right"
              offset={40}
              className={cn("text-left", textClasses[variant][state])}
              mainAction
            >
              {children}
            </Truncated>
          ) : (
            children
          )}
          <SvgChevronDownSmall
            className={cn(
              "h-[1.5rem] w-[1.5rem] transition-transform duration-200",
              textClasses[variant][state],
              active && "-rotate-180"
            )}
          />
        </div>
      )}
    </button>
  );
}
