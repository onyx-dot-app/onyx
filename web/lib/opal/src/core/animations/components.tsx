"use client";

import "@opal/core/animations/styles.css";
import React from "react";
import { cn } from "@opal/utils";
import type { WithoutStyles, ExtremaSizeVariants } from "@opal/types";
import { widthVariants } from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type HoverableInteraction = "rest" | "hover";

interface HoverableRootProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children: React.ReactNode;
  group: string;
  /** Width preset. @default "auto" */
  widthVariant?: ExtremaSizeVariants;
  /**
   * JS-controllable interaction state override.
   *
   * - `"rest"` (default): items are shown/hidden by CSS `:hover`.
   * - `"hover"`: forces items visible regardless of hover state. Useful when
   *   a hoverable action opens a modal — set `interaction="hover"` while the
   *   modal is open so the user can see which element they're interacting with.
   *
   * @default "rest"
   */
  interaction?: HoverableInteraction;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

type HoverableItemVariant = "opacity-on-hover";

interface HoverableItemProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children: React.ReactNode;
  group?: string;
  variant?: HoverableItemVariant;
  /** Ref forwarded to the item `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// HoverableRoot
// ---------------------------------------------------------------------------

/**
 * Hover-tracking container for a named group.
 *
 * Uses a `data-hover-group` attribute and CSS `:hover` to control
 * descendant `Hoverable.Item` visibility. No React state or context —
 * the browser natively removes `:hover` when modals/portals steal
 * pointer events, preventing stale hover state.
 *
 * @example
 * ```tsx
 * <Hoverable.Root group="card">
 *   <Card>
 *     <Hoverable.Item group="card" variant="opacity-on-hover">
 *       <TrashIcon />
 *     </Hoverable.Item>
 *   </Card>
 * </Hoverable.Root>
 * ```
 */
function HoverableRoot({
  group,
  children,
  widthVariant = "full",
  interaction = "rest",
  ref,
  ...props
}: HoverableRootProps) {
  return (
    <div
      {...props}
      ref={ref}
      className={cn(widthVariants[widthVariant])}
      data-hover-group={group}
      data-interaction={interaction !== "rest" ? interaction : undefined}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HoverableItem
// ---------------------------------------------------------------------------

/**
 * An element whose visibility is controlled by hover state.
 *
 * **Local mode** (`group` omitted): the item handles hover on its own
 * element via CSS `:hover`.
 *
 * **Group mode** (`group` provided): visibility is driven by CSS `:hover`
 * on the nearest `Hoverable.Root` ancestor via `[data-hover-group]:hover`.
 *
 * @example
 * ```tsx
 * // Local mode — hover on the item itself
 * <Hoverable.Item variant="opacity-on-hover">
 *   <TrashIcon />
 * </Hoverable.Item>
 *
 * // Group mode — hover on the Root reveals the item
 * <Hoverable.Root group="card">
 *   <Hoverable.Item group="card" variant="opacity-on-hover">
 *     <TrashIcon />
 *   </Hoverable.Item>
 * </Hoverable.Root>
 * ```
 */
function HoverableItem({
  group,
  variant = "opacity-on-hover",
  children,
  ref,
  ...props
}: HoverableItemProps) {
  const isLocal = group === undefined;

  return (
    <div
      {...props}
      ref={ref}
      className={cn("hoverable-item")}
      data-hoverable-variant={variant}
      data-hoverable-local={isLocal ? "true" : undefined}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compound export
// ---------------------------------------------------------------------------

/**
 * Hoverable compound component for hover-to-reveal patterns.
 *
 * Entirely CSS-driven — no React state or context. The browser's native
 * `:hover` pseudo-class handles all state, which means hover is
 * automatically cleared when modals/portals steal pointer events.
 *
 * - `Hoverable.Root` — Container with `data-hover-group`. CSS `:hover`
 *   on this element reveals descendant `Hoverable.Item` elements.
 *
 * - `Hoverable.Item` — Hidden by default. In group mode, revealed when
 *   the ancestor Root is hovered. In local mode (no `group`), revealed
 *   when the item itself is hovered.
 *
 * @example
 * ```tsx
 * import { Hoverable } from "@opal/core";
 *
 * // Group mode — hovering the card reveals the trash icon
 * <Hoverable.Root group="card">
 *   <Card>
 *     <span>Card content</span>
 *     <Hoverable.Item group="card" variant="opacity-on-hover">
 *       <TrashIcon />
 *     </Hoverable.Item>
 *   </Card>
 * </Hoverable.Root>
 *
 * // Local mode — hovering the item itself reveals it
 * <Hoverable.Item variant="opacity-on-hover">
 *   <TrashIcon />
 * </Hoverable.Item>
 * ```
 */
const Hoverable = {
  Root: HoverableRoot,
  Item: HoverableItem,
};

export {
  Hoverable,
  type HoverableRootProps,
  type HoverableItemProps,
  type HoverableItemVariant,
  type HoverableInteraction,
};
