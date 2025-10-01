"use client";

import React from "react";
import Text from "@/refresh-components/Text";

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}

export function SidebarSection({
  title,
  children,
  action,
}: SidebarSectionProps) {
  return (
    <div className="flex flex-col gap-spacing-inline">
      <div className="px-spacing-interline sticky top-[0rem] bg-background-tint-02 z-10 flex flex-row items-center justify-between">
        <Text secondaryBody text02>
          {title}
        </Text>
        {action && <div className="flex-shrink-0">{action}</div>}
      </div>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}
