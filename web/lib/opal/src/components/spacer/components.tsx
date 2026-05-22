// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SpacerSize =
  | { rem?: number; pixels?: never }
  | { pixels: number; rem?: never };

export type SpacerProps = SpacerSize & {
  vertical?: boolean;
  horizontal?: boolean;
};

// ---------------------------------------------------------------------------
// Spacer
// ---------------------------------------------------------------------------

/**
 * A zero-content element that inserts a fixed-size gap.
 *
 * Defaults to vertical spacing of 1rem. Supply either `rem` or `pixels`,
 * and either `vertical` or `horizontal` (vertical is the default).
 *
 * @example
 * ```tsx
 * <Spacer vertical rem={2} />
 * <Spacer horizontal pixels={8} />
 * ```
 */
export function Spacer({ vertical, horizontal, rem = 1, pixels }: SpacerProps) {
  const isVertical = vertical ? true : horizontal ? false : true;
  const size = pixels !== undefined ? `${pixels}px` : `${rem}rem`;

  return (
    <div
      style={{
        height: isVertical ? size : undefined,
        width: !isVertical ? size : undefined,
      }}
    />
  );
}
