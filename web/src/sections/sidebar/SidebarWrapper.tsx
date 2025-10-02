import React from "react";
import { cn } from "@/lib/utils";

interface SidebarWrapperProps {
  children: React.ReactNode;
  folded?: boolean;
  className?: string;
}

export default function SidebarWrapper({
  children,
  folded,
  className,
}: SidebarWrapperProps) {
  return (
    <div>
      <div
        className={cn(
          "h-full flex flex-col bg-background-tint-02 p-padding-button justify-between gap-padding-content",
          folded ? "w-[4rem]" : "w-[15rem]",
          className
        )}
      >
        {children}
      </div>
    </div>
  );
}
