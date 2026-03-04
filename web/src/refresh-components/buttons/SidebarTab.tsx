"use client";

import React from "react";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import type { Route } from "next";
import { Interactive } from "@opal/core";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import Link from "next/link";

export interface SidebarTabProps {
  // Button states:
  folded?: boolean;
  selected?: boolean;
  lowlight?: boolean;
  nested?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLElement>;
  href?: string;
  icon?: React.FunctionComponent<IconProps>;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
}

export default function SidebarTab({
  folded,
  selected,
  lowlight,
  nested,

  onClick,
  href,
  icon,
  rightChildren,
  children,
}: SidebarTabProps) {
  const Icon =
    icon ??
    (nested
      ? ((() => (
          <div className="w-6" aria-hidden="true" />
        )) as IconFunctionComponent)
      : null);

  if (folded) {
    if (!Icon) throw "Folded and nested sidebar-tab buttons are not allowed";
    return (
      <Button
        icon={Icon}
        variant="sidebar"
        selected={selected}
        onClick={onClick}
        href={href}
        tooltip={typeof children === "string" ? children : undefined}
        tooltipSide="right"
      />
    );
  }

  return (
    <div className="relative">
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
          {href && (
            <Link
              href={href as Route}
              scroll={false}
              className="absolute inset-0 rounded-08"
              tabIndex={-1}
            />
          )}

          {rightChildren && (
            <div className="absolute right-1.5 top-0 bottom-0 flex flex-col justify-center items-center">
              {rightChildren}
            </div>
          )}

          {typeof children === "string" ? (
            <Content
              icon={Icon ?? undefined}
              title={children}
              sizePreset="main-ui"
              variant="body"
              prominence={
                lowlight ? "muted-2x" : selected ? "default" : "muted"
              }
              widthVariant="full"
            />
          ) : (
            <div className="flex flex-row items-center gap-2 flex-1">
              {Icon && (
                <div className="flex items-center justify-center p-0.5">
                  <Icon className="h-[1rem] w-[1rem] text-text-03" />
                </div>
              )}
              {children}
            </div>
          )}
        </Interactive.Container>
      </Interactive.Base>
    </div>
  );
}
