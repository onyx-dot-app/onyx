"use client";

import React from "react";
import OverflowDiv from "@/refresh-components/OverflowDiv";

export interface SidebarBodyProps {
  actionButton?: React.ReactNode;
  children: React.ReactNode;
  footer: React.ReactNode;
}

export default function SidebarBody({
  actionButton,
  children,
  footer,
}: SidebarBodyProps) {
  return (
    <div className="flex flex-col min-h-0 h-full gap-1 px-2">
      {actionButton}
      <OverflowDiv>{children}</OverflowDiv>
      {footer}
    </div>
  );
}
