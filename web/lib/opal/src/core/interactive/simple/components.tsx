import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { useDisabled } from "@opal/core/disabled/components";
import { guardPortalClick } from "@opal/core/interactive/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InteractiveSimpleProps
  extends Omit<
    React.HTMLAttributes<HTMLElement>,
    "className" | "style" | "color"
  > {
  ref?: React.Ref<HTMLElement>;

  /**
   * Tailwind group class (e.g. `"group/Card"`) for `group-hover:*` utilities.
   */
  group?: string;

  /**
   * URL to navigate to when clicked. Passed through Slot to the child.
   */
  href?: string;

  /**
   * Link target (e.g. `"_blank"`). Only used when `href` is provided.
   */
  target?: string;
}

// ---------------------------------------------------------------------------
// InteractiveSimple
// ---------------------------------------------------------------------------

/**
 * Minimal interactive surface primitive.
 *
 * Provides cursor styling, click handling, disabled integration, and
 * optional link/group support — but **no color or background styling**.
 *
 * Use this for elements that need interactivity (click, cursor, disabled)
 * without participating in the Interactive color system.
 *
 * Uses Radix `Slot` — merges props onto a single child element without
 * adding any DOM node.
 *
 * @example
 * ```tsx
 * <Interactive.Simple onClick={handleClick} group="group/Card">
 *   <Card>...</Card>
 * </Interactive.Simple>
 * ```
 */
function InteractiveSimple({
  ref,
  group,
  href,
  target,
  ...props
}: InteractiveSimpleProps) {
  const { isDisabled, allowClick } = useDisabled();

  const classes = cn(
    "cursor-pointer select-none",
    isDisabled && "cursor-not-allowed",
    !props.onClick && !href && "!cursor-default !select-auto",
    group
  );

  const { onClick, ...slotProps } = props;

  const linkAttrs = href
    ? {
        href: isDisabled ? undefined : href,
        target,
        rel: target === "_blank" ? "noopener noreferrer" : undefined,
      }
    : {};

  return (
    <Slot
      ref={ref}
      className={classes}
      aria-disabled={isDisabled || undefined}
      {...linkAttrs}
      {...slotProps}
      onClick={
        isDisabled && !allowClick
          ? href
            ? (e: React.MouseEvent) => e.preventDefault()
            : undefined
          : guardPortalClick(onClick)
      }
    />
  );
}

export { InteractiveSimple, type InteractiveSimpleProps };
