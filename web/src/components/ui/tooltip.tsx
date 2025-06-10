"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

const TooltipProvider = TooltipPrimitive.Provider;

const Tooltip = TooltipPrimitive.Root;

const TooltipTrigger = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Trigger>
>(({ type = "button", ...props }, ref) => (
  <TooltipPrimitive.Trigger ref={ref} type={type} {...props} />
));
TooltipTrigger.displayName = TooltipPrimitive.Trigger.displayName;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content> & {
    width?: string;
    backgroundColor?: string;
    showTick?: boolean;
    tickSide?: "top" | "bottom" | "left" | "right";
    side?: "top" | "bottom" | "left" | "right";
  }
>(
  (
    {
      className,
      sideOffset = 4,
      width,
      backgroundColor,
      showTick = false,
      tickSide = "bottom",
      side = "top",
      ...props
    },
    ref
  ) => (
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      side={side}
      className={cn(
        `z-[100] overflow-hidden rounded-md text-neutral-50 ${
          backgroundColor ||
          "bg-neutral-900 dark:bg-neutral-200 dark:text-neutral-900"
        }
      ${width || "max-w-40"}
      text-wrap
       px-2 py-1.5 text-xs shadow-md animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2`,
        className
      )}
      {...props}
    >
      {showTick && (
        <div
          className={`absolute w-2 h-2 bg-inherit rotate-45 ${
            tickSide === "top"
              ? "-top-1 left-1/2 -translate-x-1/2"
              : tickSide === "bottom"
                ? "-bottom-1 left-1/2 -translate-x-1/2"
                : tickSide === "left"
                  ? "-left-1 top-1/2 -translate-y-1/2"
                  : "-right-1 top-1/2 -translate-y-1/2"
          }`}
        />
      )}
      {props.children}
    </TooltipPrimitive.Content>
  )
);
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
