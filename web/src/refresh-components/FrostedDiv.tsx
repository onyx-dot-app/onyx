"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface FrostedDivProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * Background color for the frost effect.
   * Defaults to a semi-transparent white
   */
  backgroundColor?: string;

  /**
   * Blur amount for the frosted glass effect (filter blur).
   * Defaults to "20px"
   */
  blur?: string;

  /**
   * Backdrop blur for the glass effect.
   * Defaults to "6px"
   */
  backdropBlur?: string;

  /**
   * Border radius for the frost effect.
   * Defaults to "1rem" (16px)
   */
  borderRadius?: string;

  /**
   * Additional classes for the frost overlay element itself
   */
  overlayClassName?: string;
}

/**
 * FrostedDiv - A wrapper that adds a frosted glass bloom effect behind its children
 *
 * This component wraps content and adds a frosted glass effect behind it.
 * The wrapper adds `relative` positioning - pass layout classes via `className`.
 *
 * @example
 * ```tsx
 * <FrostedDiv>
 *   <Button>Click me</Button>
 * </FrostedDiv>
 * ```
 *
 * @example
 * // Custom blur intensity and layout
 * <FrostedDiv blur="30px" className="flex items-center gap-2 p-2">
 *   <Button>One</Button>
 *   <Button>Two</Button>
 * </FrostedDiv>
 */
export default function FrostedDiv({
  backgroundColor = "var(--background-alpha-02, rgba(255, 255, 255, 0.1))",
  blur = "20px",
  backdropBlur = "6px",
  borderRadius = "1rem",
  overlayClassName,
  className,
  style,
  children,
  ...props
}: FrostedDivProps) {
  return (
    <div className={cn("relative", className)} style={style} {...props}>
      {/* Frost effect overlay */}
      <div
        className={cn(
          "absolute inset-0 pointer-events-none -z-10",
          overlayClassName
        )}
        style={{
          borderRadius,
          background: backgroundColor,
          filter: `blur(${blur})`,
          backdropFilter: `blur(${backdropBlur})`,
        }}
      />
      {children}
    </div>
  );
}
