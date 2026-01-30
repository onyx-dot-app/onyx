import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";
import Link from "next/link";
import type { Route } from "next";
import { WithoutStyles } from "@/types";
import {
  heightClassmap,
  Length,
  widthClassmap,
} from "@/layouts/general-layouts";

type HoverableVariants = "primary" | "secondary" | "tertiary";

interface HoverableContainerProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  border?: boolean;
  rounded?: string;
  padding?: number;
  height?: Length;
  width?: Length;
  ref?: React.Ref<HTMLDivElement>;
}

function HoverableContainer({
  border,
  rounded = "rounded-08",
  padding = 0.5,
  height = "full",
  width = "full",
  ref,
  ...props
}: HoverableContainerProps) {
  // Radix Slot injects className at runtime (bypassing WithoutStyles),
  // so we extract and merge it to preserve "hoverable-container".
  const {
    className: slotClassName,
    style: slotStyle,
    ...rest
  } = props as typeof props & {
    className?: string;
    style?: React.CSSProperties;
  };
  return (
    <div
      ref={ref}
      {...rest}
      className={cn(
        border && "border",
        rounded,
        widthClassmap[width],
        heightClassmap[height],
        slotClassName
      )}
      style={{
        ...slotStyle,
        padding: `${padding}rem`,
      }}
    />
  );
}

export interface HoverableProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
  /** Content to be wrapped with hover behavior */
  children: React.ReactNode;
  /**
   * When true, the child element becomes the interactive element.
   * The child can define its own `data-pressed` attribute.
   */
  asChild?: boolean;
  /** Optional href to render as a link instead of a button */
  href?: string;
  /** Ref to the underlying element (button or anchor depending on href) */
  ref?: React.Ref<HTMLButtonElement | HTMLAnchorElement>;
  /**
   * Tailwind group class to apply (e.g., "group/AgentCard").
   * Enables group-hover utilities on descendant elements.
   */
  group?: string;
  nonInteractive?: boolean;
  /** Controls background color styling on the hoverable element. */
  variant?: HoverableVariants;
}

/**
 * Hoverable Component
 *
 * A wrapper component that adds hover, active, and pressed states to any content.
 * Useful for making cards, panels, or any arbitrary content clickable with
 * consistent hover feedback.
 *
 * @example
 * ```tsx
 * // Basic usage with a Card
 * <Hoverable onClick={handleClick}>
 *   <Card>
 *     <Text>Click me!</Text>
 *   </Card>
 * </Hoverable>
 *
 * // As a link
 * <Hoverable href="/dashboard">
 *   <Card>
 *     <Text>Go to Dashboard</Text>
 *   </Card>
 * </Hoverable>
 *
 * // With asChild - child controls pressed state
 * <Hoverable asChild onClick={handleClick}>
 *   <Card data-pressed={isSelected}>
 *     <Text>Selectable item</Text>
 *   </Card>
 * </Hoverable>
 *
 * // With group - enables group-hover utilities on descendants
 * <Hoverable asChild onClick={handleClick} group="group/MyCard">
 *   <Card>
 *     <IconButton className="hidden group-hover/MyCard:flex" />
 *   </Card>
 * </Hoverable>
 * ```
 *
 * @remarks
 * - The component renders as a `<button type="button">` by default
 * - When `asChild` is true, props are merged onto the child element via Radix Slot
 * - When `href` is provided, renders as a Next.js `<Link>` (anchor) directly
 * - Hover styles apply a subtle background tint
 * - Active/pressed states apply a slightly stronger tint
 * - Use `data-pressed="true"` on the child (with `asChild`) to show pressed state
 */
export default function Hoverable({
  children,
  asChild,
  href,
  ref,
  group,
  nonInteractive,
  variant = "primary",
  ...props
}: HoverableProps) {
  const classes = cn(
    "hoverable",
    `hoverable--${variant}`,
    nonInteractive && "cursor-default",
    group
  );
  const dataAttrs = nonInteractive
    ? { "data-non-interactive": "true" as const }
    : {};

  // asChild: merge props onto child element
  if (asChild) {
    return (
      <Slot ref={ref} className={classes} {...dataAttrs} {...props}>
        {children}
      </Slot>
    );
  }

  // href: render as Link (anchor) directly
  if (href) {
    return (
      <Link
        href={href as Route}
        ref={ref as React.Ref<HTMLAnchorElement>}
        className={classes}
        {...dataAttrs}
        {...props}
      >
        {children}
      </Link>
    );
  }

  // default: render as button
  return (
    <button
      ref={ref as React.Ref<HTMLButtonElement>}
      type="button"
      className={classes}
      {...dataAttrs}
      {...props}
    >
      {children}
    </button>
  );
}

export { HoverableContainer };
