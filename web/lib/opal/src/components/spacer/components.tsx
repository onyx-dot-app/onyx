import type { OrientationVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SpacerProps {
  rem?: number;
  orientation?: OrientationVariants;
}

// ---------------------------------------------------------------------------
// Spacer
// ---------------------------------------------------------------------------

/**
 * A zero-content element that inserts a fixed-size gap.
 *
 * Defaults to vertical spacing of 1rem. Supply `rem` for size and
 * `orientation` for direction (`"vertical"` is the default).
 *
 * @example
 * ```tsx
 * <Spacer orientation="vertical" rem={2} />
 * <Spacer orientation="horizontal" rem={1.5} />
 * ```
 */
export function Spacer({ orientation = "vertical", rem = 1 }: SpacerProps) {
  const isVertical = orientation === "vertical";
  const size = `${rem}rem`;

  return (
    <div
      style={{
        height: isVertical ? size : undefined,
        width: !isVertical ? size : undefined,
      }}
    />
  );
}
