import "@opal/components/cards/card/styles.css";
import type { PaddingVariants, RoundingVariants } from "@opal/types";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BackgroundVariant = "none" | "light" | "heavy";
type BorderVariant = "none" | "dashed" | "solid";

type CardProps = {
  /**
   * Padding preset.
   *
   * | Value   | Class   |
   * |---------|---------|
   * | `"lg"`  | `p-6`   |
   * | `"md"`  | `p-4`   |
   * | `"sm"`  | `p-2`   |
   * | `"xs"`  | `p-1`   |
   * | `"2xs"` | `p-0.5` |
   *
   * @default "sm"
   */
  paddingVariant?: PaddingVariants;

  /**
   * Border-radius preset.
   *
   * | Value  | Class        |
   * |--------|--------------|
   * | `"xs"` | `rounded-04` |
   * | `"sm"` | `rounded-08` |
   * | `"md"` | `rounded-12` |
   * | `"lg"` | `rounded-16` |
   *
   * @default "md"
   */
  roundingVariant?: RoundingVariants;

  /**
   * Background fill intensity.
   * - `"none"`: transparent background.
   * - `"light"`: subtle tinted background (`bg-background-tint-00`).
   * - `"heavy"`: stronger tinted background (`bg-background-tint-01`).
   *
   * @default "light"
   */
  backgroundVariant?: BackgroundVariant;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "none"
   */
  borderVariant?: BorderVariant;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  children?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// Mappings
// ---------------------------------------------------------------------------

const paddingForVariant: Record<PaddingVariants, string> = {
  lg: "p-6",
  md: "p-4",
  sm: "p-2",
  xs: "p-1",
  "2xs": "p-0.5",
};

const roundingForVariant: Record<RoundingVariants, string> = {
  lg: "rounded-16",
  md: "rounded-12",
  sm: "rounded-08",
  xs: "rounded-04",
};

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

function Card({
  paddingVariant = "sm",
  roundingVariant = "md",
  backgroundVariant = "light",
  borderVariant = "none",
  ref,
  children,
}: CardProps) {
  const padding = paddingForVariant[paddingVariant];
  const rounding = roundingForVariant[roundingVariant];

  return (
    <div
      ref={ref}
      className={cn("opal-card", padding, rounding)}
      data-background={backgroundVariant}
      data-border={borderVariant}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Card, type CardProps, type BackgroundVariant, type BorderVariant };
