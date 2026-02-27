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
//   - Content (HeadingLayout / LabelLayout)  (edit-button size)
// ---------------------------------------------------------------------------

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
const sizeVariants = {
  lg: { height: "h-[2.25rem]", minWidth: "min-w-[2.25rem]", padding: "p-2" },
  md: { height: "h-[1.75rem]", minWidth: "min-w-[1.75rem]", padding: "p-1" },
  sm: { height: "h-[1.5rem]", minWidth: "min-w-[1.5rem]", padding: "p-1" },
  xs: {
    height: "h-[1.25rem]",
    minWidth: "min-w-[1.25rem]",
    padding: "p-0.5",
  },
  "2xs": { height: "h-[1rem]", minWidth: "min-w-[1rem]", padding: "p-0.5" },
  fit: { height: "h-fit", minWidth: "", padding: "p-0" },
} as const;

/** Named size preset key. */
type SizeVariant = keyof typeof sizeVariants;

// ---------------------------------------------------------------------------
// Width Variants
//
// A named scale of width presets that map to Tailwind width utility classes.
//
// Consumers:
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
 * | `full` | `w-full`       |
 */
const widthVariants = {
  auto: "w-auto",
  full: "w-full",
} as const;

/** Named width preset key. */
type WidthVariant = keyof typeof widthVariants;

export { sizeVariants, type SizeVariant, widthVariants, type WidthVariant };
