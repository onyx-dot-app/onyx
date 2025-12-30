/**
 * SimpleCollapsible - A collapsible container component
 *
 * Provides an expandable/collapsible section with a trigger and content area.
 * Supports both controlled and uncontrolled modes.
 *
 * @example
 * ```tsx
 * import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
 *
 * // Basic usage with header
 * <SimpleCollapsible
 *   trigger={
 *     <SimpleCollapsible.Header
 *       title="Section Title"
 *       description="Optional description"
 *     />
 *   }
 * >
 *   <div className="p-4">
 *     Content goes here
 *   </div>
 * </SimpleCollapsible>
 *
 * // With custom trigger
 * <SimpleCollapsible trigger={<CustomHeader />}>
 *   <div>Content</div>
 * </SimpleCollapsible>
 *
 * // Controlled state
 * const [open, setOpen] = useState(true);
 * <SimpleCollapsible
 *   trigger={<SimpleCollapsible.Header title="Controlled Section" />}
 *   open={open}
 *   onOpenChange={setOpen}
 * >
 *   <div>Content</div>
 * </SimpleCollapsible>
 * ```
 */

"use client";

import * as React from "react";
import { useBoundingBox } from "@/hooks/useBoundingBox";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { SvgFold, SvgExpand } from "@opal/icons";

/**
 * SimpleCollapsible Root Component
 *
 * A collapsible container with a trigger and expandable content area.
 * Built on Radix UI Collapsible primitives.
 *
 * @example
 * ```tsx
 * <SimpleCollapsible
 *   trigger={
 *     <SimpleCollapsible.Header
 *       title="Settings"
 *       description="Configure your preferences"
 *     />
 *   }
 * >
 *   <div className="p-4">
 *     {/* Content *\/}
 *   </div>
 * </SimpleCollapsible>
 *
 * // With custom trigger
 * <SimpleCollapsible trigger={<CustomHeader />}>
 *   <div>Content</div>
 * </SimpleCollapsible>
 *
 * // Controlled state
 * <SimpleCollapsible
 *   trigger={<SimpleCollapsible.Header title="Controlled" />}
 *   open={isOpen}
 *   onOpenChange={setIsOpen}
 * >
 *   <div>Content</div>
 * </SimpleCollapsible>
 *
 * // Default closed
 * <SimpleCollapsible
 *   trigger={<SimpleCollapsible.Header title="Initially Closed" />}
 *   defaultOpen={false}
 * >
 *   <div>Content</div>
 * </SimpleCollapsible>
 * ```
 */
interface SimpleCollapsibleRootProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "children"> {
  /** The trigger element that toggles the collapsible (required) */
  trigger: React.ReactNode;
  /** The content to display inside the collapsible area */
  children?: React.ReactNode;
  /** Controlled open state - when provided, component becomes controlled */
  open?: boolean;
  /** Default open state for uncontrolled mode (defaults to true) */
  defaultOpen?: boolean;
  /** Callback fired when the open state changes */
  onOpenChange?: (open: boolean) => void;
  /** Additional CSS classes to apply to the content container */
  contentClassName?: string;
}
const SimpleCollapsibleRoot = React.forwardRef<
  HTMLDivElement,
  SimpleCollapsibleRootProps
>(
  (
    {
      trigger,
      children,
      open: controlledOpen,
      defaultOpen = true,
      onOpenChange,
      contentClassName,
      className,
      ...props
    },
    ref
  ) => {
    const { ref: boundingRef, inside } = useBoundingBox();
    const [internalOpen, setInternalOpen] = React.useState(defaultOpen);

    // Determine if controlled or uncontrolled
    const isControlled = controlledOpen !== undefined;
    const open = isControlled ? controlledOpen : internalOpen;

    const handleOpenChange = React.useCallback(
      (newOpen: boolean) => {
        onOpenChange?.(newOpen);
        if (!isControlled) {
          setInternalOpen(newOpen);
        }
      },
      [isControlled, onOpenChange]
    );

    return (
      <Collapsible
        open={open}
        onOpenChange={handleOpenChange}
        className={className}
        {...props}
      >
        <CollapsibleTrigger asChild>
          <div>
            <div
              ref={boundingRef}
              className="flex flex-row items-center justify-between gap-4 cursor-pointer select-none"
            >
              {trigger}
              <IconButton
                icon={open ? SvgFold : SvgExpand}
                internal
                transient={inside}
                tooltip={open ? "Fold" : "Expand"}
              />
            </div>
          </div>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div ref={ref} className={cn("pt-4", contentClassName)}>
            {children}
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  }
);
SimpleCollapsibleRoot.displayName = "SimpleCollapsible";

/**
 * SimpleCollapsible Header Component
 *
 * A pre-styled header component for the collapsible trigger.
 * Displays a title and optional description.
 *
 * @example
 * ```tsx
 * <SimpleCollapsible
 *   trigger={
 *     <SimpleCollapsible.Header
 *       title="Advanced Settings"
 *       description="Configure advanced options"
 *     />
 *   }
 * >
 *   <div>Content</div>
 * </SimpleCollapsible>
 *
 * // Title only
 * <SimpleCollapsible
 *   trigger={<SimpleCollapsible.Header title="Quick Settings" />}
 * >
 *   <div>Content</div>
 * </SimpleCollapsible>
 * ```
 */
interface SimpleCollapsibleHeaderProps
  extends React.HTMLAttributes<HTMLDivElement> {
  /** The main heading text displayed in emphasized style */
  title: string;
  /** Optional secondary description text displayed below the title */
  description?: string;
}
const SimpleCollapsibleHeader = React.forwardRef<
  HTMLDivElement,
  SimpleCollapsibleHeaderProps
>(({ title, description, className, ...props }, ref) => {
  return (
    <div ref={ref} className={cn("flex flex-col w-full", className)} {...props}>
      <Text as="p" mainContentEmphasis>
        {title}
      </Text>
      {description && (
        <Text as="p" secondaryBody text03>
          {description}
        </Text>
      )}
    </div>
  );
});
SimpleCollapsibleHeader.displayName = "SimpleCollapsibleHeader";

export default Object.assign(SimpleCollapsibleRoot, {
  Header: SimpleCollapsibleHeader,
});

export { type SimpleCollapsibleRootProps, type SimpleCollapsibleHeaderProps };
