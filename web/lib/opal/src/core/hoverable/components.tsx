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
 * Each group gets its own `React.Context<boolean>` so that a
 * `Hoverable.Item` only re-renders when its *own* group's hover state
 * changes — not when any unrelated group changes.
 */
const contextMap = new Map<string, React.Context<boolean>>();

function getOrCreateContext(group: string): React.Context<boolean> {
  let ctx = contextMap.get(group);
  if (!ctx) {
    ctx = createContext<boolean>(false);
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
  group: string;
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
 * An element whose visibility is controlled by the nearest ancestor
 * `Hoverable.Root` with the same group name.
 *
 * Uses data-attributes for variant styling (see `styles.css`).
 *
 * @example
 * ```tsx
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
  const GroupContext = getOrCreateContext(group);
  const isActive = useContext(GroupContext);

  return (
    <div
      {...props}
      className={cn("hoverable-item")}
      data-hoverable-variant={variant}
      data-hoverable-active={isActive ? "true" : undefined}
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
 * Provides two sub-components:
 *
 * - `Hoverable.Root` — A container that tracks hover state for a named group
 *   and provides it via React context.
 *
 * - `Hoverable.Item` — An element that reads hover state from the nearest
 *   matching `Hoverable.Root` and applies variant styles (e.g., `"opacity-on-hover"`).
 *
 * Supports nesting: a child `Hoverable.Root` shadows the parent's context,
 * so each group's items only respond to their own root's hover.
 *
 * @example
 * ```tsx
 * import { Hoverable } from "@opal/core";
 *
 * <Hoverable.Root group="card">
 *   <Card>
 *     <span>Card content</span>
 *     <Hoverable.Item group="card" variant="opacity-on-hover">
 *       <TrashIcon />
 *     </Hoverable.Item>
 *   </Card>
 * </Hoverable.Root>
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
