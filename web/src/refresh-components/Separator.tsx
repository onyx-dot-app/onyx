"use client";

import React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cn } from "@/lib/utils";

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
function SeparatorInner(
  {
    className,
    orientation = "horizontal",
    decorative = true,
    ...props
  }: React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>,
  ref: React.ForwardedRef<React.ComponentRef<typeof SeparatorPrimitive.Root>>
) {
  const isHorizontal = orientation === "horizontal";

  return (
    <div
      className={cn(isHorizontal ? "py-4 w-full" : "px-4 h-full", className)}
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

const Separator = React.forwardRef(SeparatorInner);
Separator.displayName = SeparatorPrimitive.Root.displayName;
export default Separator;
