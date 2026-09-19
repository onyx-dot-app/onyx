/**
 * @opal/shared — Shared constants and types for the opal design system.
 *
 * This module holds design tokens that are referenced by multiple opal
 * packages (core, components, layouts). Centralising them here avoids
 * circular imports and gives every consumer a single source of truth.
 */

import "@opal/root.css";

import type {
  SizeVariants,
  OverridableExtremaSizeVariants,
  ContainerSizeVariants,
  ExtremaSizeVariants,
  Rounding,
  Spacing,
} from "@opal/types";

/**
 * Size-variant scale.
 *
 * Each entry maps a named preset to Tailwind utility classes for
 * `height`, `min-width`, and `padding`.
 *
 * Heights are driven by CSS custom properties defined in `@opal/root.css`.
 *
 * | Key   | Height                          | Padding  |
 * |-------|---------------------------------|----------|
 * | `lg`  | `--height-line-h1-headline`     | `p-2`   |
 * | `md`  | `--height-line-h3-section`      | `p-1`   |
 * | `sm`  | `--height-line-label`           | `p-1`   |
 * | `xs`  | `--height-line-main`            | `p-0.5` |
 * | `2xs` | `--height-line-secondary`       | `p-0.5` |
 * | `fit` | `h-fit`                         | `p-0`   |
 */
type ContainerProperties = {
  height: string;
  minWidth: string;
  padding: string;
};
const containerSizeVariants: Record<
  ContainerSizeVariants,
  ContainerProperties
> = {
  fit: { height: "h-fit", minWidth: "", padding: "p-0" },
  lg: {
    height: "h-(--height-line-h1-headline)",
    minWidth: "min-w-(--height-line-h1-headline)",
    padding: "p-2",
  },
  md: {
    height: "h-(--height-line-h3-section)",
    minWidth: "min-w-(--height-line-h3-section)",
    padding: "p-1",
  },
  sm: {
    height: "h-(--height-line-label)",
    minWidth: "min-w-(--height-line-label)",
    padding: "p-1",
  },
  xs: {
    height: "h-(--height-line-main)",
    minWidth: "min-w-(--height-line-main)",
    padding: "p-0.5",
  },
  "2xs": {
    height: "h-(--height-line-secondary)",
    minWidth: "min-w-(--height-line-secondary)",
    padding: "p-0.5",
  },
} as const;

// ---------------------------------------------------------------------------
// Width/Height Variants
//
// A named scale of width/height presets that map to Tailwind width/height utility classes.
//
// Consumers (for width):
//   - Interactive.Container  (width)
//   - Button                 (width)
//   - Content                (width)
// ---------------------------------------------------------------------------

/**
 * Width-variant scale.
 *
 * | Key    | Tailwind class |
 * |--------|----------------|
 * | `auto` | `w-auto`       |
 * | `fit`  | `w-fit`        |
 * | `full` | `w-full`       |
 */
const widthVariants: Record<ExtremaSizeVariants, string> = {
  fit: "w-fit",
  full: "w-full",
} as const;

/**
 * Height-variant scale.
 *
 * | Key    | Tailwind class |
 * |--------|----------------|
 * | `auto` | `h-auto`       |
 * | `fit`  | `h-fit`        |
 * | `full` | `h-full`       |
 */
const heightVariants: Record<ExtremaSizeVariants, string> = {
  fit: "h-fit",
  full: "h-full",
} as const;

// ---------------------------------------------------------------------------
// Card Variants
//
// Shared padding and rounding scales for card components (Card, SelectCard).
//
// Consumers:
//   - Card          (padding, rounding)
//   - SelectCard    (padding, rounding)
// ---------------------------------------------------------------------------

/**
 * Converts a spacing step to a CSS length: `N` is `N / 4` rem.
 *
 * Kept as a function rather than a class lookup so the scale stays open —
 * Tailwind cannot build a class name from a runtime value, but arithmetic can.
 */
function spacingToRem(spacing: Spacing): string {
  return `${spacing / 4}rem`;
}

/**
 * Converts a {@link Rounding} step to a CSS length.
 *
 * Separate from {@link spacingToRem} because of `"full"` — a pill has no step
 * on the scale, and folding that case into the spacing converter would make
 * `padding="full"` mean 62.5rem, which is meaningless.
 */
function roundingToRem(rounding: Rounding): string {
  return rounding === "full" ? "var(--radius-round)" : spacingToRem(rounding);
}

export {
  type ExtremaSizeVariants,
  type ContainerSizeVariants,
  type OverridableExtremaSizeVariants,
  type Rounding,
  type SizeVariants,
  type Spacing,
  containerSizeVariants,
  spacingToRem,
  roundingToRem,
  widthVariants,
  heightVariants,
};
