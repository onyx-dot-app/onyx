"use client";

import React from "react";
import OverflowDiv from "@/refresh-components/OverflowDiv";

export interface SidebarBodyProps {
  pinnedContent?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  /**
   * Unique key to enable scroll position persistence across navigation.
   * Pass this through from parent sidebar components (e.g., "admin-sidebar", "app-sidebar").
   */
  scrollKey: string;
}

export default function SidebarBody({
  pinnedContent,
  children,
  footer,
  scrollKey,
}: SidebarBodyProps) {
  return (
    <div className="flex flex-col min-h-0 h-full gap-3">
      {pinnedContent && <div className="px-2">{pinnedContent}</div>}
      <OverflowDiv className="gap-3 px-2" scrollKey={scrollKey}>
        {children}
      </OverflowDiv>
      {footer && <div className="px-2">{footer}</div>}
    </div>
  );
}
