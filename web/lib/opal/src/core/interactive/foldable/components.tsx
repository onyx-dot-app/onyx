import "@opal/core/interactive/foldable/styles.css";
import type { WithoutStyles } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FoldableProps
  extends WithoutStyles<React.HTMLAttributes<HTMLDivElement>> {
  children: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Foldable
// ---------------------------------------------------------------------------

/**
 * A zero-width collapsible wrapper that expands when its ancestor
 * `.interactive` element is hovered or has an interaction override.
 *
 * Uses a CSS grid `0fr ↔ 1fr` animation for smooth expand/collapse.
 * Must be placed inside an `Interactive.Stateless` or `Interactive.Stateful`
 * tree for the CSS triggers to work.
 *
 * The parent element should add the `interactive-foldable-host` class to
 * get synchronized gap transitions.
 *
 * @example
 * ```tsx
 * <Interactive.Stateful variant="select-heavy" state="empty">
 *   <Interactive.Container>
 *     <div className="interactive-foldable-host flex items-center">
 *       <Icon />
 *       <Foldable>
 *         <span>Label text</span>
 *       </Foldable>
 *     </div>
 *   </Interactive.Container>
 * </Interactive.Stateful>
 * ```
 */
function Foldable({ children, ...props }: FoldableProps) {
  return (
    <div {...props} className="interactive-foldable">
      <div className="interactive-foldable-inner">{children}</div>
    </div>
  );
}

export { Foldable, type FoldableProps };
