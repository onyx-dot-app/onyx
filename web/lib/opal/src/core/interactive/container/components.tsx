import Link from "next/link";
import type { Route } from "next";
import "@opal/core/interactive/shared.css";
import React from "react";
import { cn } from "@opal/utils";
import type { ButtonType, Rounding, WithoutStyles } from "@opal/types";
import {
  containerSizeVariants,
  roundingToRem,
  type ContainerSizeVariants,
  type ExtremaSizeVariants,
  widthVariants,
} from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Props for {@link InteractiveContainer}.
 *
 * Extends standard `<div>` attributes (minus `className` and `style`).
 */
interface InteractiveContainerProps extends WithoutStyles<
  React.HTMLAttributes<HTMLDivElement>
> {
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
   * Corner radius, on the same scale as `Spacing`: `N` is `N / 4` rem, so
   * `rounding={2}` is the same distance as `padding={2}`. `"full"` is a pill.
   *
   * @default 3
   */
  rounding?: Rounding;

  /**
   * Size preset controlling the container's height, min-width, and padding.
   *
   * @default "lg"
   */
  size?: ContainerSizeVariants;

  /**
   * Width preset controlling the container's horizontal size.
   *
   * @default "fit"
   */
  width?: ExtremaSizeVariants;
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
  rounding = 3,
  size = "lg",
  width = "fit",
  ...props
}: InteractiveContainerProps) {
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
  const { height, minWidth, padding } = containerSizeVariants[size];
  const sharedProps = {
    ...rest,
    className: cn(
      "interactive-container",
      height,
      minWidth,
      padding,
      widthVariants[width],
      slotClassName
    ),
    "data-border": border ? ("true" as const) : undefined,
    // Radius is written straight in rather than looked up as a class, so the
    // step can come from a runtime value. A Slot-injected radius still wins.
    style: { borderRadius: roundingToRem(rounding), ...slotStyle },
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
      ariaDisabled === true || ariaDisabled === "true" || undefined;
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

export { InteractiveContainer, type InteractiveContainerProps };
