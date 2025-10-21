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

export function SidebarSection({
  title,
  children,
  action,
  className,
}: SidebarSectionProps) {
  return (
    <div className={cn("flex flex-col gap-spacing-inline group", className)}>
      <div className="px-spacing-interline sticky top-[0rem] bg-background-tint-02 z-10 flex flex-row items-center justify-between">
        <Text secondaryBody text02>
          {title}
        </Text>
        {action && (
          <div className="flex-shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
            {action}
          </div>
        )}
      </div>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}
