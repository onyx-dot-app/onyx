"use client";

import React, { useState, useEffect, useCallback } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";

import { cn } from "@/lib/utils";
import Separator from "@/refresh-components/Separator";

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

function SeparatorHelper() {
  return <Separator className="py-0 px-2" />;
}

const sizeClasses = {
  small: ["w-[10rem]"],
  medium: ["w-[15.5rem]"],
};

export interface PopoverMenuProps {
  // size variants
  small?: boolean;
  medium?: boolean;

  className?: string;
  children?: React.ReactNode[];
  footer?: React.ReactNode;
  // Ref for the scrollable container (useful for programmatic scrolling)
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
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
  small,
  medium,

  className,
  children,
  footer,
  scrollContainerRef,
}: PopoverMenuProps) {
  const [showTopShadow, setShowTopShadow] = useState(false);
  const [showBottomShadow, setShowBottomShadow] = useState(false);
  const internalRef = React.useRef<HTMLDivElement>(null);
  const containerRef = scrollContainerRef || internalRef;

  const checkScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    // Show top shadow if scrolled down
    setShowTopShadow(container.scrollTop > 1);

    // Show bottom shadow if there's more content to scroll down
    const hasMoreBelow =
      container.scrollHeight - container.scrollTop - container.clientHeight > 1;
    setShowBottomShadow(hasMoreBelow);
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Check initial state
    checkScroll();

    container.addEventListener("scroll", checkScroll);
    // Also check on resize in case content changes
    const resizeObserver = new ResizeObserver(checkScroll);
    resizeObserver.observe(container);

    return () => {
      container.removeEventListener("scroll", checkScroll);
      resizeObserver.disconnect();
    };
  }, [containerRef, checkScroll]);

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
    <div className="flex flex-col gap-1 max-h-[20rem]">
      <div className="relative">
        <div
          ref={containerRef}
          className={cn(
            "flex flex-col gap-1 overflow-y-auto h-[20rem]",
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
                <SeparatorHelper />
              ) : (
                child
              )}
            </div>
          ))}
        </div>
        {/* Top scroll shadow indicator */}
        <div
          className={cn(
            "absolute top-0 left-0 right-0 h-6 pointer-events-none transition-opacity duration-200",
            showTopShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            background:
              "linear-gradient(to bottom, var(--background-neutral-00), transparent)",
          }}
        />
        {/* Bottom scroll shadow indicator */}
        <div
          className={cn(
            "absolute bottom-0 left-0 right-0 h-6 pointer-events-none transition-opacity duration-200",
            showBottomShadow ? "opacity-100" : "opacity-0"
          )}
          style={{
            background:
              "linear-gradient(to top, var(--background-neutral-00), transparent)",
          }}
        />
      </div>
      {footer && (
        <>
          <SeparatorHelper />
          {footer}
        </>
      )}
    </div>
  );
}

export { Popover, PopoverTrigger, PopoverContent, PopoverClose };
