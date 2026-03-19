import "@opal/core/interactive/shared.css";
import "@opal/core/interactive/stateless/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { useDisabled } from "@opal/core/disabled/components";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type InteractiveStatelessVariant = "none" | "default" | "action" | "danger";
type InteractiveStatelessProminence =
  | "primary"
  | "secondary"
  | "tertiary"
  | "internal";
type InteractiveStatelessInteraction = "rest" | "hover" | "active";

/**
 * Props for {@link InteractiveStateless}.
 */
interface InteractiveStatelessProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  ref?: React.Ref<HTMLElement>;

  /**
   * Visual variant controlling the color palette.
   * @default "default"
   */
  variant?: InteractiveStatelessVariant;

  /**
   * Prominence level controlling background intensity.
   * @default "primary"
   */
  prominence?: InteractiveStatelessProminence;

  /**
   * JS-controllable interaction state override.
   *
   * - `"rest"` — default appearance (no override)
   * - `"hover"` — forces hover visual state
   * - `"active"` — forces active/pressed visual state
   *
   * @default "rest"
   */
  interaction?: InteractiveStatelessInteraction;

  /**
   * Tailwind group class (e.g. `"group/Card"`) for `group-hover:*` utilities.
   */
  group?: string;

  /**
   * HTML button type. When set to `"submit"`, `"button"`, or `"reset"`, the
   * element is treated as inherently interactive for cursor styling purposes
   * even without an explicit `onClick` or `href`.
   */
  type?: "submit" | "button" | "reset";

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
// InteractiveStateless
// ---------------------------------------------------------------------------

/**
 * Stateless interactive surface primitive.
 *
 * The foundational building block for buttons, links, and any clickable
 * element that does not maintain selection state. Applies variant/prominence
 * color styling via CSS data-attributes and merges onto a single child
 * element via Radix `Slot`.
 *
 * Disabled state is consumed from the nearest `<Disabled>` ancestor via
 * context — there is no `disabled` prop on this component.
 */
function InteractiveStateless({
  ref,
  variant = "default",
  prominence = "primary",
  interaction = "rest",
  group,
  type,
  href,
  target,
  ...props
}: InteractiveStatelessProps) {
  const { isDisabled, allowClick } = useDisabled();

  // onClick/href are always passed directly — Stateless is the outermost Slot,
  // so Radix Slot-injected handlers don't bypass this guard.
  const classes = cn(
    "interactive",
    !props.onClick && !href && !type && "!cursor-default !select-auto",
    group
  );

  const dataAttrs = {
    "data-interactive-variant": variant !== "none" ? variant : undefined,
    "data-interactive-prominence": variant !== "none" ? prominence : undefined,
    "data-interaction": interaction !== "rest" ? interaction : undefined,
    "data-disabled": isDisabled ? "true" : undefined,
    "aria-disabled": isDisabled || undefined,
  };

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
      {...dataAttrs}
      {...linkAttrs}
      {...slotProps}
      onClick={
        isDisabled && !allowClick
          ? href
            ? (e: React.MouseEvent) => e.preventDefault()
            : undefined
          : onClick
      }
    />
  );
}

export {
  InteractiveStateless,
  type InteractiveStatelessProps,
  type InteractiveStatelessVariant,
  type InteractiveStatelessProminence,
  type InteractiveStatelessInteraction,
};
