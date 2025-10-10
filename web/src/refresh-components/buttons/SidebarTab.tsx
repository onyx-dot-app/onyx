"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Truncated, { TruncatedProvider } from "@/refresh-components/Truncated";

const textClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "text-text-04" : "text-text-03",
      "group-hover/SidebarTab:text-text-04",
    ],
    danger: ["text-action-danger-05"],
    lowlight: [
      active ? "text-text-03" : "text-text-02",
      "group-hover/SidebarTab:text-text-03",
    ],
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/SidebarTab:stroke-text-04",
    ],
    danger: ["stroke-action-danger-05"],
    lowlight: [
      active ? "stroke-text-03" : "stroke-text-02",
      "group-hover/SidebarTab:stroke-text-03",
    ],
  }) as const;

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  active?: boolean;

  // Button variants:
  danger?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  className?: string;
  iconClassName?: string;
  leftIcon?: React.FunctionComponent<SvgProps>;
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  active,

  danger,
  lowlight,

  onClick,
  className,
  iconClassName,
  leftIcon: LeftIcon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const variant = danger ? "danger" : lowlight ? "lowlight" : "main";

  return (
    <TruncatedProvider>
      <div
        className={cn(
          "flex flex-row justify-center items-center p-spacing-interline-mini gap-spacing-inline rounded-08 cursor-pointer hover:bg-background-tint-03 group/SidebarTab w-full select-none",
          active ? "bg-background-tint-00" : "bg-transparent",
          className
        )}
        onClick={onClick}
      >
        <div
          className={cn(
            "flex-1 h-[1.5rem] flex flex-row items-center px-spacing-inline py-spacing-inline-mini gap-spacing-interline",
            folded ? "justify-center" : "justify-start"
          )}
        >
          {LeftIcon && (
            <div className={cn("w-[1rem]", "h-[1rem]", iconClassName)}>
              <LeftIcon
                className={cn(
                  "h-[1rem]",
                  "w-[1rem]",
                  iconClasses(active)[variant],
                  iconClassName
                )}
              />
            </div>
          )}
          {!folded && (
            <div className={cn("flex-1 text-left")}>
              {typeof children === "string" ? (
                <Truncated className={cn(textClasses(active)[variant])}>
                  {children}
                </Truncated>
              ) : (
                children
              )}
            </div>
          )}
        </div>
        {!folded && rightChildren}
      </div>
    </TruncatedProvider>
  );
}
