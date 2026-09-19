import "@opal/core/interactive/shared.css";
import "@opal/core/interactive/stateless/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { guardPortalClick } from "@opal/core/interactive/utils";
import type { ButtonType, WithoutStyles } from "@opal/types";
import type {
  InteractiveContract,
  InteractiveVariant,
  InteractiveProminence,
} from "@onyx-ai/shared/contracts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// `variant`/`prominence`/`disabled` come from the shared InteractiveContract. Opal
// re-exports the unions under its `InteractiveStateless*` names so web code imports
// the Interactive family from `@opal/core`, not `@onyx-ai/shared`. `interaction`
// stays web-local — `hover` has no meaning on touch.
type InteractiveStatelessVariant = InteractiveVariant;
type InteractiveStatelessProminence = InteractiveProminence;
type InteractiveStatelessInteraction = "rest" | "hover" | "active";

/**
 * Props for {@link InteractiveStateless}.
 *
 * `variant`, `prominence`, and `disabled` come from the shared
 * {@link InteractiveContract}; the rest are web-specific wiring.
 */
interface InteractiveStatelessProps
  extends
    InteractiveContract,
    WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  ref?: React.Ref<HTMLElement>;

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
  type?: ButtonType;

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
 * Disabled state is controlled via the `disabled` prop.
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
  disabled,
  ...props
}: InteractiveStatelessProps) {
  const isDisabled = !!disabled;

  // onClick/href are always passed directly — Stateless is the outermost Slot,
  // so Radix Slot-injected handlers don't bypass this guard.
  const classes = cn(
    "interactive",
    !props.onClick && !href && !type && "cursor-default! select-auto!",
    group
  );

  const dataAttrs = {
    "data-interactive-variant": variant,
    "data-interactive-prominence": prominence,
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
        isDisabled
          ? href
            ? (e: React.MouseEvent) => e.preventDefault()
            : undefined
          : guardPortalClick(onClick)
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
