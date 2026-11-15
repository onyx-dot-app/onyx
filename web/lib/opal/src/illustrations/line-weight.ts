/** Every illustration is drawn on a 120 × 120 viewBox. */
const VIEWBOX_SIZE = 120;

/** The design spec's small illustration size. The large one is the viewBox size. */
const SMALL_SIZE = 64;

/** Rendered line weights in px at the small and large design sizes. */
const SMALL_LINE_PX = 2.5;
const LARGE_LINE_PX = 3.5;

/** ViewBox stroke width for 2.5 px lines at 64 px and below, 3.5 px at 120 and above, linear between.
 * No size assumes 120, so a CSS-sized consumer must pass the size its CSS renders. */
function illustrationStrokeWidth(size?: number): number {
  if (size === undefined) return LARGE_LINE_PX;
  const clamped: number = Math.min(Math.max(size, SMALL_SIZE), VIEWBOX_SIZE);
  const px: number =
    SMALL_LINE_PX +
    ((clamped - SMALL_SIZE) * (LARGE_LINE_PX - SMALL_LINE_PX)) /
      (VIEWBOX_SIZE - SMALL_SIZE);
  return (px * VIEWBOX_SIZE) / size;
}

export { illustrationStrokeWidth };
