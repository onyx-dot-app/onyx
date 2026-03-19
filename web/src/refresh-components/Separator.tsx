"use client";

import React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import { cn } from "@/lib/utils";

export interface SeparatorProps
  extends React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root> {
  noPadding?: boolean;
  /** Custom horizontal padding in rem. Overrides the default padding. */
  paddingXRem?: number;
  /** Custom vertical padding in rem. Overrides the default padding. */
  paddingYRem?: number;
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
      paddingXRem,
      paddingYRem,
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
        style={{
          ...(paddingXRem != null
            ? {
                paddingLeft: `${paddingXRem}rem`,
                paddingRight: `${paddingXRem}rem`,
              }
            : {}),
          ...(paddingYRem != null
            ? {
                paddingTop: `${paddingYRem}rem`,
                paddingBottom: `${paddingYRem}rem`,
              }
            : {}),
        }}
        className={cn(
          isHorizontal ? "w-full" : "h-full",
          paddingXRem == null && !noPadding && (isHorizontal ? "py-4" : "px-4"),
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
