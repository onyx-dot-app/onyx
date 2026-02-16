"use client";

import React from "react";
import OverflowDiv from "@/refresh-components/OverflowDiv";

export interface SidebarBodyProps {
  actionButtons?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  /**
   * Unique key to enable scroll position persistence across navigation.
   * Pass this through from parent sidebar components (e.g., "admin-sidebar", "app-sidebar").
   */
  scrollKey: string;
}

export default function SidebarBody({
  actionButtons,
  children,
  footer,
  scrollKey,
}: SidebarBodyProps) {
  return (
    <div className="flex flex-col min-h-0 h-full gap-3 px-2">
      <div className="flex flex-col gap-1.5">
        {actionButtons &&
          (Array.isArray(actionButtons)
            ? actionButtons.map((button, index) => (
                <div key={index}>{button}</div>
              ))
            : actionButtons)}
      </div>
      <OverflowDiv className="gap-3" scrollKey={scrollKey}>
        {children}
      </OverflowDiv>
      {footer}
    </div>
  );
}
