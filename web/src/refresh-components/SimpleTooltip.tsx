"use client";

import React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import Text from "@/refresh-components/texts/Text";

export interface SimpleTooltipProps
  extends React.ComponentPropsWithoutRef<typeof TooltipContent> {
  tooltip?: string;
  children?: React.ReactNode;
}

export default function SimpleTooltip({
  tooltip,
  children,
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

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div>{children}</div>
        </TooltipTrigger>
        <TooltipContent side="right" {...rest}>
          <Text inverted>{hoverContent}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
