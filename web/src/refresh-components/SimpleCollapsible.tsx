/**
 * SimpleCollapsible - A collapsible container component
 *
 * Provides an expandable/collapsible section with a header and content area.
 * Supports both controlled and uncontrolled modes.
 *
 * @example
 * ```tsx
 * import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
 *
 * // Basic usage
 * <SimpleCollapsible>
 *   <SimpleCollapsible.Header
 *     title="Section Title"
 *     description="Optional description"
 *   />
 *   <SimpleCollapsible.Content>
 *     <div>Content goes here</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 *
 * // Controlled state
 * const [open, setOpen] = useState(true);
 * <SimpleCollapsible open={open} onOpenChange={setOpen}>
 *   <SimpleCollapsible.Header title="Controlled Section" />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 *
 * // Default closed
 * <SimpleCollapsible defaultOpen={false}>
 *   <SimpleCollapsible.Header title="Initially Closed" />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
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
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgFold, SvgExpand } from "@opal/icons";
import { WithoutStyles } from "@/types";

// Context for sharing state between compound components
interface SimpleCollapsibleContextValue {
  open: boolean;
}
const SimpleCollapsibleContext =
  React.createContext<SimpleCollapsibleContextValue | null>(null);
function useSimpleCollapsible() {
  const context = React.useContext(SimpleCollapsibleContext);
  if (!context) {
    throw new Error(
      "SimpleCollapsible compound components must be used within SimpleCollapsible"
    );
  }
  return context;
}

/**
 * SimpleCollapsible Root Component
 *
 * A collapsible container with a header and expandable content area.
 * Built on Radix UI Collapsible primitives.
 *
 * @example
 * ```tsx
 * <SimpleCollapsible>
 *   <SimpleCollapsible.Header title="Settings" description="Configure your preferences" />
 *   <SimpleCollapsible.Content>
 *     <div>Content here</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 *
 * // Controlled state
 * <SimpleCollapsible open={isOpen} onOpenChange={setIsOpen}>
 *   <SimpleCollapsible.Header title="Controlled" />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 *
 * // Default closed
 * <SimpleCollapsible defaultOpen={false}>
 *   <SimpleCollapsible.Header title="Initially Closed" />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 * ```
 */
interface SimpleCollapsibleRootProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /** Controlled open state - when provided, component becomes controlled */
  open?: boolean;
  /** Default open state for uncontrolled mode (defaults to true) */
  defaultOpen?: boolean;
  /** Callback fired when the open state changes */
  onOpenChange?: (open: boolean) => void;
}
const Root = React.forwardRef<HTMLDivElement, SimpleCollapsibleRootProps>(
  (
    {
      children,
      open: controlledOpen,
      defaultOpen = true,
      onOpenChange,
      ...props
    },
    ref
  ) => {
    const [internalOpen, setInternalOpen] = React.useState(defaultOpen);

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
      <SimpleCollapsibleContext.Provider value={{ open }}>
        <Collapsible
          ref={ref}
          open={open}
          onOpenChange={handleOpenChange}
          className="flex flex-col flex-1 self-stretch"
          {...props}
        >
          {children}
        </Collapsible>
      </SimpleCollapsibleContext.Provider>
    );
  }
);
Root.displayName = "SimpleCollapsible";

/**
 * SimpleCollapsible Header Component
 *
 * A pre-styled header component for the collapsible trigger.
 * Displays a title and optional description.
 *
 * @example
 * ```tsx
 * <SimpleCollapsible>
 *   <SimpleCollapsible.Header
 *     title="Advanced Settings"
 *     description="Configure advanced options"
 *   />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 *
 * // Title only
 * <SimpleCollapsible>
 *   <SimpleCollapsible.Header title="Quick Settings" />
 *   <SimpleCollapsible.Content>
 *     <div>Content</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 * ```
 */
interface SimpleCollapsibleHeaderProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /** The main heading text displayed in emphasized style */
  title: string;
  /** Optional secondary description text displayed below the title */
  description?: string;
}
const Header = React.forwardRef<HTMLDivElement, SimpleCollapsibleHeaderProps>(
  ({ title, description, ...props }, ref) => {
    const { open } = useSimpleCollapsible();
    const { ref: boundingRef, inside } = useBoundingBox();

    return (
      <CollapsibleTrigger asChild>
        <div
          ref={ref}
          className="flex flex-row items-center justify-between gap-4 cursor-pointer select-none"
          {...props}
        >
          <div ref={boundingRef} className="w-full">
            <Content
              title={title}
              description={description}
              sizePreset="main-content"
              variant="section"
            />
          </div>
          <Button
            icon={open ? SvgFold : SvgExpand}
            prominence="tertiary"
            size="sm"
            transient={inside}
            tooltip={open ? "Fold" : "Expand"}
          />
        </div>
      </CollapsibleTrigger>
    );
  }
);
Header.displayName = "SimpleCollapsible.Header";

/**
 * SimpleCollapsible Content Component
 *
 * Container for the collapsible content area.
 *
 * @example
 * ```tsx
 * <SimpleCollapsible>
 *   <SimpleCollapsible.Header title="Settings" />
 *   <SimpleCollapsible.Content>
 *     <div>Your content here</div>
 *   </SimpleCollapsible.Content>
 * </SimpleCollapsible>
 * ```
 */
const ContentPanel = React.forwardRef<
  HTMLDivElement,
  WithoutStyles<React.HTMLAttributes<HTMLDivElement>>
>(({ children, ...props }, ref) => {
  return (
    <CollapsibleContent>
      <div ref={ref} className="pt-4" {...props}>
        {children}
      </div>
    </CollapsibleContent>
  );
});
ContentPanel.displayName = "SimpleCollapsible.Content";

export default Object.assign(Root, {
  Header,
  Content: ContentPanel,
});
