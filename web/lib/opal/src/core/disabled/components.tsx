import "@opal/core/disabled/styles.css";
import React from "react";
import { Tooltip, type TooltipSide } from "@opal/components";
import type { RichStr, WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DisabledProps extends WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
> {
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

  children?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Disabled
// ---------------------------------------------------------------------------

/**
 * Wrapper component that applies baseline disabled CSS (opacity, cursor,
 * pointer-events) to its children, and, unless `allowClick` is set, disables
 * the form controls inside so the keyboard cannot reach them either.
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
  children,
  ...rest
}: DisabledProps) {
  const showTooltip = disabled && tooltip;
  const enableClick = allowClick || showTooltip;
  // The CSS only blocks the pointer. A disabled fieldset also takes the form
  // controls inside out of the tab order and stops keyboard input. It is
  // always rendered, so toggling `disabled` never remounts the children.
  // `allowClick` keeps the children interactive, so it keeps the keyboard.
  const blockKeyboard: boolean = Boolean(disabled) && !allowClick;

  const wrapper = (
    <div
      ref={ref}
      {...rest}
      aria-disabled={disabled || undefined}
      data-opal-disabled={disabled || undefined}
      data-allow-click={disabled && enableClick ? "" : undefined}
    >
      <fieldset disabled={blockKeyboard} className="contents">
        {children}
      </fieldset>
    </div>
  );

  if (!showTooltip) return wrapper;

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {wrapper}
    </Tooltip>
  );
}

export { Disabled, type DisabledProps };
