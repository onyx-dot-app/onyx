"use client";

import React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

export interface SimpleTooltipProps
  extends React.ComponentPropsWithoutRef<typeof TooltipContent> {
  disabled?: boolean;
  tooltip?: string;
  children?: React.ReactNode;
}

export default function SimpleTooltip({
  disabled = false,
  tooltip,
  className,
  children,
  side = "right",
  ...rest
}: SimpleTooltipProps) {
  // Determine hover content based on the logic:
  // 1. If tooltip is defined, use tooltip
  // 2. If tooltip is undefined and children is a string, use children
  // 3. Otherwise, no tooltip
  const hoverContent =
    tooltip ?? (typeof children === "string" ? children : undefined);

  // If no hover content, just render children without tooltip
  if (!hoverContent) return <>{children}</>;

  // TooltipTrigger `asChild` expects a ref-aware DOM element; wrap anything
  // else in a span so non-forwardRef components and fragments don't crash.
  const isDomElement =
    React.isValidElement(children) && typeof children.type === "string";

  const triggerChild = isDomElement ? children : <span>{children}</span>;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          asChild
          // Doesn't work for some reason.
          // disabled={disabled}
        >
          {triggerChild}
        </TooltipTrigger>
        {!disabled && (
          <TooltipContent
            side={side}
            className={cn("max-w-[30rem]", className)}
            {...rest}
          >
            <Text as="p" textLight05>
              {hoverContent}
            </Text>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
