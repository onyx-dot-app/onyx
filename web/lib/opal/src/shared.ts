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
  PaddingVariants,
  RoundingVariants,
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

const paddingVariants: Record<PaddingVariants, string> = {
  lg: "p-6",
  md: "p-4",
  sm: "p-2",
  xs: "p-1",
  "2xs": "p-0.5",
  fit: "p-0",
};

const paddingXVariants: Record<PaddingVariants, string> = {
  lg: "px-6",
  md: "px-4",
  sm: "px-2",
  xs: "px-1",
  "2xs": "px-0.5",
  fit: "px-0",
};

const paddingYVariants: Record<PaddingVariants, string> = {
  lg: "py-6",
  md: "py-4",
  sm: "py-2",
  xs: "py-1",
  "2xs": "py-0.5",
  fit: "py-0",
};

const cardRoundingVariants: Record<RoundingVariants, string> = {
  xl: "rounded-20",
  lg: "rounded-16",
  md: "rounded-12",
  sm: "rounded-08",
  xs: "rounded-04",
};

const cardTopRoundingVariants: Record<RoundingVariants, string> = {
  xl: "rounded-t-20",
  lg: "rounded-t-16",
  md: "rounded-t-12",
  sm: "rounded-t-08",
  xs: "rounded-t-04",
};

const cardBottomRoundingVariants: Record<RoundingVariants, string> = {
  xl: "rounded-b-20",
  lg: "rounded-b-16",
  md: "rounded-b-12",
  sm: "rounded-b-08",
  xs: "rounded-b-04",
};

export {
  type ExtremaSizeVariants,
  type ContainerSizeVariants,
  type OverridableExtremaSizeVariants,
  type SizeVariants,
  containerSizeVariants,
  paddingVariants,
  paddingXVariants,
  paddingYVariants,
  cardRoundingVariants,
  cardTopRoundingVariants,
  cardBottomRoundingVariants,
  widthVariants,
  heightVariants,
};
