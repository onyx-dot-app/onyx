/**
 * @opal/shared — Shared constants and types for the opal design system.
 *
 * This module holds design tokens that are referenced by multiple opal
 * packages (core, components, layouts). Centralising them here avoids
 * circular imports and gives every consumer a single source of truth.
 */

// ---------------------------------------------------------------------------
// Size Variants
//
// A named scale of size presets (lg → 2xs, plus fit) that map to Tailwind
// utility classes for height, min-width, and padding.
//
// Consumers:
//   - Interactive.Container  (height + min-width + padding)
//   - Button                 (icon sizing)
//   - ContentAction          (padding only)
//   - Content (ContentXl / ContentLg / ContentMd)  (edit-button size)
// ---------------------------------------------------------------------------

type StandardDiscrimatedSizeVariants =
  | "fit"
  | "lg"
  | "md"
  | "sm"
  | "xs"
  | "2xs";
type ExtremaSizeVariants = "fit" | "full" | "auto";

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
const lineSizeVariants: Record<
  StandardDiscrimatedSizeVariants,
  { height: string; minWidth: string; padding: string }
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
  auto: "w-auto",
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
  auto: "h-auto",
  fit: "h-fit",
  full: "h-full",
} as const;

export {
  lineSizeVariants,
  type StandardDiscrimatedSizeVariants,
  widthVariants,
  heightVariants,
  type ExtremaSizeVariants,
};
