import Link from "next/link";
import type { Route } from "next";
import "@opal/core/interactive/shared.css";
import React from "react";
import { cn } from "@opal/utils";
import type { ButtonType, WithoutStyles } from "@opal/types";
import {
  containerSizeVariants,
  type ContainerSizeVariants,
  widthVariants,
  type ExtremaSizeVariants,
} from "@opal/shared";
import { useDisabled } from "@opal/core/disabled/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Border-radius presets for `Interactive.Container`.
 *
 * - `"default"` — Default radius of 0.75rem (12px), matching card rounding
 * - `"compact"` — Smaller radius of 0.5rem (8px), for tighter/inline elements
 * - `"mini"` — Smallest radius of 0.25rem (4px)
 */
type InteractiveContainerRoundingVariant =
  keyof typeof interactiveContainerRoundingVariants;
const interactiveContainerRoundingVariants = {
  default: "rounded-12",
  compact: "rounded-08",
  mini: "rounded-04",
} as const;

/**
 * Props for {@link InteractiveContainer}.
 *
 * Extends standard `<div>` attributes (minus `className` and `style`).
 */
interface InteractiveContainerProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  /**
   * Ref forwarded to the underlying element.
   */
  ref?: React.Ref<HTMLElement>;

  /**
   * HTML button type (e.g. `"submit"`, `"button"`, `"reset"`).
   *
   * When provided, renders a `<button>` element instead of a `<div>`.
   * This keeps all styling (background, rounding, height) on a single
   * element — unlike a wrapper approach which would split them.
   *
   * Mutually exclusive with `href`.
   */
  type?: ButtonType;

  /**
   * When `true`, applies a 1px border using the theme's border color.
   *
   * @default false
   */
  border?: boolean;

  /**
   * Border-radius preset controlling corner rounding.
   *
   * @default "default"
   */
  roundingVariant?: InteractiveContainerRoundingVariant;

  /**
   * Size preset controlling the container's height, min-width, and padding.
   *
   * @default "lg"
   */
  heightVariant?: ContainerSizeVariants;

  /**
   * Width preset controlling the container's horizontal size.
   *
   * @default "fit"
   */
  widthVariant?: ExtremaSizeVariants;
}

// ---------------------------------------------------------------------------
// InteractiveContainer
// ---------------------------------------------------------------------------

/**
 * Structural container for use inside `Interactive.Stateless` or
 * `Interactive.Stateful`.
 *
 * Provides a `<div>` with design-system-controlled border, padding, rounding,
 * and height. When nested under a Radix Slot-based parent, correctly extracts
 * and merges injected `className` and `style` values.
 */
function InteractiveContainer({
  ref,
  type,
  border,
  roundingVariant = "default",
  heightVariant = "lg",
  widthVariant = "fit",
  ...props
}: InteractiveContainerProps) {
  const { allowClick } = useDisabled();
  const {
    className: slotClassName,
    style: slotStyle,
    href,
    target,
    rel,
    ...rest
  } = props as typeof props & {
    className?: string;
    style?: React.CSSProperties;
    href?: string;
    target?: string;
    rel?: string;
  };
  const { height, minWidth, padding } = containerSizeVariants[heightVariant];
  const sharedProps = {
    ...rest,
    className: cn(
      "interactive-container",
      interactiveContainerRoundingVariants[roundingVariant],
      height,
      minWidth,
      padding,
      widthVariants[widthVariant],
      slotClassName
    ),
    "data-border": border ? ("true" as const) : undefined,
    style: slotStyle,
  };

  if (href) {
    return (
      <Link
        ref={ref as React.Ref<HTMLAnchorElement>}
        href={href as Route}
        target={target}
        rel={rel}
        {...(sharedProps as React.HTMLAttributes<HTMLAnchorElement>)}
      />
    );
  }

  if (type) {
    const ariaDisabled = (rest as Record<string, unknown>)["aria-disabled"];
    const nativeDisabled =
      (type === "submit" || !allowClick) &&
      (ariaDisabled === true || ariaDisabled === "true" || undefined);
    return (
      <button
        ref={ref as React.Ref<HTMLButtonElement>}
        type={type}
        disabled={nativeDisabled}
        {...(sharedProps as React.HTMLAttributes<HTMLButtonElement>)}
      />
    );
  }
  return <div ref={ref as React.Ref<HTMLDivElement>} {...sharedProps} />;
}

export {
  InteractiveContainer,
  type InteractiveContainerProps,
  type InteractiveContainerRoundingVariant,
};
