import type { ReactNode, SVGProps } from "react";

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
export type SizeVariants =
  | "fit"
  | "full"
  | "xl"
  | "lg"
  | "md"
  | "sm"
  | "xs"
  | "2xs";

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
export type ContainerSizeVariants = Exclude<SizeVariants, "full" | "xl">;

/**
 * A corner radius, on the same scale as {@link Spacing}: `N` is `N / 4` rem, so
 * `rounding={2}` is the same distance as `padding={2}`.
 *
 * | Step     | rem     | px  |
 * |----------|---------|-----|
 * | `0.5`    | `0.125` | 2   |
 * | `1`      | `0.25`  | 4   |
 * | `2`      | `0.5`   | 8   |
 * | `3`      | `0.75`  | 12  |
 * | `4`      | `1`     | 16  |
 * | `5`      | `1.25`  | 20  |
 * | `"full"` | —       | pill (`--radius-round`) |
 *
 * Closed, where `Spacing` is an open number: the radius tokens are a fixed
 * design set, and an arbitrary radius is never what a caller wants. `"full"` is
 * a string rather than `Infinity` because TypeScript has no literal type for
 * `Infinity` — including it would widen the whole union back to `number`.
 *
 * Converted with {@link roundingToRem}, not looked up as a class.
 */
export type Rounding = 0.5 | 1 | 2 | 3 | 4 | 5 | "full";

/**
 * Extreme size variants ("fit" and "full" only).
 *
 * Used for width and height properties that only support extremal values.
 */
export type ExtremaSizeVariants = Extract<SizeVariants, "fit" | "full">;

// ---------------------------------------------------------------------------
// Spacing Scale
// ---------------------------------------------------------------------------

/**
 * A spacing step. `N` is `N / 4` rem, so `4` is `1rem` and `2` is `0.5rem`.
 *
 * This borrows Tailwind's scale as an interface, not as an implementation — a
 * step reads the same here as in a class name, so a `padding` of `2` is the same
 * distance as `p-2`. The value is converted with {@link spacingToRem} rather
 * than looked up as a class, which keeps the scale open: any step works,
 * including ones Tailwind does not ship.
 *
 * Replaces the named scales. `PaddingVariants` meant one distance on a card and
 * a different one on a container; a number cannot be ambiguous that way.
 */
export type Spacing = number;

/**
 * Shadow depth variants.
 *
 * | Variant  | Effect                          |
 * |----------|---------------------------------|
 * | `"none"` | No shadow (default)             |
 * | `"sm"`   | Subtle lift (`--shadow-01`)     |
 * | `"md"`   | Medium elevation (`--shadow-02`)|
 * | `"lg"`   | Strong elevation (`--shadow-03`)|
 */
export type ShadowVariants = "none" | Extract<SizeVariants, "sm" | "md" | "lg">;

/**
 * Size variants with numeric overrides.
 *
 * Allows size specification as a named preset or a custom numeric value.
 * Used in components that need programmatic sizing flexibility.
 */
export type OverridableExtremaSizeVariants = ExtremaSizeVariants | number;

// ---------------------------------------------------------------------------
// Orientation Variants
// ---------------------------------------------------------------------------

/** Axis orientation — `"horizontal"` or `"vertical"`. */
export type OrientationVariants = "horizontal" | "vertical";

// ---------------------------------------------------------------------------
// Border Variants
// ---------------------------------------------------------------------------

/**
 * Border style variants shared across card-like surfaces.
 *
 * - `"none"`: no border.
 * - `"dashed"`: dashed border.
 * - `"solid"`: solid border.
 */
export type BorderVariants = "none" | "dashed" | "solid";

/**
 * Background fill variants shared across card-like surfaces.
 *
 * - `"none"`: transparent background.
 * - `"light"`: lightly tinted background.
 * - `"heavy"`: heavily tinted background.
 */
export type BackgroundVariants = "none" | "light" | "heavy";

// ---------------------------------------------------------------------------
// Color Types
// ---------------------------------------------------------------------------

/**
 * Semantic color roles used across the design system for foreground, border,
 * and other colorable surfaces.
 *
 * - `"default"` — standard text/border color (`text-04` / `border-01`)
 * - `"muted"` — de-emphasized color (`text-03`)
 * - `"danger"` — destructive / error state
 * - `"muted-success"` / `"muted-warning"`: status glyph against muted body text,
 *   for messages where the icon carries the state and the text stays secondary
 * - `"interactive"` — follows the interactive coloring system (`currentColor` / `--interactive-foreground`)
 */
export type ColorTypes =
  | "default"
  | "muted"
  | "success"
  | "danger"
  | "warning"
  | "muted-success"
  | "muted-warning"
  | "interactive";

// ---------------------------------------------------------------------------
// Status Variants
// ---------------------------------------------------------------------------

/**
 * Severity / status variants used by alert-style components (e.g. {@link
 * MessageCard}, {@link Card}'s `borderColor`). Each variant maps to a
 * dedicated background/border/icon palette in the design system.
 */
export type StatusVariants =
  | "default"
  | "info"
  | "success"
  | "warning"
  | "pending"
  | "error";

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
 * A branded wrapper marking React nodes as deliberate `Text` children.
 *
 * Created via the `richNodes()` function. `Text` renders the inner nodes
 * verbatim; the brand exists so arbitrary JSX is still rejected at the type
 * level and the opt-in stays visible at the call site, like `markdown()`.
 *
 * The main producer is i18n rich-text output (next-intl `t.rich(...)`), where
 * translated sentences embed inline components mid-sentence.
 *
 * Unlike `RichStr`, a `RichNodes` value cannot be reduced to a plain string,
 * so it is only accepted by `Text` children — never by `string | RichStr`
 * props, which must stay derivable for tooltips and aria labels.
 */
export interface RichNodes {
  readonly __brand: "RichNodes";
  readonly nodes: ReactNode;
}

// ---------------------------------------------------------------------------
// Input Variants
// ---------------------------------------------------------------------------

/**
 * Visual state variants for text input components.
 *
 * - `"primary"` — default editable state
 * - `"internal"` — subtle/borderless style for inline use
 * - `"error"` — error state with red border
 * - `"disabled"` — non-interactive, grayed out
 * - `"readOnly"` — visually transparent, not editable
 */
export type InputVariants =
  | "primary"
  | "internal"
  | "error"
  | "disabled"
  | "readOnly";

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
