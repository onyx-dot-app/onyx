"use client";

import React from "react";
import OverflowDiv from "@/refresh-components/OverflowDiv";

export interface SidebarBodyProps {
  actionButton?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  scrollKey: string;
}

export default function SidebarBody({
  actionButton,
  children,
  footer,
  scrollKey,
}: SidebarBodyProps) {
  return (
    <div className="flex flex-col min-h-0 h-full gap-3 px-2">
      {actionButton}
      <OverflowDiv className="gap-3" scrollKey={scrollKey}>
        {children}
      </OverflowDiv>
      {footer}
    </div>
  );
}
