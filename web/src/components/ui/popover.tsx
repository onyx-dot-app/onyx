"use client";

import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import { cn } from "@/lib/utils";

const Popover = PopoverPrimitive.Root;

const PopoverTrigger = PopoverPrimitive.Trigger;

const PopoverClose = PopoverPrimitive.Close;

const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn(
        "bg-background-neutral-00 p-1 z-[30000] rounded-12 overflow-hidden border shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
        className
      )}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = PopoverPrimitive.Content.displayName;

const sizeClasses = {
  small: ["w-[10rem]"],
  medium: ["w-[15.5rem]"],
};

export interface PopoverMenuProps {
  // size values
  small?: boolean;
  medium?: boolean;

  className?: string;
  children?: React.ReactNode[];
}

// This component converts a list of `React.ReactNode`s into a vertical menu.
//
// # Notes:
// It treats `null`s as separator lines.
//
// # Filtering:
// `undefined`s will be filtered out.
// `null`s that are at the beginning / end will also be filtered out (separator lines don't make sense as the first / last element; they're supposed to *separate* options).
export function PopoverMenu({
  className,
  children,
  small,
  medium,
}: PopoverMenuProps) {
  if (!children) return null;

  const definedChildren = children.filter(
    (child) => child !== undefined && child !== false
  );
  const filteredChildren = definedChildren.filter((child, index) => {
    if (child !== null) return true;
    return index !== 0 && index !== definedChildren.length - 1;
  });
  const size = small ? "small" : medium ? "medium" : "small";

  return (
    <div
      className={cn(
        "flex flex-col gap-1 max-h-[20rem] overflow-y-scroll",
        sizeClasses[size],
        className
      )}
    >
      {filteredChildren.map((child, index) => (
        <div key={index}>
          {child === undefined ? (
            <></>
          ) : child === null ? (
            // Render `null`s as separator lines
            <div className="border-b mx-3" />
          ) : (
            child
          )}
        </div>
      ))}
    </div>
  );
}

export { Popover, PopoverTrigger, PopoverContent, PopoverClose };
