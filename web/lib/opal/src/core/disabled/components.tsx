import "@opal/core/disabled/styles.css";
import "@opal/components/tooltip.css";
import React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { TooltipSide } from "@opal/components";
import type { RichStr } from "@opal/types";
import { resolveStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DisabledProps extends React.HTMLAttributes<HTMLDivElement> {
  ref?: React.Ref<HTMLDivElement>;

  /**
   * When truthy, applies disabled styling to child elements.
   */
  disabled?: boolean;

  /**
   * When `true`, re-enables pointer events while keeping the disabled
   * visual treatment. Useful for elements that need to remain interactive
   * (e.g. to show tooltips or handle clicks at a higher level).
   * @default false
   */
  allowClick?: boolean;

  /**
   * Tooltip content shown on hover when disabled. Implies `allowClick` so that
   * the tooltip trigger can receive pointer events. Supports inline markdown
   * via `markdown()`.
   */
  tooltip?: string | RichStr;

  /** Which side the tooltip appears on. @default "right" */
  tooltipSide?: TooltipSide;

  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Disabled
// ---------------------------------------------------------------------------

/**
 * Wrapper component that applies baseline disabled CSS (opacity, cursor,
 * pointer-events) to its children.
 *
 * Renders a `<div>` that carries the `data-opal-disabled` attribute so the
 * CSS rules in `styles.css` take effect on the wrapper and cascade into its
 * descendants. Works with any children (DOM elements, React components, or
 * fragments).
 *
 * @example
 * ```tsx
 * <Disabled disabled={!canSubmit}>
 *   <MyComponent />
 * </Disabled>
 *
 * <Disabled disabled={!canSubmit} tooltip="Feature not available">
 *   <MyComponent />
 * </Disabled>
 * ```
 */
function Disabled({
  disabled,
  allowClick,
  tooltip,
  tooltipSide = "right",
  ref,
  ...rest
}: DisabledProps) {
  const showTooltip = disabled && tooltip;
  const enableClick = allowClick || showTooltip;

  const wrapper = (
    <div
      ref={ref}
      {...rest}
      aria-disabled={disabled || undefined}
      data-opal-disabled={disabled || undefined}
      data-allow-click={disabled && enableClick ? "" : undefined}
    />
  );

  if (!showTooltip) return wrapper;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{wrapper}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="opal-tooltip"
          side={tooltipSide}
          sideOffset={4}
        >
          {resolveStr(tooltip)}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export { Disabled, type DisabledProps };
