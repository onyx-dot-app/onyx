"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

// Default the provider delay to a snappier, consistent value
const TooltipProvider: React.FC<
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Provider>
> = ({ delayDuration = 400, skipDelayDuration = 200, ...props }) => (
  <TooltipPrimitive.Provider
    delayDuration={delayDuration}
    skipDelayDuration={skipDelayDuration}
    {...props}
  />
);

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
        "z-[100] rounded-08 text-text-inverted-05 text-wrap p-padding-button shadow-lg animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
        backgroundColor || "bg-background-neutral-inverted-03",
        width,
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
