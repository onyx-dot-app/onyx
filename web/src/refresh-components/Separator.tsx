"use client";

import React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cn } from "@/lib/utils";

export interface SeparatorProps
  extends React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root> {
  noPadding?: boolean;
}

/**
 * Separator Component
 *
 * A visual divider that separates content either horizontally or vertically.
 * Built on Radix UI's Separator primitive.
 *
 * @example
 * ```tsx
 * // Horizontal separator (default)
 * <Separator />
 *
 * // Vertical separator
 * <Separator orientation="vertical" />
 *
 * // With custom className
 * <Separator className="my-8" />
 *
 * // Non-decorative (announced by screen readers)
 * <Separator decorative={false} />
 * ```
 */
const Separator = React.forwardRef(
  (
    {
      noPadding,

      className,
      orientation = "horizontal",
      decorative = true,
      ...props
    }: SeparatorProps,
    ref: React.ForwardedRef<React.ComponentRef<typeof SeparatorPrimitive.Root>>
  ) => {
    const isHorizontal = orientation === "horizontal";

    return (
      <div
        className={cn(
          isHorizontal ? "w-full" : "h-full",
          !noPadding && (isHorizontal ? "py-4" : "px-4"),
          className
        )}
      >
        <SeparatorPrimitive.Root
          ref={ref}
          decorative={decorative}
          orientation={orientation}
          className={cn(
            "bg-border-01",
            isHorizontal ? "h-[1px] w-full" : "h-full w-[1px]"
          )}
          {...props}
        />
      </div>
    );
  }
);
Separator.displayName = SeparatorPrimitive.Root.displayName;

export default Separator;
