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
} from "@opal/types";

/**
 * Size-variant scale.
 *
 * Each entry maps a named preset to Tailwind utility classes for
 * `height`, `min-width`, `padding`, and `gap`.
 *
 * | Key   | Height        | Padding  | Gap      |
 * |-------|---------------|----------|----------|
 * | `lg`  | 2.25rem (36px)| `p-2`    | 0.5rem   |
 * | `md`  | 1.75rem (28px)| `p-1`    | 0.25rem  |
 * | `sm`  | 1.5rem (24px) | `p-1`    | 0.25rem  |
 * | `xs`  | 1.25rem (20px)| `p-0.5`  | 0.125rem |
 * | `2xs` | 1rem (16px)   | `p-0.5`  | 0.125rem |
 * | `fit` | h-fit         | `p-0`    | 0        |
 */
type ContainerProperties = {
  height: string;
  minWidth: string;
  padding: string;
  gap: string;
};
const containerSizeVariants: Record<
  ContainerSizeVariants,
  ContainerProperties
> = {
  fit: { height: "h-fit", minWidth: "", padding: "p-0", gap: "gap-0" },
  lg: {
    height: "h-[2.25rem]",
    minWidth: "min-w-[2.25rem]",
    padding: "p-2",
    gap: "gap-[0.5rem]",
  },
  md: {
    height: "h-[1.75rem]",
    minWidth: "min-w-[1.75rem]",
    padding: "p-1",
    gap: "gap-[0.25rem]",
  },
  sm: {
    height: "h-[1.5rem]",
    minWidth: "min-w-[1.5rem]",
    padding: "p-1",
    gap: "gap-[0.25rem]",
  },
  xs: {
    height: "h-[1.25rem]",
    minWidth: "min-w-[1.25rem]",
    padding: "p-0.5",
    gap: "gap-[0.125rem]",
  },
  "2xs": {
    height: "h-[1rem]",
    minWidth: "min-w-[1rem]",
    padding: "p-0.5",
    gap: "gap-[0.125rem]",
  },
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

export {
  type ExtremaSizeVariants,
  type ContainerSizeVariants,
  type OverridableExtremaSizeVariants,
  type SizeVariants,
  containerSizeVariants,
  widthVariants,
  heightVariants,
};
