import type React from "react";

/**
 * Guards an onClick handler against React synthetic event bubbling from
 * portalled children (e.g. Radix Dialog overlays).
 *
 * React bubbles synthetic events through the **fiber tree** (component
 * hierarchy), not the DOM tree. This means a click on a portalled modal
 * overlay will bubble to a parent component's onClick even though the
 * overlay is not a DOM descendant. This guard checks that the click
 * target is actually inside the handler's DOM element before firing.
 */
function guardPortalClick<E extends React.MouseEvent>(
  onClick: ((e: E) => void) | undefined
): ((e: E) => void) | undefined {
  if (!onClick) return undefined;
  return (e: E) => {
    if (
      e.currentTarget instanceof Node &&
      e.target instanceof Node &&
      e.currentTarget.contains(e.target)
    ) {
      onClick(e);
    }
  };
}

export { guardPortalClick };
