"use client";

import * as React from "react";
import { DropdownMenuItem } from "./dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

interface DropdownMenuItemWithTooltipProps
  extends React.ComponentPropsWithoutRef<typeof DropdownMenuItem> {
  tooltip?: string;
}

const DropdownMenuItemWithTooltip = React.forwardRef<
  React.ElementRef<typeof DropdownMenuItem>,
  DropdownMenuItemWithTooltipProps
>(({ className, tooltip, disabled, ...props }, ref) => {
  // Only show tooltip if the item is disabled and a tooltip is provided
  if (!tooltip || !disabled) {
    return (
      <DropdownMenuItem
        ref={ref}
        className={className}
        disabled={disabled}
        {...props}
      />
    );
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="cursor-not-allowed">
            <DropdownMenuItem
              ref={ref}
              className={cn(className)}
              disabled={disabled}
              {...props}
            />
          </div>
        </TooltipTrigger>
        <TooltipContent showTick={true}>
          <Text inverted>{tooltip}</Text>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
});

DropdownMenuItemWithTooltip.displayName = "DropdownMenuItemWithTooltip";

export { DropdownMenuItemWithTooltip };
