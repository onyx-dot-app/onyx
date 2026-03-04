"use client";

import React from "react";
import type { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Link from "next/link";
import type { Route } from "next";
import Truncated from "@/refresh-components/texts/Truncated";
import { Interactive } from "@opal/core";

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  transient?: boolean;
  focused?: boolean;
  lowlight?: boolean;
  nested?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLElement>;
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
  nested,

  onClick,
  href,
  className,
  leftIcon: LeftIcon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const content = (
    <Interactive.Base
      variant="sidebar"
      selected={focused}
      transient={transient}
      onClick={onClick}
      group="group/SidebarTab"
    >
      <Interactive.Container
        roundingVariant="compact"
        heightVariant="fit"
        widthVariant="full"
      >
        <div
          className={cn(
            "relative flex flex-row justify-start items-start w-full p-1.5 gap-1",
            className
          )}
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
            className={cn(
              "relative flex-1 h-[1.5rem] flex flex-row items-center px-1 py-0.5 gap-2 justify-start",
              !focused && "pointer-events-none"
            )}
          >
            {nested && !LeftIcon && (
              <div className="w-4 shrink-0" aria-hidden="true" />
            )}
            {LeftIcon && (
              <div
                className={cn(
                  "w-[1rem] flex items-center justify-center",
                  !folded && "pointer-events-auto"
                )}
              >
                <LeftIcon className="h-[1rem] w-[1rem] interactive-foreground-icon" />
              </div>
            )}
            {!folded &&
              (typeof children === "string" ? (
                <Truncated
                  className="interactive-foreground"
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
      </Interactive.Container>
    </Interactive.Base>
  );

  if (typeof children !== "string") return content;
  if (folded)
    return <SimpleTooltip tooltip={children}>{content}</SimpleTooltip>;
  return content;
}
