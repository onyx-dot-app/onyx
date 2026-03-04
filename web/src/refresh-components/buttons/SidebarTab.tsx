"use client";

import React from "react";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import type { Route } from "next";
import { Interactive } from "@opal/core";
import { ContentAction } from "@opal/layouts";
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

  // NOTE (@raunakab)
  //
  // The `rightChildren` node NEEDS to be absolutely positioned since it needs to live on top of the absolutely positioned `Link`.
  // However, having the `rightChildren` be absolutely positioned means that it cannot appropriately truncate the title.
  // Therefore, we add a dummy node solely for the truncation effects that we obtain.
  const truncationSpacer = rightChildren && (
    <div className="w-0 group-hover/SidebarTab:w-6" />
  );

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
              className="absolute z-[99] inset-0 rounded-08"
              tabIndex={-1}
            />
          )}

          {!folded && rightChildren && (
            <div className="absolute z-[100] right-1.5 top-0 bottom-0 flex flex-col justify-center items-center pointer-events-auto">
              {rightChildren}
            </div>
          )}

          {typeof children === "string" ? (
            <ContentAction
              icon={Icon ?? undefined}
              title={folded ? "" : children}
              sizePreset="main-ui"
              variant="body"
              prominence={
                lowlight ? "muted-2x" : selected ? "default" : "muted"
              }
              widthVariant="full"
              paddingVariant="fit"
              rightChildren={truncationSpacer}
            />
          ) : (
            <div className="flex flex-row items-center gap-2 flex-1">
              {Icon && (
                <div className="flex items-center justify-center p-0.5">
                  <Icon className="h-[1rem] w-[1rem] text-text-03" />
                </div>
              )}
              {children}
              {
                // NOTE (@raunakab)
                //
                // Adding the `truncationSpacer` here for the same reason as above.
                truncationSpacer
              }
            </div>
          )}
        </Interactive.Container>
      </Interactive.Base>
    </div>
  );
}
