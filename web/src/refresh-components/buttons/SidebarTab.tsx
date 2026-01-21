"use client";

import React from "react";
import type { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Link from "next/link";
import type { Route } from "next";
import Truncated from "@/refresh-components/texts/Truncated";

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  transient?: boolean;
  focused?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  className?: string;
  leftIcon?: React.FunctionComponent<IconProps>;
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  transient,
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
  const state = transient ? "active" : "inactive";

  const content = (
    <div
      data-state={state}
      className={cn(
        "relative flex flex-row justify-start items-start p-1.5 gap-1 rounded-08 cursor-pointer group/SidebarTab w-full select-none",
        `sidebar-tab-background-${variant}`,
        className
      )}
      onClick={onClick}
    >
      {href && (
        <Link
          href={href as Route}
          scroll={false}
          className="absolute inset-0 rounded-08"
          tabIndex={-1}
        />
      )}
      <div
        data-state={state}
        className={cn(
          "relative flex-1 h-[1.5rem] flex flex-row items-center px-1 py-0.5 gap-2 justify-start",
          !focused && "pointer-events-none"
        )}
      >
        {LeftIcon && (
          <div className="w-[1rem] h-[1rem] flex items-center justify-center pointer-events-auto">
            <LeftIcon
              data-state={state}
              className={`h-[1rem] w-[1rem] sidebar-tab-icon-${variant}`}
            />
          </div>
        )}
        {!folded &&
          (typeof children === "string" ? (
            <Truncated
              data-state={state}
              className={`sidebar-tab-text-${variant}`}
              side="right"
              sideOffset={40}
            >
              {children}
            </Truncated>
          ) : (
            children
          ))}
      </div>
      {!folded && (
        <div className="relative h-[1.5rem] flex items-center">
          {rightChildren}
        </div>
      )}
    </div>
  );

  if (typeof children !== "string") return content;
  if (folded)
    return <SimpleTooltip tooltip={children}>{content}</SimpleTooltip>;
  return content;
}
