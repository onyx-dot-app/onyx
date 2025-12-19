"use client";

import * as React from "react";
import { DropdownMenuItem } from "./dropdown-menu";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { cn } from "@/lib/utils";

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
    <SimpleTooltip tooltip={tooltip}>
      <div className="cursor-not-allowed">
        <DropdownMenuItem
          ref={ref}
          className={cn(className)}
          disabled={disabled}
          {...props}
        />
      </div>
    </SimpleTooltip>
  );
});

DropdownMenuItemWithTooltip.displayName = "DropdownMenuItemWithTooltip";

export { DropdownMenuItemWithTooltip };
