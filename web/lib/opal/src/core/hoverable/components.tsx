import "@opal/core/hoverable/styles.css";
import React, { createContext, useContext, useState, useCallback } from "react";
import { cn } from "@opal/utils";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Context-per-group registry
// ---------------------------------------------------------------------------

/**
 * Lazily-created map of group names to React contexts.
 *
 * Each group gets its own `React.Context<boolean | null>` so that a
 * `Hoverable.Item` only re-renders when its *own* group's hover state
 * changes — not when any unrelated group changes.
 *
 * The default value is `null` (no provider found), which lets
 * `Hoverable.Item` distinguish "no Root ancestor" from "Root says
 * not hovered" and fall back to local `:hover` styling.
 */
const contextMap = new Map<string, React.Context<boolean | null>>();

function getOrCreateContext(group: string): React.Context<boolean | null> {
  let ctx = contextMap.get(group);
  if (!ctx) {
    ctx = createContext<boolean | null>(null);
    ctx.displayName = `HoverableContext(${group})`;
    contextMap.set(group, ctx);
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HoverableRootProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children: React.ReactNode;
  group: string;
}

type HoverableItemVariant = "opacity-on-hover";

interface HoverableItemProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children: React.ReactNode;
  group?: string;
  variant?: HoverableItemVariant;
}

// ---------------------------------------------------------------------------
// HoverableRoot
// ---------------------------------------------------------------------------

/**
 * Hover-tracking container for a named group.
 *
 * Wraps children in a `<div>` that tracks mouse-enter / mouse-leave and
 * provides the hover state via a per-group React context.
 *
 * Nesting works because each `Hoverable.Root` creates a **new** context
 * provider that shadows the parent — so an inner `Hoverable.Item group="b"`
 * reads from the inner provider, not the outer `group="a"` provider.
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
function HoverableRoot({ group, children, ...props }: HoverableRootProps) {
  const [hovered, setHovered] = useState(false);
  const onMouseEnter = useCallback(() => setHovered(true), []);
  const onMouseLeave = useCallback(() => setHovered(false), []);

  const GroupContext = getOrCreateContext(group);

  return (
    <GroupContext.Provider value={hovered}>
      <div {...props} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
        {children}
      </div>
    </GroupContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// HoverableItem
// ---------------------------------------------------------------------------

/**
 * An element whose visibility is controlled by hover state.
 *
 * **Group mode** (`group` provided + matching `Hoverable.Root` ancestor):
 * visibility is driven by the Root's hover state via React context.
 *
 * **Local mode** (`group` omitted, or no matching `Hoverable.Root` found):
 * the item handles hover on its own element via CSS `:hover`.
 *
 * Uses data-attributes for variant styling (see `styles.css`).
 *
 * @example
 * ```tsx
 * // Local mode — hover on the item itself
 * <Hoverable.Item variant="opacity-on-hover">
 *   <TrashIcon />
 * </Hoverable.Item>
 *
 * // Group mode — hover on the Root reveals the item
 * <Hoverable.Item group="card" variant="opacity-on-hover">
 *   <TrashIcon />
 * </Hoverable.Item>
 * ```
 */
function HoverableItem({
  group,
  variant = "opacity-on-hover",
  children,
  ...props
}: HoverableItemProps) {
  const contextValue = useContext(
    group ? getOrCreateContext(group) : EMPTY_CONTEXT
  );
  const isLocal = contextValue === null;

  return (
    <div
      {...props}
      className={cn("hoverable-item")}
      data-hoverable-variant={variant}
      data-hoverable-active={
        isLocal ? undefined : contextValue ? "true" : undefined
      }
      data-hoverable-local={isLocal ? "true" : undefined}
    >
      {children}
    </div>
  );
}

/** Stable context that always returns `null` (no provider). */
const EMPTY_CONTEXT = createContext<boolean | null>(null);

// ---------------------------------------------------------------------------
// Compound export
// ---------------------------------------------------------------------------

/**
 * Hoverable compound component for hover-to-reveal patterns.
 *
 * Provides two sub-components:
 *
 * - `Hoverable.Root` — A container that tracks hover state for a named group
 *   and provides it via React context.
 *
 * - `Hoverable.Item` — An element that applies variant styles
 *   (e.g., `"opacity-on-hover"`). When `group` is provided and a matching
 *   `Hoverable.Root` ancestor exists, visibility is driven by the Root's
 *   hover state. Otherwise, the item falls back to local CSS `:hover`.
 *
 * Supports nesting: a child `Hoverable.Root` shadows the parent's context,
 * so each group's items only respond to their own root's hover.
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
};
