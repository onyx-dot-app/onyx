/**
 * Collapsible Components
 *
 * A set of components for creating expandable/collapsible sections.
 * Built on Radix UI Collapsible primitives with custom animations.
 *
 * Components:
 * - Collapsible: Root container that manages open/closed state
 * - CollapsibleTrigger: Interactive element that toggles the collapsible
 * - CollapsibleContent: Content area that expands/collapses with animation
 *
 * @example
 * ```tsx
 * import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/refresh-components/Collapsible";
 *
 * // Basic usage
 * <Collapsible>
 *   <CollapsibleTrigger>
 *     <button>Toggle Content</button>
 *   </CollapsibleTrigger>
 *   <CollapsibleContent>
 *     <div className="p-4">
 *       Your collapsible content here
 *     </div>
 *   </CollapsibleContent>
 * </Collapsible>
 *
 * // Controlled state
 * const [isOpen, setIsOpen] = useState(false);
 * <Collapsible open={isOpen} onOpenChange={setIsOpen}>
 *   <CollapsibleTrigger asChild>
 *     <button>{isOpen ? "Close" : "Open"}</button>
 *   </CollapsibleTrigger>
 *   <CollapsibleContent>
 *     <div>Content</div>
 *   </CollapsibleContent>
 * </Collapsible>
 * ```
 */

"use client";

import { cn } from "@/lib/utils";
import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";
import * as React from "react";

/**
 * Collapsible Root Component
 *
 * The root container for a collapsible section. Manages the open/closed state
 * and provides context to trigger and content components.
 *
 * This is a re-export of Radix UI's Collapsible.Root component.
 *
 * @see https://www.radix-ui.com/primitives/docs/components/collapsible
 */
const Collapsible = CollapsiblePrimitive.Root;

/**
 * Collapsible Trigger Component
 *
 * The interactive element that controls the open/closed state of the collapsible.
 * Typically wraps a button or other clickable element.
 *
 * Supports the `asChild` prop to merge props with a child element instead of
 * rendering a default button.
 *
 * This is a re-export of Radix UI's CollapsibleTrigger component.
 *
 * @see https://www.radix-ui.com/primitives/docs/components/collapsible
 */
const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger;

/**
 * Collapsible Content Component
 *
 * The expandable/collapsible content area. Automatically animates when
 * opening and closing based on the collapsible state.
 *
 * Features:
 * - Smooth slide-down animation when opening (animate-collapsible-down)
 * - Smooth slide-up animation when closing (animate-collapsible-up)
 * - Overflow hidden to prevent content bleeding during animation
 * - Supports custom className for additional styling
 *
 * Built on Radix UI's CollapsibleContent with custom animations.
 *
 * @see https://www.radix-ui.com/primitives/docs/components/collapsible
 */
const CollapsibleContent = React.forwardRef<
  React.ElementRef<typeof CollapsiblePrimitive.CollapsibleContent>,
  React.ComponentPropsWithoutRef<typeof CollapsiblePrimitive.CollapsibleContent>
>(({ className, ...props }, ref) => (
  <CollapsiblePrimitive.CollapsibleContent
    ref={ref}
    className={cn(
      "overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up",
      className
    )}
    {...props}
  />
));
CollapsibleContent.displayName = "CollapsibleContent";

export { Collapsible, CollapsibleContent, CollapsibleTrigger };
