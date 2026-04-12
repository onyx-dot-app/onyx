/**
 * @opal/shared — Shared constants and types for the opal design system.
 *
 * This module holds design tokens that are referenced by multiple opal
 * packages (core, components, layouts). Centralising them here avoids
 * circular imports and gives every consumer a single source of truth.
 */

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
 * | Key   | Height        | Padding  |
 * |-------|---------------|----------|
 * | `lg`  | 2.25rem (36px)| `p-2`   |
 * | `md`  | 1.75rem (28px)| `p-1`   |
 * | `sm`  | 1.5rem (24px) | `p-1`   |
 * | `xs`  | 1.25rem (20px)| `p-0.5` |
 * | `2xs` | 1rem (16px)   | `p-0.5` |
 * | `fit` | h-fit         | `p-0`   |
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
  lg: { height: "h-[2.25rem]", minWidth: "min-w-[2.25rem]", padding: "p-2" },
  md: { height: "h-[1.75rem]", minWidth: "min-w-[1.75rem]", padding: "p-1" },
  sm: { height: "h-[1.5rem]", minWidth: "min-w-[1.5rem]", padding: "p-1" },
  xs: {
    height: "h-[1.25rem]",
    minWidth: "min-w-[1.25rem]",
    padding: "p-0.5",
  },
  "2xs": { height: "h-[1rem]", minWidth: "min-w-[1rem]", padding: "p-0.5" },
} as const;

// ---------------------------------------------------------------------------
// Width/Height Variants
//
// A named scale of width/height presets that map to Tailwind width/height utility classes.
//
// Consumers (for width):
//   - Interactive.Container  (widthVariant)
//   - Button                 (width)
//   - Content                (widthVariant)
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
//   - Card          (paddingVariant, roundingVariant)
//   - SelectCard    (paddingVariant, roundingVariant)
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
  lg: "rounded-16",
  md: "rounded-12",
  sm: "rounded-08",
  xs: "rounded-04",
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
  widthVariants,
  heightVariants,
};
