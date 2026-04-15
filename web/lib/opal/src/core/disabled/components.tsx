import "@opal/core/disabled/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { Tooltip, type TooltipSide } from "@opal/components";
import type { RichStr } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DisabledProps extends React.HTMLAttributes<HTMLElement> {
  ref?: React.Ref<HTMLElement>;

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

  children: React.ReactElement;
}

// ---------------------------------------------------------------------------
// Disabled
// ---------------------------------------------------------------------------

/**
 * Wrapper component that applies baseline disabled CSS (opacity, cursor,
 * pointer-events) to its child element.
 *
 * Uses Radix `Slot` — merges props onto the single child element without
 * adding any DOM node. Works correctly inside Radix `asChild` chains.
 *
 * @example
 * ```tsx
 * <Disabled disabled={!canSubmit}>
 *   <div>...</div>
 * </Disabled>
 *
 * <Disabled disabled={!canSubmit} tooltip="Feature not available">
 *   <div>...</div>
 * </Disabled>
 * ```
 */
function Disabled({
  disabled,
  allowClick,
  tooltip,
  tooltipSide = "right",
  children,
  ref,
  ...rest
}: DisabledProps) {
  const showTooltip = disabled && tooltip;
  const enableClick = allowClick || showTooltip;

  const wrapper = (
    <Slot
      ref={ref}
      {...rest}
      aria-disabled={disabled || undefined}
      data-opal-disabled={disabled || undefined}
      data-allow-click={disabled && enableClick ? "" : undefined}
    >
      {children}
    </Slot>
  );

  if (!showTooltip) return wrapper;

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {wrapper}
    </Tooltip>
  );
}

export { Disabled, type DisabledProps };
