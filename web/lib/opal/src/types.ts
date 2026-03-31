import type { SVGProps } from "react";

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

// Base Size Types:

/**
 * Full range of size variants.
 *
 * This is the complete scale of size presets available in the design system.
 * Components needing the full range use this type directly.
 */
export type SizeVariants = "fit" | "full" | "lg" | "md" | "sm" | "xs" | "2xs";

// Convenience Size Types:
//
// NOTE (@raunakab + @nmgarza5)
// There are many components throughout the library that need to "extract" very specific sizings from the full gamut that is available.
// For those components, we've extracted these below "convenience" types.

/**
 * Size variants for container components (excludes "full").
 *
 * Used by components that control height, min-width, and padding.
 * Excludes "full" since containers need a fixed height preset.
 */
export type ContainerSizeVariants = Exclude<SizeVariants, "full">;

/**
 * Padding size variants.
 *
 * | Variant | Class   |
 * |---------|---------|
 * | `lg`    | `p-6`   |
 * | `md`    | `p-4`   |
 * | `sm`    | `p-2`   |
 * | `xs`    | `p-1`   |
 * | `2xs`   | `p-0.5` |
 */
export type PaddingVariants = Extract<
  SizeVariants,
  "lg" | "md" | "sm" | "xs" | "2xs"
>;

/**
 * Rounding size variants.
 *
 * | Variant | Class        |
 * |---------|--------------|
 * | `lg`    | `rounded-16` |
 * | `md`    | `rounded-12` |
 * | `sm`    | `rounded-08` |
 * | `xs`    | `rounded-04` |
 */
export type RoundingVariants = Extract<SizeVariants, "lg" | "md" | "sm" | "xs">;

/**
 * Extreme size variants ("fit" and "full" only).
 *
 * Used for width and height properties that only support extremal values.
 */
export type ExtremaSizeVariants = Extract<SizeVariants, "fit" | "full">;

/**
 * Size variants with numeric overrides.
 *
 * Allows size specification as a named preset or a custom numeric value.
 * Used in components that need programmatic sizing flexibility.
 */
export type OverridableExtremaSizeVariants = ExtremaSizeVariants | number;

// ---------------------------------------------------------------------------
// Icon Props
// ---------------------------------------------------------------------------

/**
 * Base props for SVG icon components.
 *
 * Extends standard SVG element attributes with convenience props used across
 * the design system. All generated icon components (in `@opal/icons`) accept
 * this interface, ensuring a consistent API for sizing, coloring, and labeling.
 *
 * @example
 * ```tsx
 * import type { IconProps } from "@opal/types";
 *
 * function MyIcon({ size = 16, className, ...props }: IconProps) {
 *   return (
 *     <svg width={size} height={size} className={className} {...props}>
 *       ...
 *     </svg>
 *   );
 * }
 * ```
 */
export interface IconProps extends SVGProps<SVGSVGElement> {
  className?: string;
  size?: number;
  title?: string;
  color?: string;
}

/** Strips `className` and `style` from a props type to enforce design-system styling. */
export type WithoutStyles<T> = Omit<T, "className" | "style">;

// ---------------------------------------------------------------------------
// Rich Strings
// ---------------------------------------------------------------------------

/**
 * A branded string wrapper that signals inline markdown should be parsed.
 *
 * Created via the `markdown()` function. Components that accept `string | RichStr`
 * will parse the inner `raw` string as inline markdown when a `RichStr` is passed,
 * and render plain text when a regular `string` is passed.
 *
 * This avoids "API coloring" — components don't need a `markdown` boolean prop,
 * and intermediate wrappers don't need to thread it through. The decision to
 * use markdown lives at the call site via `markdown("*bold* text")`.
 */
export interface RichStr {
  readonly __brand: "RichStr";
  readonly raw: string;
}

/**
 * HTML button `type` attribute values.
 *
 * Used by interactive primitives and button-like components to indicate that
 * the element is inherently interactive for cursor-styling purposes, even
 * without an explicit `onClick` or `href`.
 */
export type ButtonType = "submit" | "button" | "reset";

/** Like `Omit` but distributes over union types, preserving discriminated unions. */
export type DistributiveOmit<T, K extends keyof any> = T extends any
  ? Omit<T, K>
  : never;

/**
 * A React function component that accepts {@link IconProps}.
 *
 * Use this type when a component prop expects an icon — it ensures the icon
 * supports `className`, `size`, `title`, and `color` without callers needing
 * to import `IconProps` directly.
 *
 * @example
 * ```tsx
 * import type { IconFunctionComponent } from "@opal/types";
 *
 * interface ButtonProps {
 *   icon?: IconFunctionComponent;
 * }
 * ```
 */
export type IconFunctionComponent = React.FunctionComponent<IconProps>;
