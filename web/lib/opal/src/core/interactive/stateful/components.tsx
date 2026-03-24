import "@opal/core/interactive/shared.css";
import "@opal/core/interactive/stateful/styles.css";
import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@opal/utils";
import { useDisabled } from "@opal/core/disabled/components";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type InteractiveStatefulVariant =
  | "select-light"
  | "select-heavy"
  | "select-tinted"
  | "select-filter"
  | "sidebar";
type InteractiveStatefulState = "empty" | "filled" | "selected";
type InteractiveStatefulInteraction = "rest" | "hover" | "active";

/**
 * Props for {@link InteractiveStateful}.
 */
interface InteractiveStatefulProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  ref?: React.Ref<HTMLElement>;

  /**
   * Visual variant controlling the color palette and behavior.
   *
   * - `"select-light"` — transparent selected background (for inline toggles)
   * - `"select-heavy"` — tinted selected background (for list rows, model pickers)
   * - `"select-tinted"` — like select-heavy but with a tinted rest background
   * - `"select-filter"` — like select-tinted for empty/filled; selected state uses inverted tint backgrounds and inverted text (for filter buttons)
   * - `"sidebar"` — for sidebar navigation items
   *
   * @default "select-heavy"
   */
  variant?: InteractiveStatefulVariant;

  /**
   * The current value state of this element.
   *
   * - `"empty"` — no value / unset
   * - `"filled"` — has a value but not actively selected
   * - `"selected"` — actively chosen / focused
   *
   * @default "empty"
   */
  state?: InteractiveStatefulState;

  /**
   * JS-controllable interaction state override.
   *
   * - `"rest"` — default appearance (no override)
   * - `"hover"` — forces hover visual state
   * - `"active"` — forces active/pressed visual state
   *
   * @default "rest"
   */
  interaction?: InteractiveStatefulInteraction;

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
// InteractiveStateful
// ---------------------------------------------------------------------------

/**
 * Stateful interactive surface primitive.
 *
 * The foundational building block for elements that maintain a value state
 * (empty/filled/selected). Applies variant/state color styling via CSS
 * data-attributes and merges onto a single child element via Radix `Slot`.
 *
 * Disabled state is consumed from the nearest `<Disabled>` ancestor via
 * context — there is no `disabled` prop on this component.
 */
function InteractiveStateful({
  ref,
  variant = "select-heavy",
  state = "empty",
  interaction = "rest",
  group,
  href,
  target,
  ...props
}: InteractiveStatefulProps) {
  const { isDisabled, allowClick } = useDisabled();

  // onClick/href are always passed directly — Stateful is the outermost Slot,
  // so Radix Slot-injected handlers don't bypass this guard.
  const classes = cn(
    "interactive",
    !props.onClick && !href && "!cursor-default !select-auto",
    group
  );

  const dataAttrs = {
    "data-interactive-variant": variant,
    "data-interactive-state": state,
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
  InteractiveStateful,
  type InteractiveStatefulProps,
  type InteractiveStatefulVariant,
  type InteractiveStatefulState,
  type InteractiveStatefulInteraction,
};
