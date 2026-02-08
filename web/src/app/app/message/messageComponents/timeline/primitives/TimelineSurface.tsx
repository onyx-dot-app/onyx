import React from "react";
import { cn } from "@/lib/utils";

export type TimelineSurfaceBackground = "tint" | "transparent";

export interface TimelineSurfaceProps {
  children: React.ReactNode;
  className?: string;
  isHover?: boolean;
  roundedTop?: boolean;
  roundedBottom?: boolean;
  background?: TimelineSurfaceBackground;
}

/**
 * TimelineSurface provides the shared background + rounded corners for a row.
 * Use it to keep hover and tint behavior consistent across timeline items.
 */
export function TimelineSurface({
  children,
  className,
  isHover = false,
  roundedTop = false,
  roundedBottom = false,
  background = "tint",
}: TimelineSurfaceProps) {
  if (React.Children.count(children) === 0) {
    return null;
  }

  const baseBackground = background === "tint" ? "bg-background-tint-00" : "";
  const hoverBackground =
    background === "tint" && isHover ? "bg-background-tint-02" : "";

  return (
    <div
      className={cn(
        "transition-colors duration-200",
        baseBackground,
        hoverBackground,
        roundedTop && "rounded-t-12",
        roundedBottom && "rounded-b-12",
        className
      )}
    >
      {children}
    </div>
  );
}

export default TimelineSurface;
