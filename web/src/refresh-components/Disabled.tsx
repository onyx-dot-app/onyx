import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

/**
 * Standard disabled styles used across the application.
 * - opacity-50: Visual feedback that the element is inactive
 * - cursor-not-allowed: Indicates the element cannot be interacted with
 * - pointer-events-none: Prevents all mouse/touch interactions
 * - select-none: Prevents text selection
 */
const DISABLED_STYLES =
  "opacity-50 cursor-not-allowed pointer-events-none select-none";

/**
 * Disabled styles that still allow click interactions.
 * Use this for elements that need to show tooltips, error messages,
 * or other feedback when clicked while in a disabled state.
 * - opacity-50: Visual feedback that the element is inactive
 * - cursor-not-allowed: Indicates the element cannot be interacted with
 */
const DISABLED_ALLOW_CLICK_STYLES = "opacity-50 cursor-not-allowed";

export interface DisabledProps {
  /**
   * When true, applies disabled styling to the child element.
   * When false or undefined, renders the child unchanged.
   */
  disabled?: boolean;
  /**
   * When true, allows click interactions while still appearing disabled.
   * Useful for elements that need to show tooltips or error messages.
   * @default false
   */
  allowClick?: boolean;
  /**
   * The child element to apply disabled styling to.
   * Must be a single React element.
   */
  children: React.ReactElement;
}

/**
 * Disabled Component
 *
 * A pure wrapper component that standardizes disabled styling across the application.
 * Uses Radix Slot to merge props directly onto its child element without adding
 * an extra wrapper div.
 *
 * @example
 * ```tsx
 * // Basic usage - blocks all interactions
 * <Disabled disabled={!isEnabled}>
 *   <Card>
 *     <Text>This content is fully disabled</Text>
 *   </Card>
 * </Disabled>
 *
 * // Allow clicks for tooltips/feedback
 * <Disabled disabled={isDisabled} allowClick>
 *   <Button onClick={showTooltip}>Hover for info</Button>
 * </Disabled>
 * ```
 *
 * @remarks
 * - By default, applies: opacity-50, cursor-not-allowed, pointer-events-none, select-none
 * - With allowClick: applies only opacity-50, cursor-not-allowed (clicks still work)
 * - Sets aria-disabled attribute for accessibility
 * - Uses Radix Slot to avoid extra DOM nodes
 * - When disabled is false/undefined, renders child unchanged
 * - Forwards refs so it can be used as a tooltip trigger
 */
const Disabled = React.forwardRef<
  HTMLElement,
  DisabledProps & React.HTMLAttributes<HTMLElement>
>(function Disabled({ disabled, allowClick = false, children, ...rest }, ref) {
  // When not disabled, render child unchanged (still forward ref + props
  // so parent Slots like TooltipTrigger asChild work correctly)
  if (!disabled) {
    return (
      <Slot ref={ref} {...rest}>
        {children}
      </Slot>
    );
  }

  const styles = allowClick ? DISABLED_ALLOW_CLICK_STYLES : DISABLED_STYLES;

  return (
    <Slot
      ref={ref}
      {...rest}
      className={cn(
        // Get existing className from child if present
        (children.props as { className?: string }).className,
        rest.className,
        styles
      )}
      aria-disabled="true"
    >
      {children}
    </Slot>
  );
});

export { Disabled };
export default Disabled;
