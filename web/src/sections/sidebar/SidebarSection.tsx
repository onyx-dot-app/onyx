"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { Disabled, Hoverable } from "@opal/core";

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  disabled?: boolean;
}

export default function SidebarSection({
  title,
  children,
  action,
  disabled,
}: SidebarSectionProps) {
  return (
    <Hoverable.Root group="sidebar-section">
      {/* Title */}
      {/* NOTE: mr-1.5 is intentionally used instead of padding to avoid the background color
          from overlapping with scrollbars on Safari.
      */}
      <Disabled disabled={disabled}>
        <div className="pl-2 mr-1.5 py-1 sticky top-0 bg-background-tint-02 z-10 flex flex-row items-center justify-between min-h-[2rem]">
          <div className="p-0.5 w-full flex flex-col justify-center">
            <Text secondaryBody text02>
              {title}
            </Text>
          </div>
          {action && (
            <Hoverable.Item group="sidebar-section">{action}</Hoverable.Item>
          )}
        </div>
      </Disabled>

      {/* Contents */}
      {children}
    </Hoverable.Root>
  );
}
