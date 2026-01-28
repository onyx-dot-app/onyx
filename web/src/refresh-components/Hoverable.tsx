import React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";
import Link from "next/link";
import type { Route } from "next";
import { WithoutStyles } from "@/types";

export interface HoverableProps
  extends WithoutStyles<React.HTMLAttributes<HTMLButtonElement>> {
  /** Content to be wrapped with hover behavior */
  children: React.ReactNode;
  /**
   * When true, the child element becomes the interactive element.
   * The child can define its own `data-pressed` attribute.
   */
  asChild?: boolean;
  /** Optional href to render as a link instead of a button */
  href?: string;
  /** Ref to the underlying button element */
  ref?: React.Ref<HTMLButtonElement>;
  /**
   * Tailwind group class to apply (e.g., "group/AgentCard").
   * Enables group-hover utilities on descendant elements.
   */
  group?: string;
  disableHoverInteractivity?: boolean;
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
 * - When `href` is provided, the content is wrapped in a Next.js `<Link>`
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
  disableHoverInteractivity,
  ...props
}: HoverableProps) {
  const Comp = asChild ? Slot : "button";

  const content = (
    <Comp
      ref={ref}
      type={asChild ? undefined : "button"}
      className={cn(
        "flex flex-1 cursor-pointer",
        !disableHoverInteractivity && [
          "transition-colors",
          "hover:bg-background-tint-02",
          "active:bg-background-tint-00",
          "data-[pressed=true]:bg-background-tint-00",
        ],
        group
      )}
      {...props}
    >
      {children}
    </Comp>
  );

  if (!href) return content;
  return <Link href={href as Route}>{content}</Link>;
}
