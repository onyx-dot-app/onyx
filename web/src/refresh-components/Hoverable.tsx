import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";
import Link from "next/link";
import type { Route } from "next";
import { WithoutStyles } from "@/types";
import { SvgChevronDownSmall } from "@opal/icons";

type ButtonHeightVariants = "standard" | "compact" | "full";
type HoverableVariants = "primary" | "secondary" | "tertiary";

const buttonHeightVariants = {
  standard: "h-[2.25rem]",
  compact: "h-[1.75rem]",
  full: "h-full",
} as const;

interface HoverableContainerProps
  extends WithoutStyles<React.HtmlHTMLAttributes<HTMLDivElement>> {
  border?: boolean;
  reducedRounding?: boolean;
  noPadding?: boolean;
  heightVariant?: ButtonHeightVariants;
  ref?: React.Ref<HTMLDivElement>;
}

function HoverableContainer({
  border,
  reducedRounding,
  noPadding,
  heightVariant = "standard",
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
        reducedRounding ? "rounded-08" : "rounded-12",
        !noPadding && "p-2",
        buttonHeightVariants[heightVariant],
        slotClassName
      )}
      style={slotStyle}
    />
  );
}

/**
 * ChevronHoverableContainer
 *
 * Like HoverableContainer, but renders a chevron-down icon on the right that
 * rotates 180° when "open".
 *
 * Open state is resolved in order:
 * 1. Explicit `open` prop
 * 2. Radix `data-state` attribute (injected through the Slot chain by
 *    Popover.Trigger → Hoverable asChild → this component)
 *
 * @example
 * ```tsx
 * <Popover>
 *   <Popover.Trigger asChild>
 *     <Hoverable asChild>
 *       <ChevronHoverableContainer>
 *         <LineItemLayout icon={SvgIcon} title="Option" variant="secondary" center />
 *       </ChevronHoverableContainer>
 *     </Hoverable>
 *   </Popover.Trigger>
 *   <Popover.Content>…</Popover.Content>
 * </Popover>
 * ```
 */
interface ChevronHoverableContainerProps extends HoverableContainerProps {
  /** Explicit open state. When omitted, falls back to Radix `data-state`. */
  open?: boolean;
}

function ChevronHoverableContainer({
  open,
  children,
  ...containerProps
}: ChevronHoverableContainerProps) {
  // Derive open state: explicit prop → Radix data-state (injected via Slot chain)
  const dataState = (containerProps as Record<string, unknown>)[
    "data-state"
  ] as string | undefined;
  const isOpen = open ?? dataState === "open";

  return (
    <HoverableContainer {...containerProps}>
      <div className="flex flex-row items-center gap-2">
        <div className="flex-1 min-w-0">{children}</div>
        <SvgChevronDownSmall
          className={cn(
            "shrink-0 transition-transform duration-200",
            isOpen && "-rotate-180"
          )}
          size={14}
        />
      </div>
    </HoverableContainer>
  );
}

export interface HoverableProps
  extends WithoutStyles<React.HTMLAttributes<HTMLElement>> {
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
  /** When true, forces the pressed visual state (same as `data-pressed="true"`). */
  transient?: boolean;
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
function Hoverable({
  children,
  asChild,
  href,
  ref,
  group,
  nonInteractive,
  transient,
  variant = "primary",
  ...props
}: HoverableProps) {
  const classes = cn(
    "hoverable",
    !props.onClick && !href && "cursor-default",
    group
  );
  const dataAttrs = {
    "data-variant": variant,
    ...(nonInteractive && { "data-non-interactive": "true" as const }),
    ...(transient && { "data-pressed": "true" as const }),
  };

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

export { Hoverable, HoverableContainer, ChevronHoverableContainer };
