"use client";

import React from "react";
import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Link from "next/link";
import Truncated from "@/refresh-components/texts/Truncated";

const backgroundClasses = (active?: boolean) =>
  ({
    defaulted: [
      active ? "bg-background-tint-00" : "bg-transparent",
      "hover:bg-background-tint-03",
    ],
    lowlight: [
      active ? "bg-background-tint-00" : "bg-transparent",
      "hover:bg-background-tint-03",
    ],
    focused: [
      "border-background-tint-04 border-[2px]",
      "bg-background-neutral-00",
    ],
  }) as const;

const textClasses = (active: boolean | undefined) =>
  ({
    defaulted: [
      active ? "text-text-04" : "text-text-03",
      "group-hover/SidebarTab:text-text-04",
    ],
    lowlight: [
      active ? "text-text-03" : "text-text-02",
      "group-hover/SidebarTab:text-text-03",
    ],
    focused: ["text-text-03"],
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    defaulted: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/SidebarTab:stroke-text-04",
    ],
    lowlight: [
      active ? "stroke-text-03" : "stroke-text-02",
      "group-hover/SidebarTab:stroke-text-03",
    ],
    focused: ["stroke-text-02"],
  }) as const;

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  active?: boolean;
  focused?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  className?: string;
  leftIcon?: React.FunctionComponent<SvgProps>;
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  active,
  focused,
  lowlight,

  onClick,
  href,
  className,
  leftIcon: LeftIcon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const variant = lowlight ? "lowlight" : focused ? "focused" : "defaulted";

  const innerContent = (
    <div
      className={cn(
        "flex flex-row justify-center items-center p-spacing-interline-mini gap-spacing-inline rounded-08 cursor-pointer group/SidebarTab w-full select-none",
        backgroundClasses(active)[variant],
        // active ? "bg-background-tint-00" : "bg-transparent",
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
          <div className="w-[1rem] h-[1rem] flex flex-col items-center justify-center">
            <LeftIcon
              className={cn(
                "h-[1rem]",
                "w-[1rem]",
                iconClasses(active)[variant]
              )}
            />
          </div>
        )}
        {!folded &&
          (typeof children === "string" ? (
            <Truncated
              className={cn(textClasses(active)[variant])}
              side="right"
            >
              {children}
            </Truncated>
          ) : (
            children
          ))}
      </div>
      {!folded && rightChildren}
    </div>
  );

  const content = href ? <Link href={href}>{innerContent}</Link> : innerContent;

  if (typeof children !== "string") return content;
  if (folded)
    return <SimpleTooltip tooltip={children}>{content}</SimpleTooltip>;
  return content;
}
