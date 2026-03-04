"use client";

import React from "react";
import type { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Link from "next/link";
import type { Route } from "next";
import { Interactive } from "@opal/core";
import { ContentAction } from "@opal/layouts";

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  selected?: boolean;
  lowlight?: boolean;
  nested?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLElement>;
  href?: string;
  leftIcon?: React.FunctionComponent<IconProps>;
  rightChildren?: React.ReactNode;
  children?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  selected,
  lowlight,
  nested,

  onClick,
  href,
  leftIcon: LeftIcon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const isStringChildren = typeof children === "string";

  const innerContent = folded ? (
    LeftIcon && (
      <div className="flex items-center justify-center p-0.5">
        <LeftIcon className="h-[1rem] w-[1rem] text-text-03" />
      </div>
    )
  ) : isStringChildren ? (
    <ContentAction
      icon={LeftIcon}
      title={children}
      sizePreset="main-ui"
      variant="body"
      prominence={lowlight ? "muted" : "default"}
      paddingVariant="fit"
      rightChildren={
        rightChildren && (
          <div className="relative flex items-center pointer-events-auto">
            {rightChildren}
          </div>
        )
      }
    />
  ) : (
    <div className="flex flex-row items-center gap-2 flex-1">
      {LeftIcon && (
        <div className="flex items-center justify-center p-0.5">
          <LeftIcon className="h-[1rem] w-[1rem] text-text-03" />
        </div>
      )}
      {children}
      {rightChildren && (
        <div className="relative flex items-center shrink-0 pointer-events-auto">
          {rightChildren}
        </div>
      )}
    </div>
  );

  const content = (
    <Interactive.Base
      variant="sidebar"
      selected={selected}
      onClick={onClick}
      group="group/SidebarTab"
    >
      <Interactive.Container
        roundingVariant="compact"
        heightVariant="lg"
        widthVariant="full"
      >
        <div
          className={cn(
            "relative flex flex-row justify-start items-start w-full gap-1",
            !selected && "pointer-events-none"
          )}
        >
          {href && (
            <Link
              href={href as Route}
              scroll={false}
              className="absolute inset-0 rounded-08 pointer-events-auto"
              tabIndex={-1}
            />
          )}
          {nested && !LeftIcon && !folded && (
            <div className="w-4 shrink-0" aria-hidden="true" />
          )}
          {innerContent}
        </div>
      </Interactive.Container>
    </Interactive.Base>
  );

  if (!isStringChildren) return content;
  if (folded)
    return <SimpleTooltip tooltip={children}>{content}</SimpleTooltip>;
  return content;
}
