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
 * not hovered" and throw when `group` was explicitly specified.
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
function HoverableRoot({
  group,
  children,
  onMouseEnter: consumerMouseEnter,
  onMouseLeave: consumerMouseLeave,
  ...props
}: HoverableRootProps) {
  const [hovered, setHovered] = useState(false);

  const onMouseEnter = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      setHovered(true);
      consumerMouseEnter?.(e);
    },
    [consumerMouseEnter]
  );

  const onMouseLeave = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      setHovered(false);
      consumerMouseLeave?.(e);
    },
    [consumerMouseLeave]
  );

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
 * **Local mode** (`group` omitted): the item handles hover on its own
 * element via CSS `:hover`. This is the core abstraction.
 *
 * **Group mode** (`group` provided): visibility is driven by a matching
 * `Hoverable.Root` ancestor's hover state via React context. If no
 * matching Root is found, an error is thrown.
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
 * <Hoverable.Root group="card">
 *   <Hoverable.Item group="card" variant="opacity-on-hover">
 *     <TrashIcon />
 *   </Hoverable.Item>
 * </Hoverable.Root>
 * ```
 *
 * @throws If `group` is specified but no matching `Hoverable.Root` ancestor exists.
 */
function HoverableItem({
  group,
  variant = "opacity-on-hover",
  children,
  ...props
}: HoverableItemProps) {
  const contextValue = useContext(
    group ? getOrCreateContext(group) : NOOP_CONTEXT
  );

  if (group && contextValue === null) {
    throw new Error(
      `Hoverable.Item group="${group}" has no matching Hoverable.Root ancestor. ` +
        `Either wrap it in <Hoverable.Root group="${group}"> or remove the group prop for local hover.`
    );
  }

  const isLocal = group === undefined;

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

/** Stable context used when no group is specified (local mode). */
const NOOP_CONTEXT = createContext<boolean | null>(null);

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
 * - `Hoverable.Item` — The core abstraction. On its own (no `group`), it
 *   applies local CSS `:hover` for the variant effect. When `group` is
 *   specified, it reads hover state from the nearest matching
 *   `Hoverable.Root` — and throws if no matching Root is found.
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
