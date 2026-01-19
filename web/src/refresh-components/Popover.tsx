"use client";

import React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";
import Separator from "@/refresh-components/Separator";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { WithoutStyles } from "@/types";
import { Section } from "@/layouts/general-layouts";

/**
 * Popover Root Component
 *
 * Wrapper around Radix Popover.Root for managing popover state.
 *
 * @example
 * ```tsx
 * <Popover open={isOpen} onOpenChange={setIsOpen}>
 *   <Popover.Trigger>
 *     <button>Open</button>
 *   </Popover.Trigger>
 *   <Popover.Content>
 *     {/* Popover content *\/}
 *   </Popover.Content>
 * </Popover>
 * ```
 */
const PopoverRoot = PopoverPrimitive.Root;

/**
 * Popover Trigger Component
 *
 * Button or element that triggers the popover to open.
 *
 * @example
 * ```tsx
 * <Popover.Trigger asChild>
 *   <button>Click me</button>
 * </Popover.Trigger>
 * ```
 */
const PopoverTrigger = PopoverPrimitive.Trigger;

/**
 * Popover Anchor Component
 *
 * An optional element to position the popover relative to.
 *
 * @example
 * ```tsx
 * <Popover>
 *   <Popover.Anchor asChild>
 *     <div>Anchor element</div>
 *   </Popover.Anchor>
 *   <Popover.Trigger>
 *     <button>Click me</button>
 *   </Popover.Trigger>
 *   <Popover.Content>
 *     {/* This will be positioned relative to the anchor *\/}
 *   </Popover.Content>
 * </Popover>
 * ```
 */
const PopoverAnchor = PopoverPrimitive.Anchor;

/**
 * Popover Close Component
 *
 * Element that closes the popover when clicked.
 *
 * @example
 * ```tsx
 * <Popover.Close asChild>
 *   <button>Close</button>
 * </Popover.Close>
 * ```
 */
const PopoverClose = PopoverPrimitive.Close;

/**
 * Popover Content Component
 *
 * The main popover container with default styling.
 *
 * @param width - Width of the popover: "fit", "md", or "lg". Default: "fit"
 *
 * @example
 * ```tsx
 * <Popover.Content align="start" sideOffset={8}>
 *   <div>Popover content here</div>
 * </Popover.Content>
 *
 * // Medium width
 * <Popover.Content width="md">
 *   <div>Medium width content</div>
 * </Popover.Content>
 *
 * // Large width
 * <Popover.Content width="lg">
 *   <div>Large width content</div>
 * </Popover.Content>
 * ```
 */
type PopoverContentWidth = "fit" | "md" | "lg";
const widthClasses: Record<PopoverContentWidth, string> = {
  fit: "w-fit",
  md: "w-[12rem]",
  lg: "w-[18rem]",
};
interface PopoverContentProps
  extends WithoutStyles<
    React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
  > {
  width?: PopoverContentWidth;
  ref?: React.Ref<React.ComponentRef<typeof PopoverPrimitive.Content>>;
}
function PopoverContent({
  width = "fit",
  align = "center",
  sideOffset = 4,
  ref,
  ...props
}: PopoverContentProps) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "bg-background-neutral-00 p-1 z-popover rounded-12 overflow-hidden border shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
          widthClasses[width]
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  );
}

export default Object.assign(PopoverRoot, {
  Trigger: PopoverTrigger,
  Anchor: PopoverAnchor,
  Content: PopoverContent,
  Close: PopoverClose,
  Menu: PopoverMenu,
});

// ============================================================================
// Common Layouts
// ============================================================================

function SeparatorHelper() {
  return <Separator className="py-0 px-2" />;
}

/**
 * Popover Menu Component
 *
 * Converts a list of React nodes into a vertical menu with automatic separator handling.
 *
 * @remarks
 * - Treats `null` values as separator lines
 * - Filters out `undefined` and `false` values
 * - Removes separators at the beginning and end of the list
 *
 * @example
 * ```tsx
 * <Popover>
 *   <Popover.Trigger asChild>
 *     <button>Options</button>
 *   </Popover.Trigger>
 *   <Popover.Content>
 *     <Popover.Menu small>
 *       <MenuItem>Option 1</MenuItem>
 *       <MenuItem>Option 2</MenuItem>
 *       {null}  {/* Separator line *\/}
 *       <MenuItem>Option 3</MenuItem>
 *     </Popover.Menu>
 *   </Popover.Content>
 * </Popover>
 *
 * // With footer
 * <Popover.Menu
 *   medium
 *   footer={<Button>Apply</Button>}
 * >
 *   <MenuItem>Item 1</MenuItem>
 *   <MenuItem>Item 2</MenuItem>
 * </Popover.Menu>
 * ```
 */
const sizeClasses = {
  sm: "w-[10rem]",
  md: "w-[16rem]",
  full: "!w-full",
};
export interface PopoverMenuProps {
  // size variants
  sm?: boolean;
  md?: boolean;
  full?: boolean;

  children?: React.ReactNode[];
  footer?: React.ReactNode;

  // Ref for the scrollable container (useful for programmatic scrolling)
  scrollContainerRef?: React.RefObject<HTMLDivElement | null>;
}
export function PopoverMenu({
  sm,
  md,
  full,

  children,
  footer,
  scrollContainerRef,
}: PopoverMenuProps) {
  if (!children) return null;

  const definedChildren = children.filter(
    (child) => child !== undefined && child !== false
  );
  const filteredChildren = definedChildren.filter((child, index) => {
    if (child !== null) return true;
    return index !== 0 && index !== definedChildren.length - 1;
  });
  const size = full ? "full" : sm ? "sm" : md ? "md" : "full";

  return (
    <Section alignItems="stretch">
      <ShadowDiv
        scrollContainerRef={scrollContainerRef}
        className={cn("flex flex-col gap-1 max-h-[20rem]", sizeClasses[size])}
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
      </ShadowDiv>
      {footer && (
        <>
          <SeparatorHelper />
          {footer}
        </>
      )}
    </Section>
  );
}
