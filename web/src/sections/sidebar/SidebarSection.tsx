"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}

export default function SidebarSection({
  title,
  children,
  action,
  className,
}: SidebarSectionProps) {
  return (
    <div className={cn("flex flex-col group/SidebarSection", className)}>
      <div className="pl-2 pr-1.5 py-1 sticky top-[0rem] bg-background-tint-02 z-10 flex flex-row items-center justify-between min-h-[2rem]">
        <Text as="p" secondaryBody text02>
          {title}
        </Text>
        {action && (
          <div className="flex-shrink-0 opacity-0 group-hover/SidebarSection:opacity-100 transition-opacity">
            {action}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}
