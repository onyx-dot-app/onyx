"use client";

import React from "react";
import Text from "@/components-2/Text";

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
}

export function SidebarSection({ title, children }: SidebarSectionProps) {
  return (
    <div className="flex flex-col gap-spacing-inline">
      <Text
        secondaryBody
        text02
        className="px-spacing-interline sticky top-[0rem] bg-background-tint-02 z-10"
      >
        {title}
      </Text>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}
