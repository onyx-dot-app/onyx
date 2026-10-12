import "@opal/core/disabled/styles.css";
import React from "react";
import { Tooltip, type TooltipSide } from "@opal/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
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
   * via `markdown()`. Screen readers read it as plain text from a hidden live
   * region.
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
      {/* The tooltip only exists while hovered, and nothing inside a disabled
        region can take focus to open it, so the reason is also kept here for
        assistive technology. It is polite and always rendered, so a change of
        reason is announced and unlocking announces nothing. It is hidden like
        sr-only, but fixed rather than absolute: a fixed box never adds to a
        scroll area's height, so it cannot make the page scrollable. */}
      <span
        className="fixed size-px overflow-hidden whitespace-nowrap [clip-path:inset(50%)]"
        aria-live="polite"
        aria-atomic="true"
      >
        {disabled && tooltip ? toPlainString(tooltip) : ""}
      </span>
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
